# Harbor & Vale — Orchestration Architecture

> **Scope of this document.** It records the orchestration decision for the CrewAI
> layer and the runtime behaviour the Phase 1 spike proved. Everything here is
> **scoped to the pinned `crewai==1.15.20`** on project Python 3.12.14. Any change
> to the `crewai` pin invalidates these findings until the Phase 1 spikes
> (`spike/task_1_1_*.py` … `spike/task_1_6_*.py`) are re-run.
>
> The authoritative architecture and plan remain `PROJECT_PLAN.md`. This document
> satisfies the Phase 1 acceptance criterion "the decision is written to
> `docs/architecture.md`" (§T Phase 1) and §C.2.4.

---

## 1. Core principle — Agent Plans, Python Executes

An agent (LLM) never writes a CSV, computes a statistic, or decides PASS/FAIL. It
produces a **structured plan**; a Pydantic guardrail validates that plan;
**deterministic Python performs every precision-critical step** (cleaning,
measurement, contract building, validation, model selection) and writes every
artifact. LLM output may vary between runs; execution stays deterministic and
auditable, and each plan is persisted as an artifact.

```
┌──────────────┐  structured JSON  ┌──────────────┐  if invalid   ┌────────────────┐
│  Agent (LLM) │ ─────────────────▶│  guardrail   │ ── retry ────▶│ Python executor │
│  judgement   │                   │  Pydantic    │  then fail    │  deterministic  │
└──────────────┘                   └──────────────┘  visibly      └────────────────┘
```

---

## 2. Selected orchestration pattern — **PATTERN A**

**Decision: Pattern A.** Each crew is **one `Crew` of 3 agents and 3 `Task`s in
`Process.sequential`**. Each task carries `output_pydantic` + a `guardrail` +
`guardrail_max_retries` + a `callback` (deterministic Python) + explicit
`context=[…]`. The task's `callback` runs the deterministic step (execute the
plan, measure, write the artifact) and finishes before the next task's agent
starts; the next agent reads the fresh artifact through a scoped read tool and
receives the prior task's validated output text via `context=`.

```
inspect_task   Agent → CleaningPlan (output_pydantic + guardrail)
               → callback: execute_plan() → artifacts/crew1/clean_data.csv + profile
eda_task       Agent (context=[inspect_task]) → InsightsDoc (+ guardrail)
               → callback: render eda_report.html + insights.md
contract_task  Agent (context=[inspect_task, eda_task]) → ContractDraft (+ guardrail)
               → callback: builder.py merges draft + measured facts + sha256 → dataset_contract.json
```

A CrewAI **Flow** (`Flow[PipelineState]`) wraps the two crews, calls each with
`Crew().kickoff(inputs=…)`, runs the deterministic **validation gate** in a Flow
method, and `@router`s on the gate result.

### Why Pattern A is safe (runtime evidence)

| Concern | Evidence (spike) |
|---|---|
| The `Agent → Python → Agent` interleaving happens inside **one** sequential crew | **Task 1.3:** a `Task.callback` runs **synchronously**, **fully completes before the next sequential task's agent starts**, and **blocks** the crew loop. Event order `task1_agent → callback_START → callback_FINISH → task2_agent`; a 300 ms sleep in the callback delayed task 2 by >300 ms. |
| The callback's artifact is actually on disk for the next agent | **Task 1.3:** a file written + `flush` + `os.fsync` + `close` in task 1's callback was read back **byte-for-byte** by task 2's agent. |
| The next agent gets the prior **validated, final** output | **Task 1.4:** `context=[t1]` injects `t1.output.raw` verbatim (post-guardrail, post-callback); a guardrail-**rejected** attempt never leaks; multiple context tasks render in **list order**. |
| Structured plans are enforced | **Task 1.1:** `output_pydantic` yields a validated model on `TaskOutput.pydantic` / `CrewOutput.pydantic`, or the run raises `pydantic.ValidationError` — invalid data cannot escape as a half-built object. |
| Invalid plans retry with feedback, then fail visibly | **Task 1.2:** `guardrail` returning `(False, msg)` retries with `msg` fed into the next prompt; `guardrail_max_retries` (default 3) attempts then a plain `Exception`; nothing invalid escapes. |
| Tool action space can be constrained mechanically | **Task 1.5:** a `Literal[...]` tool arg is enforced by pydantic **before the tool body**, for `@tool` and `BaseTool`. |
| The Flow / router / crew-from-Flow all work | **Task 1.6:** `Flow[StateModel]`, `@start`/`@listen`, `@router` (string labels, single branch), `or_`/`and_`, and `Crew.kickoff(inputs=…)` from inside a Flow method. |

