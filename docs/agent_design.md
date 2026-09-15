# Crew 1 — Agent Design (Phase 6)

Documents each of Crew 1's three agents against the exact 9-point structure
PROJECT_PLAN.md §D.1-D.3 defines, plus the cross-cutting design questions
Phase 6's Internal Gate 6.6 asks for. **Crew 2 (Phase 7) is not documented
here** — it does not exist yet.

---

## Why exactly three agents

Three different KINDS of judgement, not three arbitrary pipeline stages
(PROJECT_PLAN.md §D's own framing): *what is broken in the data and what to
do about it* (Inspector), *what the data means for the business*
(Analyst), and *what a completely separate team is allowed to assume about
this data without ever seeing it* (Architect). A further split would create
an agent with no real decision of its own to make — a violation of "Agent
Plans, Python Executes": if a step has no judgement call, it belongs in
`tools/*.py`, not in a fourth `Agent`.

## Pattern A

One `Crew`, three `Agent`s, three `Task`s, `Process.sequential` — the
pattern the Phase 1 spike proved and `docs/architecture.md` records.
`Task N`'s `callback` runs synchronously and fully finishes (verified
against the real pinned `crewai==1.15.20`) before `Task N+1`'s agent starts,
so `Agent → deterministic Python → Agent` happens inside one `crew.kickoff()`
call, never across two.

## Critical vs. narrative failure

Two of Crew 1's three agents are **critical**: if their output is still
invalid after `guardrail_max_retries` (2) retries, Crew 1 halts with
`status="halted_agent_failure"` and produces **no fallback** — a
guessed cleaning plan or a guessed contract is more dangerous than no
pipeline at all, because it manufactures false confidence (exactly the
Harbor & Vale incident). One agent — the EDA & Insights Analyst — is
**narrative**: a failed interpretation degrades the report visibly instead
of halting the whole crew, because the business insight is useful-but-not-
load-bearing, while the contract genuinely is.

## Agent Plans, Python Executes

No agent in Crew 1 mutates a DataFrame, writes a production artifact
directly, computes an authoritative statistic, or decides PASS/FAIL of
anything. Every agent produces a validated, structured plan
(`CleaningPlan` / `InsightsDoc` / `ContractDraft`); a deterministic Python
`callback` is the only thing that ever touches disk or measures a real
number (`callbacks.py`, all three functions).

## What `context=` is and is not

`context=[task]` (docs/architecture.md §8) hands the downstream agent the
upstream task's **raw prompt text**, verbatim — never a typed object, never
a validated artifact. Crew 1 sets `context=` explicitly on every `Task`
(never the default, which silently injects every prior task) and never
relies on it to carry the actual contract — the real handoff is the
callback-written artifact on disk (`clean_data.csv`, `insights.md`), read
back through a scoped, run-bound tool (`tools.py`), plus the explicit,
non-CrewAI `Crew1RunContext` (`runtime.py`) every guardrail/callback reads
directly.

## Retry policy

Every Crew 1 `Task` is wired with `guardrail_max_retries=2` (never the
deprecated `max_retries`) — `GUARDRAIL_MAX_RETRIES` in `guardrails.py` is
the single source of truth both the `Task` construction and the narrative-
fallback attempt-counting logic read, so the two can never drift apart.

---

## D.1 — Agent 1: Data Quality Inspector 🔴 CRITICAL

1. **Why an Agent, not deterministic Python?** Whether to drop, impute, or
   leave a value as legitimately-informative missing is a judgement call a
   fixed rule gets wrong in general — e.g. an empty `TotalCharges` for a
   brand-new customer means "not yet billed," not "unknown"; filling it
   with a column mean would misrepresent that customer, filling it with 0
   is correct. A hard-coded rule cannot make that call for every column
   Data Quality Inspector will ever see.
2. **Reasoning performed.** Reads the raw dataset's deterministic profile
   (per-column dtype, null/blank-string counts, min/max/mean/median, top
   values) and preview rows; classifies each real, observed issue and
   decides a specific typed operation with a stated reason.
3. **Tools.** `profile_dataset` (zero-argument, run-bound — returns the
   active run's raw `DatasetProfile`), `preview_sample` (bounded `n<=50`,
   run-bound). Both thin wrappers around already-tested
   `tools/profiling_tools.py` functions; neither takes a filesystem path.
4. **Context.** The raw dataset's measured profile (via the tool above) —
   no upstream task context (`context=[]`; this is the first task).
