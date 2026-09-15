"""The Flow's own state (PROJECT_PLAN.md §H.1, Phase 8 Internal Gate 8.1).

`PipelineState` is a small, Pydantic-typed record of ONE pipeline run —
never a dumping ground for large DataFrames, raw LLM prompts/responses,
`Crew`/`Agent`/`Task` objects, or API clients. Every field here is either a
plain scalar, a short list of strings, or a short dict — the kind of thing
that is cheap to serialize into `run_summary.json` and safe to inspect in a
test assertion.

**Direction, always: `Crew1Result`/`Crew2Result` -> `PipelineState`, never
the other way.** `pipeline_flow.py` reads fields off the already-existing,
independently-testable `Crew1Result`/`Crew2Result` objects (Phase 6/7) and
maps them onto this state; neither crew module imports this module or knows
`PipelineState` exists. This keeps both crews exactly as independently
runnable/testable as `scripts/run_crew1.py`/`scripts/run_crew2.py` already
prove them to be.

**One field beyond PROJECT_PLAN.md §H.1's illustrative snippet:** `id`.
The installed, pinned `crewai==1.15.20` Flow runtime requires every
structured Flow state model to declare an `id: str` field (verified
directly against the installed package —
`crewai/flow/runtime/__init__.py::_create_initial_state`, "Flow state model
must have an id field") — this is a framework mechanical requirement, not a
Plan field, and is kept fully separate from the Plan's own `run_id` (the
business-meaningful identifier every log line, artifact, and report is
keyed by). A handful of small scalar fields beyond §H.1's snippet are also
added — `execution_mode`, `dataset_name/rows/columns`, `log_path`,
`handoff_snapshot_dir` — each one because Q.3's `run_summary.json` or Gate
8.4's run-scoped-snapshot invariant explicitly needs it; none of them holds
anything large or agent-authored.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

PipelineStatus = Literal[
    "pending",
    "running",
    "halted_agent_failure",
    "halted_validation",
    "halted_error",
    "completed",
]

FailureCategory = Literal[
    "agent_output",
    "artifact_missing",
    "contract_validation",
    "runtime",
]

ExecutionMode = Literal["normal", "validate_only", "replay_plans"]
"""Recorded once by `start_pipeline` (Gate 8's "record obvious execution
mode" requirement) and carried through to `run_summary.json`/
`run_metadata.json`. `fault_injection` is an orthogonal, independent flag —
a `normal` OR `replay_plans` run may also have `fault_injection` set;
`validate_only` never does (rejected at the CLI, `scripts/run_pipeline.py`)."""


class PipelineState(BaseModel):
    """One pipeline run's Flow-level state (PROJECT_PLAN.md §H.1).

    `validate_assignment=True`: this object is mutated in place by every one
    of the Flow's dozen nodes (`state.status = "halted_validation"`, etc.)
    over one run's lifetime — validating each assignment (not just
    construction) catches a typo'd status/failure_category literal at the
    exact node that introduced it, rather than letting it silently
    corrupt state and surface later as a confusing `run_summary.json`.
    """

    model_config = ConfigDict(validate_assignment=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    """Framework-required Flow state identity — see the module docstring.
    Never referenced by any log message, report, or test; `run_id` is the
    field everything else in this project keys off."""

    run_id: str = ""
    started_at: datetime | None = None
    dataset_path: str = ""

    status: PipelineStatus = "pending"
    failure_category: FailureCategory | None = None
    failure_summary: str = ""

    fault_injection: str | None = None
    """`None` on every real run — the only way this is ever non-`None` is an
    explicit `--inject-failure <name>` CLI flag (PROJECT_PLAN.md §P.1). No
    default, no environment variable, ever sets this."""
    validate_only: bool = False
    replay_plans: bool = False
    execution_mode: ExecutionMode = "normal"

    # --- dataset summary (Q.3) — scalars only, never the DataFrame itself ---
    dataset_name: str = ""
    dataset_rows: int = 0
    dataset_columns: int = 0

    # --- Crew 1 -------------------------------------------------------------
    crew1_completed: bool = False
    crew1_degraded: list[str] = Field(default_factory=list)
    contract_version: str = ""

    # --- validation gate ------------------------------------------------------
    validation_passed: bool = False
    validation_errors: int = 0
    validation_warnings: int = 0

    # --- Crew 2 -------------------------------------------------------------
    crew2_started: bool = False
    crew2_completed: bool = False
    crew2_degraded: list[str] = Field(default_factory=list)
    best_model_name: str = ""
    primary_metric: str = ""
    primary_metric_value: float | None = None

    # --- Gate 8.4 run-scoped handoff snapshot / logging ----------------------
    handoff_snapshot_dir: str = ""
    """`runs/<run_id>/handoff/` (Gate 8.4) once `run_analyst_crew`/
    `load_dataset` (validate-only) has populated it — the exact files
    `validate_handoff` checks and, on PASS, the exact files Crew 2 is bound
    to. Empty until that point."""
    log_path: str = ""