### Why Pattern B is not primary

Pattern B (split each crew into ≥2 `kickoff()` stages with Python wired between
them in the Flow — §C.2.3) exists **only** for the case where a task's `callback`
does **not** complete before the next task's agent runs. Task 1.3 disproved that
for `crewai==1.15.20`: the callback is synchronous and blocking. Pattern B adds an
unusual crew shape (two `crew()` methods with task subsets) and moves
orchestration out of the crew into the Flow, for no behaviour Pattern A lacks. It
is retained as a **documented fallback**, not the primary design.

### Conditions that trigger a later fallback to Pattern B

Re-run the Phase 1 spikes after **any** of these, and switch the affected crew to
Pattern B (§C.2.3) if the check fails:

1. **A `crewai` version bump** changes `Task.callback` timing so a callback no
   longer fully completes before the next sequential task's agent starts
   (re-run `spike/task_1_3_callback_ordering.py`).
2. A required callback must be genuinely **async** in a way `_execute_core`'s
   `asyncio.run(cb_result)` cannot handle cleanly.
3. `guardrail` / retry semantics change such that a critical structured plan can
   no longer be made to **fail visibly** (re-run `spike/task_1_2_*`).
4. `context=` or `output_pydantic` semantics change such that a downstream agent
   can no longer be given the prior task's **final validated** output
   (re-run `spike/task_1_1_*` and `spike/task_1_4_*`).

---

## 3. Proven CrewAI 1.15.20 behaviour (spike findings)

### 4. `output_pydantic` (Task 1.1)

- `Task(output_pydantic=Model)` — field type `type[pydantic.BaseModel] | None`.
- Success: `CrewOutput.pydantic` **and** `task.output.pydantic` are a real instance
  of the model; `task.output.output_format == OutputFormat.PYDANTIC`;
  `task.output.raw` is the JSON string; `json_dict` stays `None` (that is for
  `output_json`).
- Coercion is **pydantic v2 lax** (`"7"` → `7`), not strict — strict semantic
  checks belong in the guardrail.
- Invalid output → `crew.kickoff()` raises `pydantic.ValidationError` (uncoercible
  type and missing-required-field both). Invalid data **cannot** escape as a
  half-built model; the only non-raising failure mode leaves `.pydantic = None`.
- Enforcement (plain-text agent output, no guardrail) is a deterministic pydantic
  step **inside `Task`** (`_export_output → convert_to_model →
  model.model_validate_json`), after the agent runs — **not** the LLM's own
  mechanism.

### 5. `guardrail` + retry (Task 1.2)

- `Task(guardrail=fn)` — `fn` takes **exactly one** positional arg, receives a
  `TaskOutput`, returns `tuple[bool, Any]`. `(True, data)` (data ≠ `None`; may be a
  `str` or a whole `TaskOutput`) or `(False, msg)`.