5. **Forbidden.** Writing any file; mutating the DataFrame; executing the
   cleaning itself; inventing a column; declaring a UNIT for any column
   (that is Agent 3's job); inventing a statistic.
6. **Structured output.** `CleaningPlan` (`plans/cleaning_plan.py`,
   reused verbatim from Phase 5) — a closed 7-operation vocabulary
   (`drop_duplicates`, `impute`, `cast`, `rename`, `drop_column`, `clip`,
   `standardize_category`), each operation carrying a required `reason`.
7. **Validation / guardrail.** `guardrails.guardrail_cleaning_plan` wraps
   the Phase 5 `validate_cleaning_plan`, supplying the real run's raw
   `DatasetProfile` via `runtime.get_active_context()`. Structural failure
   (bad JSON/schema) and semantic failure (e.g. `impute` on a column with
   zero measured nulls, or a reference to a column that does not exist)
   both return `(False, message)` — CrewAI retries with that message fed
   into the next prompt. `guardrail_max_retries=2`.
8. **Consumer / callback.** `callbacks.execute_cleaning_and_profile`:
   persists the accepted plan under `artifacts/crew1/_internal/cleaning_plan.json`,
   executes it via the already-tested `tools/cleaning_tools.execute_plan`,
   writes `clean_data.csv`, builds the clean-data profile, and computes the
   deterministic EDA statistics/figures Task 2 needs — all before Task 2's
   agent starts (proven callback-ordering guarantee).
9. **Failure policy.** 🔴 CRITICAL. After 2 exhausted retries, CrewAI's own
   guardrail machinery raises a plain `Exception`; `run_analyst_crew` catches
   it, sets `status="halted_agent_failure"`, persists the last rejected raw
   output to `artifacts/crew1/_internal/rejected_cleaning_plan.json` (when
   available), and Crew 1 stops — Tasks 2 and 3 never run. **No fallback.**

---

## D.2 — Agent 2: EDA & Insights Analyst 🟡 NARRATIVE

1. **Why an Agent, not deterministic Python?** The gap between "month-to-
   month customers churn at roughly 4× the rate of two-year customers" (a
   measured fact) and "contract length is the strongest retention lever we
   have observed, so incentives should target month-to-month customers
   before pursuing anything more expensive" (a business recommendation)
   requires framing a number as an implication and an action — genuinely an
   LLM task, not a statistic Python can derive.
2. **Reasoning performed.** Reads the deterministic EDA statistics
   (computed by Agent 1's callback) and produces 5-7 insights, each
   distinguishing observation → business implication → recommended action,
   grounded in a real, citable measured statistic.
3. **Tools.** `get_eda_statistics`, `get_numeric_correlations`,
   `list_eda_figures` — all zero-argument, run-bound, reading the SAME
   cached computation the guardrail validates against (one source of
   truth, never a second, possibly-divergent recomputation).
4. **Context.** `context=[inspect_task]` (Task 1's raw output, narrative
   continuity only) plus the tool-exposed measured statistics/figures.
5. **Forbidden.** Producing its own numbers; drawing figures; writing raw
   HTML.
6. **Structured output.** `InsightsDoc` (`plans/insights_doc.py`, Phase 5):
   `headline`, `insights[]` (title/observation/business_implication/
   recommended_action/evidence_stat_key), `data_caveats[]`.
7. **Validation / guardrail.** `guardrails.guardrail_insights_doc` wraps
   the Phase 5 `validate_insights_doc`, supplying the real `eda_stats`
   dict. Every `evidence_stat_key` MUST be a real key in that dict — an
   invented key is rejected outright (the anti-hallucination mechanism).
   `guardrail_max_retries=2`.
8. **Consumer / callback.** `callbacks.render_eda_and_insights` renders
   `eda_report.html` and `insights.md` via the already-tested Phase 5
   Jinja2 renderers — from `ctx.insights_doc`/`ctx.eda_degraded`, never
   from CrewAI's own `task.output.pydantic` (see the Phase 6 addendum in
   `docs/architecture.md` for why that field cannot be trusted as a
   validity signal here).
