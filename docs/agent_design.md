# Agent Design — Crew 1 (Phase 6) and Crew 2 (Phase 7)

Documents each Crew's agents against the exact 9-point structure
PROJECT_PLAN.md §D.1-D.3 / §G.1-G.3 defines, plus the cross-cutting design
questions Phase 6/7's Internal Gates ask for.

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

---

# Crew 2 — Agent Design (Phase 7)

## Why exactly three agents

Same principle as Crew 1 (§ above): three different KINDS of judgement, not
three pipeline stages. *What should the model actually be trained on, and
how* (Feature Engineer) · *what experiment design is defensible for this
business problem* (Modeling Specialist) · *what does this model's own
measured behavior, plus the contract's own declared assumptions, honestly
imply for anyone using it* (Responsible AI Documenter). Training itself,
metric computation, and winner selection are NOT agent judgement calls —
they are entirely deterministic (`ml/train.py`, `ml/evaluate.py`), so they
stay outside any Agent, exactly as Crew 1 keeps cleaning EXECUTION and
contract-building outside its Agents.

## The two-file handoff boundary (§G.0)

Crew 2's entire view of Crew 1 is exactly two logical names —
`"clean_data"` and `"dataset_contract"` — reachable only through
`read_handoff(name: Literal["clean_data", "dataset_contract"])`. The
`Literal` is INLINED directly in the tool function's parameter annotation,
never via a module-level named alias — `docs/architecture.md`'s Finding 3
(Phase 6 addendum) proved a named alias breaks CrewAI's dynamic per-tool
Pydantic schema construction with `PydanticUndefinedAnnotation`; inlining is
one of the two documented fixes, and Phase 7 needed the genuinely
multi-valued `Literal` case Crew 1 avoided by using zero-argument tools
instead. `access/allowlist.ExactFileAllowlist` (Phase 5, unmodified) is the
defense-in-depth Layer 2 underneath: even a resolved-path bypass attempt is
denied. Both layers are proven at the actual `@tool`-wrapped function level
in `tests/integration/test_crew2_tool_surface.py` — signature inspection
plus real denied/allowed calls through a live `Crew2RunContext` — not
merely at the underlying `ExactFileAllowlist` class Phase 5 already tested.

**Every Crew 1 field `Crew2RunContext` ever caches (`contract`, `clean_df`)
is loaded exclusively through `ctx.handoff.read_handoff(...)`** — including
from guardrails, which are trusted Python, not an agent. This keeps exactly
one audited channel to Crew 1 data instead of a "trusted code can read the
real path directly" shortcut that would otherwise exist right next to the
allowlisted one.

## `Crew2RunContext` (§ Internal Gate 7.2)

Same rationale and same concurrency guarantee as Crew 1's `Crew1RunContext`
(see above) — one run at a time, plain module-level tool/guardrail/callback
functions (`Task.callback`'s `SerializableCallable` typing forbids
closures), reached via `runtime.get_active_context()`.
`GUARDRAIL_MAX_RETRIES = 2` is Crew 2's own single source of truth
(`guardrails.py`), matching Crew 1's constant but deliberately not shared
with it — the two crews' retry budgets are independently declared, even
though they currently hold the same value.

## Critical vs. narrative failure

Agent 4 (Feature Engineer) and Agent 5 (Modeling Specialist) are
**critical**: an invalid `FeaturePlan`/`ExperimentPlan` after
`guardrail_max_retries` (2) retries halts Crew 2 with
`status="halted_agent_failure"` and produces **no fallback** — a guessed
feature set or a guessed experiment design is exactly the kind of false
confidence this project exists to prevent. Agent 6 (Responsible AI
Documenter) is **narrative**: on exhaustion it force-accepts (the same
mechanism `guardrail_insights_doc` proved safe in Phase 6) and Crew 2
still finishes, rendering a deterministic, truthful fallback
`model_card.md` with a visible degradation banner instead of a
narrative-only halt.

## Agent Plans, Python Executes

No Crew 2 agent fits a preprocessor, trains a model, computes a metric, or
selects a winner. Every agent produces a validated, structured plan
(`FeaturePlan` / `ExperimentPlan` / `ModelCard`); `callbacks.py`'s three
functions are the only code that ever touches `clean_df`, fits a
`sklearn.Pipeline`, or writes an artifact.

---

## G.1 — Agent 4: Feature Engineer 🔴 CRITICAL

1. **Why an Agent, not deterministic Python?** Which columns to use, which
   transform/encoding each one needs, and — critically — whether an
   `advisory`-excluded column is legitimately usable for THIS dataset are
   judgement calls that need to read and interpret the contract's
   semantics, not just its shape.
2. **Reasoning performed.** Reads the contract's `required_features` /
   `excluded_features` / `columns`; reads the real measured profile via
   `profile_handoff_data`; decides `use_features`, `transforms` (e.g.
   `log1p` on right-skewed monetary columns), `encoders` (one per
   categorical feature used), and any `advisory_overrides` with a concrete,
   dataset-specific justification.