- `(False, msg)` → **retry**, with `msg` rendered into the next attempt's prompt
  via the i18n `validation_error` template ("### Previous attempt failed
  validation: … ### Previous result: … Try again …").
- **`guardrail_max_retries: int = 3` is authoritative.** `max_retries` is a
  **deprecated** alias (removal in CrewAI v1.0.0) that emits a `DeprecationWarning`
  and is copied into `guardrail_max_retries`. Plan wants 2 → **set
  `guardrail_max_retries=2` explicitly.**
- Total guardrail evaluations and agent invocations = `guardrail_max_retries + 1`.
- Never passes → a **plain `builtins.Exception`** ("Task failed guardrail
  validation after N retries. Last error: …") — **no dedicated guardrail-error
  class**; `task.output` is `None`, nothing invalid escapes.
- **PEP 563 gotcha:** with `from __future__ import annotations` in the guardrail's
  module, an annotated `-> tuple[bool, Any]` becomes a string and
  `Task(guardrail=fn)` raises at construction. Omit the guardrail return
  annotation, or don't use that import in guardrail modules.

### 6. Required guardrail structural-parse behaviour

Ordering (Task 1.2 Experiment D): with a `guardrail` set and a plain-string agent
result, **pydantic parsing is skipped on the initial pass**; the guardrail runs
first with `task_output.pydantic is None` and only `task_output.raw` populated;
`output_pydantic` validation runs **after** the guardrail returns success (or
during a retry). Consequences:

- A structurally-broken output that the **guardrail approves** raises
  `pydantic.ValidationError` out of `kickoff()` **after** the guardrail — the
  retry loop does not catch it.
- An all-invalid retry sequence raises `ValidationError` **mid-loop**, not the
  "after N retries" `Exception`.

**Production rule:** every Harbor & Vale guardrail must **parse `output.raw`
itself** (own the Pydantic parse — do not assume `output.pydantic` is set) and
return `(False, msg)` on structural failure, so structural errors flow through the
retry-with-feedback-then-fail-visibly path instead of escaping as a bare
`ValidationError`.

### 7. Callback sequencing guarantee (Task 1.3)

`Task._execute_core`: the `callback` is called **after** the guardrail loop and
`self.output = task_output`, **before** the `output_file` save / `TaskCompletedEvent`
/ `return`. `Crew._execute_tasks` runs non-async tasks via a synchronous
`task.execute_sync(...)` in a plain loop, so:

- `Task N`'s callback **runs synchronously, blocks the crew loop, and fully
  finishes before `Task N+1`'s agent starts.**
- The callback input is a `TaskOutput` (`.pydantic` populated when
  `output_pydantic` succeeded; `output_format == PYDANTIC`).
- The callback's **return value is discarded** (only a coroutine is `asyncio.run`).
- A callback that **raises** propagates the **original** exception (e.g.
  `RuntimeError`) out of `kickoff()`, halts the crew, and `Task N+1` never runs.
- Closure callbacks emit `UserWarning: function callbacks cannot be serialized …`
  → Crew 1/2 callbacks must be **module-level named functions**.

### 8. `context=[task]` is RAW prompt context, not a typed handoff (Task 1.4)

`Crew._get_context → aggregate_raw_outputs_from_tasks → DIVIDERS.join(o.raw …)`,
`DIVIDERS = "\n\n----------\n\n"`, passed as `context=` to `agent.execute_task` and
wrapped by the i18n `task_with_context` template. So:

- The downstream agent receives the upstream task's **`.raw` string, verbatim** —
  **not** `.pydantic`, **not** a repr, **not** `.json_dict`.
- It reads the **final** `t1.output` (post-guardrail, post-callback); a rejected
  guardrail attempt never leaks.
- `context=[t1, t2]` renders both in **list order**, divider-joined.

**Production rule:** `context=` is for narrative continuity. The **contract itself
travels as the callback-written artifact**, read downstream through a scoped read
tool — never as a `context=` string.

### 9. Explicit-context requirement

Omitting `context=` is **not** "no context": the default sentinel `NOT_SPECIFIED`
makes CrewAI inject **every prior task's output**. **Every Harbor & Vale `Task`
must set `context=` explicitly** to control exactly what each agent sees (the Plan
pseudocode already does).

### 10. `Literal` tool boundary (Task 1.5)

- `@tool` (`CrewStructuredTool`): `.invoke → _parse_args →
  args_schema.model_validate(raw) → THEN func(**parsed)`.
- `BaseTool`: `.run → _validate_kwargs → args_schema.model_validate(kwargs) → THEN
  _run(**kwargs)`.
- Both build `args_schema` from the signature; a `Literal[...]` arg compiles to a
  JSON-Schema **`enum`**. An out-of-set value raises `ValueError`
  (`type=literal_error`) **before the tool body**; the agent gets the error and the
  allowed values back and can correct.
- **Handoff answer:** `HandoffName = Literal["clean_data", "dataset_contract"]` on
  `read_handoff(name: HandoffName)` **mechanically rejects `read_handoff("raw_data")`
  before any read** (§G.0 layer 1). Layer 2 — the exact-file allowlist, `../` and
  symlink defence — is **separate deterministic Python** (Phase 5), not a CrewAI
  feature.

### 11. Flow / router (Task 1.6)

- `Flow[StateModel]` — typed, mutable, observable via `flow.state`; CrewAI wraps
  the model as `StateWithId(FlowState, <model>)` and adds an `id` field
  (`isinstance(state, <model>)` is `True`). `kickoff(inputs=…)` merges inputs into
  state and returns the last leaf method's value.
- `@start` → `@listen` chains run in deterministic order.
- `@router` returns a **plain string label**; only the matching `@listen("LABEL")`
  runs.
- `or_(a, b)` fires its listener **once**, when the **first** trigger completes
  (not re-fired for the second). `and_(a, b)` fires **once**, only after **all**.
- `Crew.kickoff(inputs=…)` works from inside a Flow method: inputs reach the crew
  prompt (`{placeholder}` interpolation), the `CrewOutput` returns to the Flow, and
  the Flow continues to downstream `@listen`s.

### 12. Failure behaviour

| Failure | CrewAI 1.15.20 behaviour | Production handling |
|---|---|---|
| `output_pydantic` invalid, no guardrail | `crew.kickoff()` raises `pydantic.ValidationError` | critical agents: catch → `status="halted_agent_failure"` |
| guardrail never passes | plain `Exception` after `guardrail_max_retries` | same; persist the rejected plan to `_internal/` |
| callback raises | original exception propagates out of `kickoff()`, crew halts, next task skipped | wrap; map to `status` + `failure_category`; narrative agents → visible `DEGRADED` banner, never silent |
| `@router` emits a label with **no** `@listen` | `kickoff()` returns that label, Flow **ends silently** | routers must only emit labels that have listeners (`gate_passed` / `gate_failed`, both wired) |
| a Flow node raises | original exception propagates out of `Flow.kickoff()` | Phase 8 wraps crew/gate calls, maps to `PipelineState.status` |

### 13. Pattern B fallback condition

See §2 "Conditions that trigger a later fallback to Pattern B" — primarily a
`crewai` bump that breaks the Task 1.3 callback-timing guarantee.

### 14. Boundaries production code must follow

1. **Guardrails own the Pydantic parse.** Parse `output.raw`; return `(False, msg)`
   on structural or semantic failure. Never assume `output.pydantic` is set at
   guardrail time. Never let a bare `ValidationError` escape a critical task.
2. **Set `context=` explicitly on every `Task`.** Treat it as narrative context,
   not the contract carrier.
3. **The contract travels as an artifact**, written by a deterministic callback and
   read downstream via a scoped `Literal`-named read tool — never via `context=`.
4. **Callbacks are module-level named functions**, synchronous, deterministic. A
   critical-agent callback failure → `status="halted_agent_failure"`. A
   narrative-agent callback failure → visible `DEGRADED` artifact + banner, never
   silent.
5. **Use `guardrail_max_retries` (set it to 2), never `max_retries`.**
6. **Handoff tools use `Literal` logical names and have no path parameter**
   (§G.0 layer 1). The exact-file allowlist / `../` / symlink defence is separate
   deterministic Python (§G.0 layer 2, Phase 5).
7. **`@router` methods only emit labels that have `@listen` handlers.** An
   unlistened label silently stops the Flow.
8. **Wrap every crew/gate call in the Flow** so a raised exception becomes a
   `PipelineState` status transition, not an uncaught crash.
9. **PASS/FAIL at the gate is deterministic Python**, never an LLM, never a
   guardrail, never a router condition that consults an LLM (§A1, §F).
10. Do not use `from __future__ import annotations` in modules that define
    guardrail functions with annotated return types (PEP 563 gotcha, §5).
11. **All of the above is verified only for `crewai==1.15.20`.** Re-run
    `spike/task_1_*.py` after any pin change before trusting these boundaries.

---

## Addendum (Phase 3, CORRECTED in Session 18) — the guardrail return annotation CrewAI requires

Discovered wiring `harbor_vale.plans.contract_draft.validate_contract_draft` into
a real `Task(guardrail=...)` against the pinned `crewai==1.15.20`, refining §5/§14.10
above (not a contradiction — an added precision the Phase 1 spike did not need,
since its guardrails were never constructed as a real `Task`).

> **Correction (Session 18).** The version of this addendum first written in
> Session 17 over-claimed: it said CrewAI requires the *exact legacy spelling*
> `typing.Tuple[bool, typing.Any]` and that the modern `tuple[bool, Any]`
> fails. That claim was never actually tested — Session 17's comparison used
> `tuple[bool, object]` (note: `object`, not `Any`) against
> `Tuple[bool, Any]`, which changed **two** variables at once (the generic
> spelling *and* the second type argument) and drew a conclusion about the
> wrong one. Session 18 isolated each variable independently; the real rule
> is below, and it matches the Phase 1 Task 1.2 finding exactly — the hazard
> is stringized annotations, not spelling.

**Isolated verification (Session 18), same guardrail body, same `Task(...)`
construction, only the return annotation varied:**

| Case | Annotation (module-level, no `from __future__ import annotations` unless noted) | `Task(guardrail=fn)` |
|---|---|:---:|
| A | `-> tuple[bool, Any]` (PEP 585, modern) | **constructs cleanly** |
| B | `-> Tuple[bool, Any]` (`typing.Tuple`, legacy) | **constructs cleanly** |
| C | `-> tuple[bool, Any]`, but the module has `from __future__ import annotations` (annotation is stringized to `'tuple[bool, Any]'`) | **raises** `pydantic_core.ValidationError` |
| D | `-> tuple[bool, object]` (Session 17's original, real/non-stringized annotation — `object`, not `Any`) | **raises** `pydantic_core.ValidationError` |

Cases A and B prove `tuple[...]` vs. `Tuple[...]` makes no difference — Python's
typing system treats them as equal at runtime, and CrewAI's validator accepts
both. Case C reproduces the actual, real hazard: a **stringized** annotation
(from `from __future__ import annotations`) — this is exactly the Phase 1
Task 1.2 PEP 563 finding (§5 above), now confirmed to also apply to a real
`Task(guardrail=...)` construction, not just reasoned about from source.
Case D explains where Session 17's original failure actually came from: the
second type argument must be `Any` specifically — `object` (a real, valid,
non-stringized annotation) is rejected too, but for a completely different
reason than spelling.

```python
# FAILS — stringized (from __future__ import annotations in the module)
from __future__ import annotations
def fn(output) -> tuple[bool, Any]: ...
Task(guardrail=fn)
# pydantic_core.ValidationError: 1 validation error for Task
# guardrail
#   Value error, If return type is annotated, it must be Tuple[bool, Any]

# FAILS — real annotation, but `object` instead of `Any`
def fn(output) -> tuple[bool, object]: ...
Task(guardrail=fn)  # same ValidationError

# BOTH PASS — real (non-stringized) annotation, second arg is Any
def fn(output) -> tuple[bool, Any]: ...          # PEP 585 spelling — OK
def fn(output) -> Tuple[bool, Any]: ...          # typing.Tuple spelling — OK
```

**Production rule (corrected addendum to §14):** every Harbor & Vale
guardrail function must have a **real, non-stringized** return annotation
equal to `Tuple[bool, Any]` — either spelling (`tuple[bool, Any]` or
`Tuple[bool, Any]`) works identically — with the second type argument
literally `Any` (not `object`, not a narrower type), in a module that does
not import `from __future__ import annotations`. The binding constraint is
the Phase 1 PEP 563 rule (§5, §14.10): avoid stringized annotations in any
guardrail module. `src/harbor_vale/plans/contract_draft.py` already uses
`Tuple[bool, Any]` (the legacy spelling) — per this corrected finding that
remains valid but was never actually *required*; no code change follows
from this correction. Verified against `crewai==1.15.20`.

## Addendum (Phase 5) — `Task.guardrail` only counts REQUIRED parameters

The Sessions 17–18 guardrail-annotation rule covers the *return*
annotation. Phase 5 needed several guardrails that also take *context*
(`validate_cleaning_plan(output, *, profile=...)`,
`validate_feature_plan(output, *, contract=...)`, etc.) — cross-validating
an agent's plan against a real `DatasetProfile`/`DatasetContract` a bare
`output`-only signature cannot carry. Constructing one of these directly as
`Task(guardrail=fn)` first failed:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Task
guardrail
  Value error, Guardrail function must accept exactly one parameter
```

**Verified empirically against `crewai==1.15.20`:** this check counts only
parameters **without a default** — a keyword parameter carrying any default
value (including `None`) does not count against the limit, regardless of
how many such optional parameters exist:

```python
def g(output, *, a: int = 1, b: str = "x") -> Tuple[bool, Any]: ...
Task(description="d", expected_output="e", guardrail=g)   # constructs fine

def g2(output, ctx) -> Tuple[bool, Any]: ...               # ctx has no default
Task(description="d", expected_output="e", guardrail=g2)   # raises the error above
```

**Production rule this project now follows:** every `plans/*.py` guardrail
that needs external context gives that parameter a default of `None` and
returns `(False, "no <thing> supplied — this is a caller wiring error, not
a plan defect")` if it is ever actually called with `None` — never raises.
A real caller (Phase 6+) wraps the function in a one-argument closure per
`Task` instance that supplies the real context, e.g.
`lambda output: validate_cleaning_plan(output, profile=this_run_profile)`.
See `src/harbor_vale/plans/cleaning_plan.py`, `insights_doc.py`,
`feature_plan.py` for the pattern in place; `experiment_plan.py`'s
`task_type` parameter already had a meaningful default and needed no change.

---

## Addendum (Phase 6) — `task.output.pydantic` cannot be trusted after a
## successful guardrail, and the narrative-fallback forced-accept mechanism

Discovered wiring Crew 1's three real `Task(guardrail=...)`s against the
real pinned `crewai==1.15.20` (a scripted `BaseLLM`, no network — the same
technique as `spike/task_1_2_guardrail_retry.py`). Two related findings that
change how a Crew 1 (or any future) callback should read a guardrail's
validated result.

### Finding 1 — a guardrail returning `(True, <bare pydantic model>)` does
### NOT populate `task.output.pydantic`

`Task._invoke_guardrail_function` (crewai/task.py) only special-cases two
return shapes for `guardrail_result.result`:

- a `str` → sets `task_output.raw` to it and **re-runs** `_export_output`
  (i.e. `output_pydantic.model_validate_json`) on it, populating `.pydantic`.
- a `TaskOutput` → replaces `task_output` wholesale, **without** re-running
  `_export_output`.

Any other type (including the bare, already-parsed Pydantic model instance
every `plans/*.validate_*` function in this project returns on success,
e.g. `(True, CleaningPlan(...))`) falls through **both** branches — `task_output`
is returned completely unchanged from whatever it was before the guardrail
ran. Empirically verified: `task.output.pydantic` was `None` after a
guardrail returned `(True, <ToyNote instance>)`, while returning
`(True, out.raw)` (a string) correctly populated it.

**A second, independent surprise:** `task.output.pydantic` is **not**
reliably `None` even before a guardrail's own success on every attempt —
the Sessions 17-18 finding ("guardrail runs first with `task_output.pydantic
is None`") was verified only for a task's very *first* attempt. On a
*retry* attempt, an already-structurally-valid raw response gets exported
(`_export_output`) **before** the guardrail evaluates it — so `.pydantic`
can already hold the LLM's own (still semantically wrong) parsed object at
guardrail-call time on attempt 2+.

**Production rule (binding, applies to every Harbor & Vale guardrail/
callback, not only Crew 1):** never read `task.output.pydantic` in a
callback to get "the validated result" — it is unreliable in both
directions (unset after a real success; possibly set to unvalidated content
before one). Store the validated object explicitly instead — Crew 1 stores
it on the run-scoped `Crew1RunContext` (`crews/analyst_crew/runtime.py`)
from inside the guardrail itself, and every callback reads it from there.
This does not change what a guardrail should *return* to CrewAI (still
`(True, data)` / `(False, msg)`, `data` any non-`None` value — CrewAI's own
retry/exhaustion bookkeeping only cares about `success`); it changes where
*this project's own code* gets the validated object from.

### Finding 2 — forcing a narrative-agent's guardrail to accept, without
### raising, on final exhaustion

PROJECT_PLAN.md §D.2 point 9 requires Agent 2's invalid output, after
`guardrail_max_retries` retries, to produce a **visible degraded fallback**
— never halt Crew 1, and Agent 3 must still run. Left alone, CrewAI's own
guardrail-exhaustion behaviour (§5 above) raises a plain `Exception` out of
`crew.kickoff()` on the final failed attempt, which halts the **entire**
crew — Task 3 would never run, directly violating §D.2 point 9.

**Empirically verified mechanism:** on the final allowed attempt, if the
output is still invalid, the guardrail returns `(True, output)` — the
**same** `TaskOutput` instance it was given as its own argument, completely
unchanged (not a copy, not a new string, not a reconstructed object).
Because this hits the `isinstance(guardrail_result.result, TaskOutput)`
branch, CrewAI accepts it **without** re-running `_export_output` — so this
is safe even when the LLM's final attempt is structurally broken (not just
semantically wrong), unlike returning `(True, output.raw)` (a string),
which WOULD re-trigger `output_pydantic` validation and could raise
`pydantic.ValidationError` on malformed JSON. Verified end-to-end: the crew
completes (no exception), the guardrail is invoked exactly
`guardrail_max_retries + 1` times, and the next `Task` in the sequence runs
normally afterward.

The forced-accept branch never lets the invalid content reach an artifact:
the guardrail sets an explicit `ctx.eda_degraded = True` +
`ctx.eda_degraded_reason` on the `Crew1RunContext` in the same call, and the
callback renders from those fields (and `ctx.insights_doc`, left `None`),
never from the accepted-but-ignored `TaskOutput`. This is the general
pattern for any future "critical vs. narrative" agent split in this
project: only a NARRATIVE agent's guardrail may use this forced-accept
mechanism; a CRITICAL agent's guardrail must always return `(False, msg)`
on invalid input, letting CrewAI's own exhaustion-exception fire, which the
caller (`run_analyst_crew`) catches and reports as
`status="halted_agent_failure"`.

### Finding 3 — a named `Literal` type alias breaks `@tool` argument-schema
### construction

A CrewAI `@tool`-decorated function argument typed with a **module-level
named** `Literal` alias (e.g. `Crew1ArtifactName = Literal["x"]`, then
`def f(name: Crew1ArtifactName)`) fails at the first actual tool-schema
build with `pydantic_core._pydantic_core.PydanticUndefinedAnnotation:
'Crew1ArtifactName' is not fully defined` — CrewAI's tool-arg schema
builder does not resolve a module-level type alias into the dynamically
constructed per-tool Pydantic model's namespace. **Two independent fixes
both work:** inlining the `Literal[...]` directly in the parameter
annotation instead of via a named alias; or removing
`from __future__ import annotations` from the tool module (stringized
annotations compound the same resolution gap). Crew 1's actual design
avoided the whole class of Literal-arg tool-schema risk by preferring a
zero-argument, run-bound tool (`read_insights_report`) over a
single-value-enum argument — simpler, and strictly more restrictive per
§G.0's "no unconstrained arbitrary path input" principle. Documented here
because a future CrewAI tool with a genuinely multi-valued `Literal`
argument (e.g. Phase 7's handoff-name tool) will need one of the two fixes
above, not the "just use zero arguments" escape hatch Crew 1 took.

---

## Spike status

The Phase 1 spike files `spike/task_1_1_output_pydantic.py` …
`spike/task_1_6_flow_router.py` are **disposable technical evidence**. Each carries
a `DISPOSABLE SPIKE` header. `PROJECT_PLAN.md` §T Phase 1 accepts "deleted **or**
explicitly marked as deletable"; they are **kept** as reproducible proof for the
findings above and may be deleted once this document is considered sufficient.
They contain no Harbor & Vale business logic, no dataset, and no production
`Agent` / `Task` / `Crew` / `Flow` definitions.