9. **Failure policy.** 🟡 NARRATIVE — **visible fallback, not a halt.** On
   the final (3rd) guardrail evaluation, if the output is still invalid,
   `guardrail_insights_doc` force-accepts (returns `(True, output)` — the
   SAME `TaskOutput`, unchanged) instead of letting CrewAI raise, and sets
   `ctx.eda_degraded=True` with the rejection reason. The callback renders
   both artifacts with the exact visible banner: *"⚠️ Narrative unavailable
   — the analyst agent's output failed schema validation after 2
   retries."* The invalid narrative content itself never reaches an
   artifact. **Task 3 still runs** — see the Phase 6 addendum in
   `docs/architecture.md` for the empirical proof this mechanism does not
   trigger CrewAI's own re-validation/crash path.

---

## D.3 — Agent 3: Data Contract Architect 🔴 CRITICAL ⭐

1. **Why an Agent, not deterministic Python?** Python can measure that
   `monthly_charges` is a `float64` between 18 and 119; it cannot know that
   is money, and it certainly cannot know WHAT currency, because nothing in
   the source documentation says. Connecting a column's name, context, and
   distribution to its real-world meaning — and, more importantly, to what
   can be *honestly justified* as an enforceable constraint — is exactly
   where an LLM adds value code cannot. This is the single most important
   agent in the project: it writes the interface every downstream
   consumer trusts.
2. **Reasoning performed.** Per column: `semantic_type`; whether the unit
   is genuinely documented (`unit.evidence`) or honestly
   `unspecified`/`currency_unspecified`; whether a categorical domain is
   truly closed; whether a business range is defensible; whether an
   excluded feature is genuinely `target_leakage` (temporal/semantic
   reason required) vs. merely `redundancy_collinearity` (correlated but
   legitimately available at prediction time — the corrected `TotalCharges`
   classification, §E.4).
3. **Tools.** `profile_clean_dataset` (the post-cleaning profile),
   `read_insights_report` (Crew 1's own already-rendered `insights.md` —
   zero-argument, no path parameter at all), `read_source_documentation`
   (curated `data/README.md` §6-11 — the only legitimate evidence source
   for a unit/closed-domain/business-range claim). All run-bound,
   zero-argument or bounded, never an arbitrary path.
4. **Context.** `context=[inspect_task, eda_task]` (both prior tasks' raw
   output, narrative continuity) plus the tool-exposed clean profile,
   insights, and source documentation.
5. **Forbidden.** Writing `dataset_contract.json` itself; inventing
   min/max/median/row counts/hashes; declaring a unit without evidence;
   marking a feature `target_leakage` merely because it correlates with the
   target.
6. **Structured output.** `ContractDraft` (`plans/contract_draft.py`,
   Phase 3 — reused, not a second schema) — semantics and justifications
   only; structurally incapable of carrying a measured value
   (`extra="forbid"` throughout, no `min`/`max`/`sha256` field anywhere in
   the model).
7. **Validation / guardrail.** `guardrails.guardrail_contract_draft` wraps
   `validate_contract_draft`, extended this phase with an optional
   `clean_columns` parameter (Phase 6 addition, backward-compatible
   default `None`) that fails fast on a coverage mismatch against the
   REAL `clean_data.csv` columns — the guardrail-level echo of the
   identical check `contract/builder.build_contract` performs
   authoritatively at build time. Every other rule (`business_range`
   needs justification, `unit` needs evidence, `exclusion_type` must be a
   real enum member, target declared exactly once, full column coverage)
   is enforced by `ContractDraft`'s own Pydantic validators.
   `guardrail_max_retries=2`.
8. **Consumer / callback.** `callbacks.build_final_contract`: the agent
   NEVER writes the contract file. The callback calls
   `contract/builder.build_contract` with the validated `ContractDraft` and
   the real `clean_data.csv` — Python stamps every measured fact (dtypes,
   observed statistics, exact SHA256, row/column counts) and writes
   `dataset_contract.json`. This remains the only production
   contract-building path.
9. **Failure policy.** 🔴 CRITICAL. Same halt mechanism as Agent 1: after 2
   exhausted retries, Crew 1 halts with `status="halted_agent_failure"`,
   the rejected draft is persisted to
   `artifacts/crew1/_internal/rejected_contract_draft.json` when available,
   and **no contract is produced.** A guessed contract is more dangerous
   than no contract — it manufactures false confidence, which is the
   original Harbor & Vale failure mode.

---

## Prompt-design learning iteration

Recorded in `working flow/2026-09-15_session-23.md` (Phase 6's session
record), per PROJECT_PLAN.md §T Phase 6's explicit requirement — the run 1
→ run 2 comparison, what changed in `config/agents.yaml`/`config/tasks.yaml`
and why, and an honest account of what improved and what did not.