3. **Tools.** `read_handoff` (`"clean_data"` or `"dataset_contract"`),
   `profile_handoff_data` — both allowlisted, zero free path parameter.
4. **Context.** `context=[]` (first task) plus the tool-exposed contract
   and profile.
5. **Forbidden.** Touching raw data; writing `features.csv`; using a
   `hard`-excluded feature; fitting any preprocessing itself; computing
   statistics from the eventual test set (it does not exist yet at this
   point in the pipeline).
6. **Structured output.** `FeaturePlan` (`plans/feature_plan.py`, Phase 5,
   reused verbatim) — `contract_acknowledgment` (§F.0 layer 2, non-blocking
   acknowledgment), `use_features`, `derived`, `transforms`, `encoders`,
   `dropped`, `advisory_overrides`.
7. **Validation / guardrail.** `guardrails.guardrail_feature_plan` wraps
   `validate_feature_plan`, cross-checked against the ACTUAL current
   `DatasetContract` loaded via the allowlist (never a memorized/assumed
   naming convention — the Session 26 grounding lesson, generalized to
   Crew 2 in `config/tasks.yaml`'s explicit STEP 1/2/3 process). Mechanical
   rejections: target as feature, unknown column, missing required
   feature, `hard`-excluded feature, `advisory`-excluded feature without a
   matching override, override referencing a non-advisory column,
   contract-version mismatch. `guardrail_max_retries=2`.
8. **Consumer / callback.** `callbacks.persist_feature_plan_and_build_features`:
   persists the plan to `_internal/feature_plan.json`, calls the already-
   tested `tools/feature_tools.build_features` (unfitted `ColumnTransformer`
   — nothing is fit on the full dataset here), writes `features.csv`.
9. **Failure policy.** 🔴 CRITICAL. 2 exhausted retries → Crew 2 halts,
   rejected raw output persisted to `_internal/rejected_feature_plan.json`,
   Tasks 2/3 never run, no `features.csv`.

---

## G.2 — Agent 5: Modeling & Experimentation Specialist 🔴 CRITICAL

1. **Why an Agent, not deterministic Python?** Choosing a business-
   appropriate primary metric under class imbalance, and picking which
   model families are worth comparing and why, is a judgement call with
   business context (missing a genuine churner costs more than a false
   alarm) — not a fixed rule.
2. **Reasoning performed.** Reads the target's measured `positive_rate` and
   Crew 2's own approved `FeaturePlan`; proposes `primary_metric` +
   `metric_rationale`, `cv_folds`, and ≥2 variants from the frozen
   estimator set, each with a plain, defensible hyperparameter choice and a
   one-sentence rationale.
3. **Tools.** `read_handoff("dataset_contract")`, `read_feature_plan()`
   (Crew 2's own already-written artifact). **Deliberately does NOT** carry
   `read_experiment_results` — that tool exists in `tools.py` (interface
   parity with §G.2 point 3's full table) but is wired only onto Agent 6,
   because it can only ever return real content AFTER Task 2's callback
   trains — during Task 2 itself, calling it would only ever raise. Wiring
   it here would invite a call that cannot succeed; PROJECT_PLAN.md's own
   "3 Agents / 3 Tasks, no post-training narrative Task" constraint is
   respected by giving the "after training" tool only to the "after
   training" agent (Agent 6), not by adding a 4th task.
4. **Context.** `context=[feature_task]` plus the tool-exposed contract and
   FeaturePlan.
5. **Forbidden.** Training a model itself; inventing a metric; choosing the
   winner; seeing the test set before training completes; any estimator
   outside `logistic_regression`/`random_forest`/`gradient_boosting`;
   hyperparameter search/tuning; setting `random_state` itself.
6. **Structured output.** `ExperimentPlan` (`plans/experiment_plan.py`,
   Phase 5) — `primary_metric`, `metric_rationale`, `cv_folds`, `variants[]`.
7. **Validation / guardrail.** `guardrails.guardrail_experiment_plan` wraps
   `validate_experiment_plan`: estimator from the closed `Literal`,
   per-estimator params allowlist, ≥2 variants, unique names,
   `task_type` compatibility (bound to the real contract's
   `target.task_type`). `guardrail_max_retries=2`.
8. **Consumer / callback.** `callbacks.train_and_evaluate`: runs the exact
   approved protocol (`train_test_split(test_size=0.2, stratify=y,
   random_state=42)`, `StratifiedKFold(5, shuffle=True, random_state=42)`,
   preprocessing INSIDE the `Pipeline`, test set touched exactly once);
   Python selects the winner by `argmax(primary_metric)` over CV metrics
   (deterministic tie-break — earliest-declared variant on an exact tie);
   writes `experiments.json`, `model.joblib`, and renders
   `evaluation_report.md` from `experiments.json` + the plan's own
   narrative rationale — never from an unverified number.
9. **Failure policy.** 🔴 CRITICAL. 2 exhausted retries → Crew 2 halts,
   rejected raw output persisted to `_internal/rejected_experiment_plan.json`,
   `features.csv` remains (Task 1 already succeeded) but no
   `model.joblib`/`experiments.json`/`evaluation_report.md`/`model_card.md`.

---

## G.3 — Agent 6: Responsible AI Documenter 🟡 NARRATIVE

1. **Why an Agent, not deterministic Python?** Translating the contract's
   own declared `assumptions` into an operational limitation (e.g. an
   undocumented currency implies the model assumes measurement scale stays
   constant, and an upstream unit change — the original Harbor & Vale
   incident — would silently invalidate its predictions) is exactly the
   kind of judgement-plus-honesty task an LLM adds value on; a template
   cannot know which of the contract's assumptions actually matters for
   THIS model.
2. **Reasoning performed.** Reads the contract's `assumptions`, Crew 2's
   own `FeaturePlan` and real `experiments.json`; writes purpose, intended
   use, limitations, ethical considerations, and monitoring
   recommendations grounded in what was actually measured and actually
   assumed.
3. **Tools.** `read_handoff("dataset_contract")`, `read_feature_plan()`,
   `read_experiment_results()` — all Crew 2's own artifacts + the
   allowlisted contract; never `insights.md`, `eda_report.html`, or any
   Crew 1 `_internal` file.
4. **Context.** `context=[feature_task, modeling_task]` plus the
   tool-exposed contract, FeaturePlan, and real experiment results.
5. **Forbidden.** Inventing a metric; claiming a fairness/bias metric was
   measured when none was; rewriting `evaluation_report.md`.
6. **Structured output.** `ModelCard` (`plans/model_card.py`, Phase 5) —
   `purpose`, `intended_use`, `out_of_scope_use`, `training_data_summary`,
   `metrics_summary` (typed `MetricClaim`s), `limitations`,
   `ethical_considerations`, `contract_dependencies`,
   `monitoring_recommendations`.
7. **Validation / guardrail.** `guardrails.guardrail_model_card` wraps
   `validate_model_card`: every `MetricClaim` mechanically verified against
   the real `experiments.json` (metric/split/variant/value must all match
   exactly — `MetricName` is a closed `Literal` with no `"fairness"` value
   constructible at all); `contract_dependencies` must include at least one
   string that is an EXACT match of a real `contract.assumptions` entry.
   `guardrail_max_retries=2`.
8. **Consumer / callback.** `callbacks.render_model_card` →
   `tools/report_tools.render_model_card_markdown`: normal mode renders
   ONLY the validated `ModelCard`'s fields; degraded mode ignores the
   invalid LLM content entirely and builds its own minimal, truthful
   fallback directly from `experiments.json`'s winner metrics and the
   contract's real `assumptions` — with the required visible banner.
9. **Failure policy.** 🟡 NARRATIVE — visible fallback, not a halt. Same
   forced-accept mechanism as Crew 1's `guardrail_insights_doc` (proven
   safe against real `crewai==1.15.20`): on the final allowed attempt, if
   still invalid, the guardrail returns `(True, output)` unchanged so
   CrewAI does not raise; `ctx.model_card_degraded=True` is set explicitly,
   and the callback renders from that flag, never from the unvalidated
   content. Crew 2 still produces all four required artifacts.

## Live acceptance run — one code-level learning iteration (not prompt-only)

Recorded in full in `working flow/2026-09-15_session-27.md`. In short: Run 1
(the real, Session-26 Crew 1 handoff) halted inside Task 2's deterministic
training callback — not an agent/guardrail defect — because the real
`clean_data.csv` still carries 11 measured nulls in `TotalCharges`, and
`ml/features.build_preprocessor` had no NaN-handling case (`StandardScaler`
silently passes a NaN through by sklearn design; no estimator accepts one).
This was a genuine, previously-unexercised Phase 5 gap, not a prompt-quality
issue, so the fix was code (`SimpleImputer` inside the existing leakage-safe
`Pipeline`, `src/harbor_vale/ml/features.py`), not a role/goal/backstory
change — PROJECT_PLAN.md's "change deterministic architecture only when a
real contradiction is found, and report it" applied here, not the prompt-
iteration guidance. Run 2, with the fix applied, completed fully on the
first attempt for all three agents (0 guardrail retries) with high-quality
output: exact real contract column spellings throughout the `FeaturePlan`,
correct hard-exclusion of `customerID`, two frozen-set model variants with
defensible rationale, and a `ModelCard` whose limitations explicitly name
the scale-change risk this entire project is about. No prompt change was
made or would have been defensible given Run 2's quality — no third run was
justified, and none was run (2/2 live runs used).
