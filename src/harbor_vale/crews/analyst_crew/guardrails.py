"""Crew 1's `Task.guardrail` functions (PROJECT_PLAN.md §D.1/§D.2/§D.3 point 7,
Phase 6 Internal Gates 6.1-6.4).

Each function below wraps one already-tested Phase 5 `plans/*.validate_*`
function, supplying the real run context it needs (§14's "one-argument
closure per `Task` instance" pattern — realized here via
`runtime.get_active_context()` rather than a literal closure, so every
guardrail stays a plain, inspectable module-level function; see
`runtime.py`'s docstring for why).

**Deliberate omission: no `from __future__ import annotations`.** The same
proven CrewAI 1.15.20 PEP 563 hazard as every other guardrail module in this
project (docs/architecture.md §5, §14.10) — a stringized `-> Tuple[bool,
Any]` breaks `Task(guardrail=fn)` construction.

**The narrative-fallback mechanism (Agent 2 only).** PROJECT_PLAN.md §D.2
point 9 requires a VISIBLE degraded fallback, not a pipeline halt, when the
`InsightsDoc` guardrail is still invalid after `GUARDRAIL_MAX_RETRIES`
retries — and Agent 3 must still run afterward. Left to CrewAI's own
guardrail-exhaustion behaviour, that would instead raise a plain `Exception`
out of `crew.kickoff()` (docs/architecture.md §5, §12), halting Crew 1
*before* Agent 3 ever runs — exactly what §D.2 point 9 forbids. Empirically
verified (Phase 6, against the real pinned `crewai==1.15.20`, via a scripted
`BaseLLM` — no network) as the mechanism that avoids this: on the FINAL
allowed attempt, if the output is still invalid, `guardrail_insights_doc`
returns `(True, output)` — the SAME `TaskOutput` instance it was given,
completely unchanged. CrewAI's own `elif isinstance(guardrail_result.result,
TaskOutput): task_output = guardrail_result.result` branch accepts it
*without* re-running `output_pydantic` validation against `.raw` (unlike the
`str`-result branch, which DOES re-validate and would raise
`pydantic.ValidationError` on genuinely malformed JSON) — so this is safe
even when the LLM's final attempt is structurally broken, not just
semantically wrong. The invalid narrative content itself never reaches an
artifact: the callback (`callbacks.render_eda_and_insights`) renders from
`ctx.insights_doc`/`ctx.eda_degraded`, which this guardrail sets explicitly
— never from `task.output.pydantic` (see `runtime.py`'s docstring for why
that field cannot be trusted as a validity signal here either way).
"""

from typing import Any, Tuple

from harbor_vale.crews.analyst_crew.runtime import get_active_context
from harbor_vale.plans.cleaning_plan import validate_cleaning_plan
from harbor_vale.plans.contract_draft import validate_contract_draft
from harbor_vale.plans.insights_doc import validate_insights_doc

# Single source of truth for the retry budget every Crew 1 Task is wired
# with (PROJECT_PLAN.md §D.1/§D.2/§D.3 point 7: "guardrail_max_retries=2").
# `analyst_crew.py` imports this constant for `Task(guardrail_max_retries=...)`
# so the Task wiring and this module's own attempt-counting can never drift
# apart into two different retry budgets.
GUARDRAIL_MAX_RETRIES = 2
_INSIGHTS_MAX_ATTEMPTS = GUARDRAIL_MAX_RETRIES + 1  # total invocations CrewAI allows (docs/architecture.md §5)


def guardrail_cleaning_plan(output) -> Tuple[bool, Any]:
    """Task 1 (Inspector) guardrail — CRITICAL, no fallback (§D.1 point 9).

    On every rejected attempt, the rejected raw output is cached on the
    active context so `run_analyst_crew` can persist it to
    `_internal/rejected_cleaning_plan.json` if this Task ultimately exhausts
    its retries and the crew halts.
    """
    ctx = get_active_context()
    ok, result = validate_cleaning_plan(output, profile=ctx.raw_profile)
    if ok:
        ctx.cleaning_plan = result
        return True, result
    ctx.last_rejected_cleaning_plan_raw = getattr(output, "raw", str(output))
    return False, result


def guardrail_insights_doc(output) -> Tuple[bool, Any]:
    """Task 2 (EDA & Insights Analyst) guardrail — NARRATIVE, visible
    fallback on exhaustion (§D.2 point 9). See the module docstring for the
    forced-accept mechanism's proof of safety.
    """
    ctx = get_active_context()
    ctx.insights_guardrail_attempts += 1

    if ctx.eda_stats is None:
        return False, (
            "guardrail_insights_doc: eda_stats not available on the active context — "
            "this is a caller wiring error (Task 1's callback must run first), not a doc defect"
        )

    ok, result = validate_insights_doc(output, eda_stats=ctx.eda_stats)
    if ok:
        ctx.insights_doc = result
        ctx.eda_degraded = False
        ctx.eda_degraded_reason = None
        return True, result

    if ctx.insights_guardrail_attempts >= _INSIGHTS_MAX_ATTEMPTS:
        # Final allowed attempt, still invalid: force-accept via the SAME
        # TaskOutput, unchanged, so CrewAI does not raise and Task 3 still
        # runs. The invalid content is never used — only the degraded flag/
        # reason recorded here reaches the callback.
        ctx.eda_degraded = True
        ctx.eda_degraded_reason = str(result)
        ctx.insights_doc = None
        return True, output

    return False, result


def guardrail_contract_draft(output) -> Tuple[bool, Any]:
    """Task 3 (Data Contract Architect) guardrail — CRITICAL, no fallback
    (§D.3 point 9). Extends the Phase 5 `validate_contract_draft` with the
    real clean-data column-coverage check (§D.3 point 7) via the
    `clean_columns` context parameter it already supports.
    """
    ctx = get_active_context()
    ok, result = validate_contract_draft(output, clean_columns=ctx.clean_columns)
    if ok:
        ctx.contract_draft = result
        return True, result
    ctx.last_rejected_contract_draft_raw = getattr(output, "raw", str(output))
    return False, result
