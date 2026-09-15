"""Crew 2's per-run runtime/context object (PROJECT_PLAN.md §G.0, Internal
Gate 7.2 — "Reuse the successful Phase 6 runtime architecture ... prefer a
Crew-2-scoped runtime such as `Crew2RunContext`").

Same design rationale as `crews.analyst_crew.runtime.Crew1RunContext`
(`SerializableCallable` forbids closures/bound methods for `Task.callback`,
so every tool/guardrail/callback here is a plain module-level function that
reaches this run's state via :func:`get_active_context`). See that module's
docstring for the full explanation — not repeated here.

**The one Crew-2-specific rule:** every piece of Crew 1 data this context
ever holds (`contract`, `clean_df`, `clean_profile`) is loaded **through**
`ctx.handoff.read_handoff(name)` — the same two-name allowlisted channel an
agent's own tool calls go through — never by a trusted shortcut that reads
`artifacts/crew1/*` directly. `run_scientist_crew` is trusted orchestration
code and may run the Phase 4 gate before constructing this context (§F.0),
but once a `Crew2RunContext` exists, everything after that point — guardrails
included — reaches Crew 1 output only via the allowlist, so there is exactly
one channel to audit, not two.

**Concurrency:** exactly one crew at a time, same enforcement as Crew 1's
`crew1_run_context`.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    import pandas as pd
    from sklearn.compose import ColumnTransformer

    from harbor_vale.access.handoff import Crew2Handoff
    from harbor_vale.contract.schema import DatasetContract
    from harbor_vale.ml.train import TrainedVariant
    from harbor_vale.plans.experiment_plan import ExperimentPlan
    from harbor_vale.plans.feature_plan import FeaturePlan
    from harbor_vale.plans.model_card import ModelCard
    from harbor_vale.tools.profiling_tools import DatasetProfile


@dataclass
class Crew2RunContext:
    """Everything Crew 2's tools/guardrails/callbacks need for one run.

    Populated incrementally: most fields start `None`/empty and are filled
    in by Task 1 (Feature Engineer)'s callback, then Task 2 (Modeling &
    Experimentation Specialist)'s callback, then Task 3 (Responsible AI
    Documenter)'s guardrail/callback. Fields are plain, inspectable
    attributes so tests can assert on them directly.
    """

    run_id: str
    handoff: "Crew2Handoff"

    # --- Flow-injected metadata (§G.0 "סטטוס הוולידציה כמטא-דאטה") ---------
    # Never the validation_report.json itself — only these three scalars,
    # exactly what §G.0's kickoff-inputs example shows.
    handoff_status: str
    contract_version: str
    validation_warnings: int

    # --- output paths (workspace-relative; defaults to artifacts/crew2) ---
    features_csv: Path
    model_joblib: Path
    experiments_json: Path
    evaluation_report_md: Path
    model_card_md: Path
    internal_dir: Path

    # --- loaded lazily, always via ctx.handoff.read_handoff(...) ----------
    contract: "DatasetContract | None" = None
    clean_df: "pd.DataFrame | None" = None
    clean_profile: "DatasetProfile | None" = None

    # --- filled in by Task 1 (Feature Engineer) ----------------------------
    feature_plan: "FeaturePlan | None" = None
    feature_X: "pd.DataFrame | None" = None
    feature_y: "pd.Series | None" = None
    feature_preprocessor: "ColumnTransformer | None" = None
    feature_names: list[str] = field(default_factory=list)
    last_rejected_feature_plan_raw: str | None = None

    # --- filled in by Task 2 (Modeling & Experimentation Specialist) ------
    experiment_plan: "ExperimentPlan | None" = None
    trained_variants: "list[TrainedVariant] | None" = None
    cv_metrics: dict[str, dict[str, Any]] | None = None
    winner_name: str | None = None
    test_metrics: dict[str, Any] | None = None
    experiments_artifact: dict[str, Any] | None = None
    last_rejected_experiment_plan_raw: str | None = None

    # --- filled in by Task 3 (Responsible AI Documenter) -------------------
    model_card: "ModelCard | None" = None
    model_card_degraded: bool = False
    model_card_degraded_reason: str | None = None
    model_card_guardrail_attempts: int = 0

    # --- overall run status, set by run_scientist_crew() -------------------
    status: str = "running"
    failure_category: str | None = None
    failure_message: str | None = None


_active_context: Crew2RunContext | None = None


@contextmanager
def crew2_run_context(ctx: Crew2RunContext) -> Iterator[Crew2RunContext]:
    """Make *ctx* the active Crew 2 run context for the duration of the
    `with` block (i.e. for the one `crew.kickoff()` call it wraps).

    Raises `RuntimeError` if a context is already active — Crew 2 never
    supports concurrent/nested runs in this project.
    """
    global _active_context
    if _active_context is not None:
        raise RuntimeError(
            "a Crew2RunContext is already active — concurrent/nested Crew 2 "
            "runs are not supported; this is a caller wiring error"
        )
    _active_context = ctx
    try:
        yield ctx
    finally:
        _active_context = None


def get_active_context() -> Crew2RunContext:
    """Return the currently active `Crew2RunContext`.

    Raises `RuntimeError` (never returns `None`) if called outside a
    `with crew2_run_context(ctx):` block — every Crew 2 tool/guardrail/
    callback function calls this first thing, so an out-of-band call is a
    genuine wiring bug, not a data problem, and must fail loudly.
    """
    if _active_context is None:
        raise RuntimeError(
            "no active Crew2RunContext — this function was called outside "
            "`crew2_run_context(...)`; this is a caller wiring error"
        )
    return _active_context
