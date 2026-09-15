"""Crew 2's `Task.guardrail` functions (PROJECT_PLAN.md §G.1/§G.2/§G.3 point 7,
Phase 7 Internal Gates 7.3-7.5).

Each function wraps an already-tested Phase 5 `plans/*.validate_*` function,
supplying the real run's `Crew2RunContext` state it needs — same "closure
via `get_active_context()`" pattern as `crews.analyst_crew.guardrails`, for
the identical `SerializableCallable` reason documented there.

**Deliberate omission: no `from __future__ import annotations`** — the same
proven CrewAI 1.15.20 PEP 563 hazard as every other guardrail module in this
project.

**Critical vs. narrative, exactly as §G.1/§G.2/§G.3 point 9 specify:**
Agent 4 (Feature Engineer) and Agent 5 (Modeling Specialist) are CRITICAL —
their guardrails always return `(False, msg)` on invalid input, letting
CrewAI's own guardrail-exhaustion exception fire and halt Crew 2. Agent 6
(Responsible AI Documenter) is NARRATIVE — its guardrail uses the identical
forced-accept mechanism `crews.analyst_crew.guardrails.guardrail_insights_doc`
already proved safe against real `crewai==1.15.20` (docs/architecture.md's
Phase 6 addendum, Finding 2): on the FINAL allowed attempt, if the output is
still invalid, return `(True, output)` — the SAME `TaskOutput`, unchanged —
so CrewAI accepts it without re-validating `.raw` and Crew 2 finishes. The
invalid content itself never reaches an artifact: `callbacks.render_model_card`
renders from `ctx.model_card`/`ctx.model_card_degraded`, never from
`task.output.pydantic`.
"""

from typing import Any, Tuple

from harbor_vale.crews.scientist_crew.runtime import get_active_context
from harbor_vale.crews.scientist_crew.tools import ensure_contract_loaded
from harbor_vale.plans.experiment_plan import validate_experiment_plan
from harbor_vale.plans.feature_plan import validate_feature_plan
from harbor_vale.plans.model_card import validate_model_card

# Single source of truth for the retry budget every Crew 2 Task is wired
# with (PROJECT_PLAN.md Internal Gate 7.2: "GUARDRAIL_MAX_RETRIES = 2 for
# Crew 2"). `scientist_crew.py` imports this constant for
# `Task(guardrail_max_retries=...)` so the Task wiring and this module's own
# attempt-counting can never drift apart into two different retry budgets.
GUARDRAIL_MAX_RETRIES = 2
_MODEL_CARD_MAX_ATTEMPTS = GUARDRAIL_MAX_RETRIES + 1  # total invocations CrewAI allows


def guardrail_feature_plan(output) -> Tuple[bool, Any]:
    """Task 1 (Feature Engineer) guardrail — CRITICAL, no fallback
    (§G.1 point 9). Cross-validates the parsed `FeaturePlan` against the
    ACTUAL current `DatasetContract`, loaded via the allowlisted handoff
    (never re-derived from memory/examples — the Session 26 grounding
    lesson applies to Crew 2 exactly as it did to Crew 1's Contract
    Architect)."""
    ctx = get_active_context()
    contract = ensure_contract_loaded(ctx)
    ok, result = validate_feature_plan(output, contract=contract)
    if ok:
        ctx.feature_plan = result
        return True, result
    ctx.last_rejected_feature_plan_raw = getattr(output, "raw", str(output))
    return False, result


def guardrail_experiment_plan(output) -> Tuple[bool, Any]:
    """Task 2 (Modeling & Experimentation Specialist) guardrail — CRITICAL,
    no fallback (§G.2 point 9)."""
    ctx = get_active_context()
    contract = ensure_contract_loaded(ctx)
    ok, result = validate_experiment_plan(output, task_type=contract.target.task_type)
    if ok:
        ctx.experiment_plan = result
        return True, result
    ctx.last_rejected_experiment_plan_raw = getattr(output, "raw", str(output))
    return False, result


def guardrail_model_card(output) -> Tuple[bool, Any]:
    """Task 3 (Responsible AI Documenter) guardrail — NARRATIVE, visible
    fallback on exhaustion (§G.3 point 9). See the module docstring for the
    forced-accept mechanism's proof of safety."""
    ctx = get_active_context()
    ctx.model_card_guardrail_attempts += 1

    if ctx.experiments_artifact is None:
        return False, (
            "guardrail_model_card: experiments_artifact not available on the active context — "
            "this is a caller wiring error (Task 2's callback must run first), not a card defect"
        )

    contract = ensure_contract_loaded(ctx)
    ok, result = validate_model_card(output, experiments=ctx.experiments_artifact, contract=contract)
    if ok:
        ctx.model_card = result
        ctx.model_card_degraded = False
        ctx.model_card_degraded_reason = None
        return True, result

    if ctx.model_card_guardrail_attempts >= _MODEL_CARD_MAX_ATTEMPTS:
        # Final allowed attempt, still invalid: force-accept via the SAME
        # TaskOutput, unchanged, so CrewAI does not raise and Crew 2 still
        # finishes. The invalid content is never used — only the degraded
        # flag/reason recorded here reaches the callback.
        ctx.model_card_degraded = True
        ctx.model_card_degraded_reason = str(result)
        ctx.model_card = None
        return True, output

    return False, result
