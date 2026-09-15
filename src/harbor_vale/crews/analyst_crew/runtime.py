"""Crew 1's per-run runtime/context object (PROJECT_PLAN.md §T Phase 6,
"Callback / Guardrail Implementation Discipline").

**Not `PipelineState` (Phase 8).** This is a small, Crew-1-local object that
exists only to give Crew 1's tools/guardrails/callbacks a single, explicit
place to read and write run-scoped state (paths, the raw/clean DataFrames,
measured profiles/statistics, the validated agent outputs, and the
narrative-degradation flag) — instead of module-level globals scattered
across files, or CrewAI's `context=[task]` (proven, docs/architecture.md §8,
to be RAW prompt text only, never a typed handoff channel).

**Why not closures?** `Task.callback` is typed `SerializableCallable`
(`crewai/types/callback.py`): a closure, bound method, or callable class
instance all fail `_is_non_roundtrippable` and emit
`UserWarning: ... callbacks cannot be serialized ...` — the exact hazard
docs/architecture.md §7 already flags ("Crew 1/2 callbacks must be
module-level named functions"). `Task.guardrail` does not carry that same
typed annotation (verified empirically — see docs/architecture.md's Phase 6
addendum), so guardrail closures remain fine, but this module keeps the
*same* access pattern for both, for one uniform, auditable design: every
tool/guardrail/callback function is a plain module-level function that
calls :func:`get_active_context` to reach the current run's state.

**Concurrency:** Crew 1 runs exactly one crew at a time (`Process.sequential`,
Pattern A, a single `kickoff()` call) — there is never a legitimate reason
for two `Crew1RunContext` instances to be active simultaneously in this
project. :func:`crew1_run_context` enforces that with a plain `RuntimeError`
rather than silently overwriting one run's state with another's.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    import pandas as pd

    from harbor_vale.contract.schema import DatasetContract
    from harbor_vale.plans.cleaning_plan import CleaningPlan
    from harbor_vale.plans.contract_draft import ContractDraft
    from harbor_vale.plans.insights_doc import InsightsDoc
    from harbor_vale.tools.profiling_tools import DatasetProfile


@dataclass
class Crew1RunContext:
    """Everything Crew 1's tools/guardrails/callbacks need for one run.

    Populated incrementally as the crew progresses — most fields start
    `None`/empty and are filled in by the Task 1 (Inspector) callback, then
    the Task 2 (EDA Analyst) guardrail/callback, then the Task 3 (Contract
    Architect) guardrail/callback. Fields are plain, inspectable attributes
    (not private) so tests can assert on them directly.
    """

    run_id: str
    dataset_name: str
    source_documentation_url: str
    business_context: dict[str, Any]
    source_documentation_excerpt: str

    # --- output paths (workspace-relative; defaults to artifacts/crew1) ---
    clean_data_csv: Path
    dataset_contract_json: Path
    eda_report_html: Path
    insights_md: Path
    internal_dir: Path
    figures_dir: Path

    # --- raw data + its deterministic profile (read-only inputs) ---
    raw_df: "pd.DataFrame"
    raw_profile: "DatasetProfile"

    # --- filled in by Task 1's callback ---
    cleaning_plan: "CleaningPlan | None" = None
    clean_df: "pd.DataFrame | None" = None
    clean_profile: "DatasetProfile | None" = None
    clean_columns: set[str] | None = None
    eda_stats: dict[str, Any] | None = None
    numeric_correlations: dict[str, float] | None = None
    figure_relpaths: list[str] = field(default_factory=list)
    last_rejected_cleaning_plan_raw: str | None = None

    # --- filled in by Task 2's guardrail/callback ---
    insights_doc: "InsightsDoc | None" = None
    eda_degraded: bool = False
    eda_degraded_reason: str | None = None
    insights_guardrail_attempts: int = 0

    # --- filled in by Task 3's guardrail/callback ---
    contract_draft: "ContractDraft | None" = None
    final_contract: "DatasetContract | None" = None
    last_rejected_contract_draft_raw: str | None = None

    # --- overall run status, set by run_analyst_crew() ---
    status: str = "running"
    failure_category: str | None = None
    failure_message: str | None = None


_active_context: Crew1RunContext | None = None


@contextmanager
def crew1_run_context(ctx: Crew1RunContext) -> Iterator[Crew1RunContext]:
    """Make *ctx* the active Crew 1 run context for the duration of the
    `with` block (i.e. for the one `crew.kickoff()` call it wraps).

    Raises `RuntimeError` if a context is already active — Crew 1 never
    supports concurrent/nested runs in this project.
    """
    global _active_context
    if _active_context is not None:
        raise RuntimeError(
            "a Crew1RunContext is already active — concurrent/nested Crew 1 "
            "runs are not supported; this is a caller wiring error"
        )
    _active_context = ctx
    try:
        yield ctx
    finally:
        _active_context = None


def get_active_context() -> Crew1RunContext:
    """Return the currently active `Crew1RunContext`.

    Raises `RuntimeError` (never returns `None`) if called outside a
    `with crew1_run_context(ctx):` block — every Crew 1 tool/guardrail/
    callback function calls this first thing, so an out-of-band call is a
    genuine wiring bug, not a data problem, and must fail loudly.
    """
    if _active_context is None:
        raise RuntimeError(
            "no active Crew1RunContext — this function was called outside "
            "`crew1_run_context(...)`; this is a caller wiring error"
        )
    return _active_context
