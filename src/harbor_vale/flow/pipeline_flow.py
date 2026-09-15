"""The real, production `HarborValeFlow` (PROJECT_PLAN.md §H, Phase 8).

Wires the already-proven Crew 1 (Phase 6), Crew 2 (Phase 7), and the
deterministic Phase 4 validation gate into one CrewAI `Flow[PipelineState]`
graph, using the real pinned `crewai==1.15.20` `@start`/`@listen`/`@router`/
`or_` decorators — never a plain `if report.passed: run_crew2()` inside one
method.

**Direction, always: `Crew1Result`/`Crew2Result` -> `PipelineState`.**
Neither `crews.analyst_crew` nor `crews.scientist_crew` imports anything
from this module; this module reads their already-stable, independently-
testable result objects and maps fields onto `self.state`.

**The central structural guarantee (§H.2):** `run_scientist_crew` (this
module's Flow node) is wired with `@listen("gate_passed")` — a string
route label only `gate_router` can emit, and only when
`ValidationReport.passed` (Phase 4, zero LLM involvement) is `True`. If the
router never returns `"gate_passed"`, this method is simply never called —
not "called but guarded by an `if`", structurally absent from that
execution's call graph.

**Large objects never touch `self.state`** (a Pydantic model that gets
serialized into `run_summary.json`/logs): the raw `DataFrame`, the full
`Crew1Result`/`Crew2Result` objects, and the injected test `LLM` all live
as plain (non-pydantic-field) instance attributes on the Flow object
itself — `self._raw_df`, `self._crew1_result`, `self._crew2_result`,
`self._llm` — set via the same "arbitrary attribute assignment" escape
hatch the installed `crewai.flow.runtime.Flow` base class documents for
exactly this purpose (verified directly against the installed package,
and the same pattern `crewai.memory.recall_flow.RecallFlow.__init__` uses).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pandas as pd
from crewai.flow.flow import Flow, listen, or_, router, start

from harbor_vale.contract.validator import render_validation_report_markdown, run_validation_gate
from harbor_vale.crews.analyst_crew import run_analyst_crew as _crew1_run_analyst_crew
from harbor_vale.crews.scientist_crew import run_scientist_crew as _crew2_run_scientist_crew
from harbor_vale.demo.fault_injection import FaultInjectionError, scale_change
from harbor_vale.flow.replay import ReplayMissingArtifactError, replay_crew1, replay_crew2
from harbor_vale.flow.run_metadata import build_run_metadata
from harbor_vale.flow.run_metadata import write_run_metadata as _write_run_metadata_file
from harbor_vale.flow.run_summary import build_run_summary
from harbor_vale.flow.run_summary import write_run_summary as _write_run_summary_file
from harbor_vale.flow.state import PipelineState
from harbor_vale.io_paths import (
    DOCS,
    EDA_REPORT_HTML,
    HANDOFF_CLEAN_DATA,
    HANDOFF_CONTRACT,
    INSIGHTS_MD,
    PROJECT_ROOT,
    RAW_TELCO_CHURN_CSV,
    VALIDATION,
    VALIDATION_REPORT_JSON,
    VALIDATION_REPORT_MD,
    ensure_runtime_dirs,
    handoff_snapshot_dir,
    log_file_for,
    relative_to_root,
    replay_workspace,
)
from harbor_vale.logging_setup import get_logger, setup_logging
from harbor_vale.ml.evaluate import verify_metric_in_experiments

if TYPE_CHECKING:
    from crewai import LLM

logger = get_logger(__name__)

FAULT_SCALE_COLUMN = "MonthlyCharges"
"""The real, live-verified scale-sensitive column in the actual committed
`dataset_contract.json` (both `MonthlyCharges` and `TotalCharges` declare a
`scale_drift` policy; `MonthlyCharges` is this Flow's chosen §P.1 demo
column — the mandatory `scale_change` mutation target)."""

_SUPPORTED_FAULTS = frozenset({"scale_change"})
"""Every other `demo/fault_injection.py` helper exists and is unit-tested
(Phase 4) but is not yet wired to a Flow injection point — only `scale_change`
is the §O.3/§P.1 MANDATORY scenario this Phase must wire end-to-end."""

_DATASET_NAME = "telco_customer_churn"


def _new_run_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"


def _resolve(relpath: str) -> Path:
    """Reconstruct an absolute path from a `relative_to_root`-produced
    string, exactly as `io_paths.relative_to_root` produced it."""
    return PROJECT_ROOT / relpath


class HarborValeFlow(Flow[PipelineState]):
    """The Phase 8 production Flow (PROJECT_PLAN.md §H.2)."""

    initial_state: type[PipelineState] = PipelineState

    def __init__(
        self,
        *,
        fault_injection: str | None = None,
        validate_only: bool = False,
        replay_plans: bool = False,
        dataset_path: str = "",
        llm: "LLM | None" = None,
        **kwargs,
    ) -> None:
        """Construct the Flow and seed the CLI-facing fields of its state.

        **Why constructor kwargs, not `initial_state=PipelineState(...)`:**
        verified directly against the installed, pinned `crewai==1.15.20` —
        `Flow[PipelineState]`'s generic specialization narrows the
        `initial_state` field's accepted runtime shape to `type[T]` only
        (a plain `BaseModel` *instance* is rejected with `pydantic_core`'s
        `is_subclass_of` error even though `_create_initial_state`'s own
        logic has a dead branch for it). Setting these fields on
        `self.state` right after `super().__init__()` — before any node
        runs — is the reliable, tested path; `kickoff(inputs=...)` is
        CrewAI's documented alternative but was not needed here.
        """
        super().__init__(**kwargs)
        self.state.fault_injection = fault_injection
        self.state.validate_only = validate_only
        self.state.replay_plans = replay_plans
        if dataset_path:
            self.state.dataset_path = dataset_path

        # Plain instance attributes — deliberately NOT pydantic state fields
        # (see module docstring). `llm` exists only so offline/mocked tests
        # can inject a scripted LLM into the real crews without a network
        # call; production runs never pass it (both crews fall back to their
        # own `config/llm.py`-centralized default).
        self._llm = llm
        self._raw_df: "pd.DataFrame | None" = None
        self._crew1_result = None
        self._crew2_result = None
        self._validation_report = None

    # ------------------------------------------------------------------
    # start_pipeline
    # ------------------------------------------------------------------
    @start()
    def start_pipeline(self) -> None:
        state = self.state
        if not state.run_id:
            state.run_id = _new_run_id()
        state.started_at = datetime.now(timezone.utc)

        if state.validate_only and state.replay_plans:
            state.status = "halted_error"
            state.failure_category = "runtime"
            state.failure_summary = "incompatible flags: --validate-only and --replay-plans cannot combine"
        elif state.validate_only and state.fault_injection:
            state.status = "halted_error"
            state.failure_category = "runtime"
            state.failure_summary = "incompatible flags: --validate-only and --inject-failure cannot combine"
        else:
            state.status = "running"

        state.execution_mode = (
            "validate_only" if state.validate_only else ("replay_plans" if state.replay_plans else "normal")
        )

        ensure_runtime_dirs()
        setup_logging(run_id=state.run_id)
        state.log_path = relative_to_root(log_file_for(state.run_id))

        logger.info(
            "start_pipeline: run_id=%s execution_mode=%s fault_injection=%s",
            state.run_id, state.execution_mode, state.fault_injection,
        )
        if state.fault_injection:
            logger.critical("FAULT INJECTION ACTIVE: %s", state.fault_injection)
        if state.status == "halted_error":
            logger.error("start_pipeline: %s", state.failure_summary)

    # ------------------------------------------------------------------
    # load_dataset
    # ------------------------------------------------------------------
    @listen(start_pipeline)
    def load_dataset(self) -> None:
        state = self.state
        if state.status != "running":
            return
        if state.validate_only:
            logger.info("load_dataset: skipped (validate-only mode)")
            return

        dataset_path = Path(state.dataset_path) if state.dataset_path else RAW_TELCO_CHURN_CSV
        try:
            if not dataset_path.is_file():
                raise FileNotFoundError(f"raw dataset not found at {dataset_path}")
            raw_df = pd.read_csv(dataset_path)
        except Exception as exc:  # noqa: BLE001 — a load failure is a normal halt, not a crash
            state.status = "halted_error"
            state.failure_category = "runtime"
            state.failure_summary = f"load_dataset failed: {exc}"
            logger.error("load_dataset failed: %s", exc)
            return

        self._raw_df = raw_df
        state.dataset_path = relative_to_root(dataset_path)
        state.dataset_name = _DATASET_NAME
        state.dataset_rows = int(len(raw_df))
        state.dataset_columns = int(len(raw_df.columns))
        logger.info("load_dataset: rows=%d columns=%d", state.dataset_rows, state.dataset_columns)

    # ------------------------------------------------------------------
    # run_analyst_crew (Crew 1)
    # ------------------------------------------------------------------
    @listen(load_dataset)
    def run_analyst_crew(self) -> None:
        state = self.state
        if state.status != "running" or state.validate_only:
            return

        if state.replay_plans:
            try:
                result = replay_crew1(
                    self._raw_df, run_id=state.run_id, workspace=replay_workspace(state.run_id) / "crew1"
                )
            except ReplayMissingArtifactError as exc:
                state.status = "halted_error"
                state.failure_category = "artifact_missing"
                state.failure_summary = str(exc)
                logger.error("run_analyst_crew (replay): %s", exc)
                return
        else:
            if self._raw_df is None:  # pragma: no cover — load_dataset guarantees this unless already halted
                state.status = "halted_error"
                state.failure_category = "runtime"
                state.failure_summary = "run_analyst_crew: no raw dataset loaded"
                return
            try:
                result = _crew1_run_analyst_crew(self._raw_df, run_id=state.run_id, llm=self._llm)
            except Exception as exc:  # noqa: BLE001 — genuine crash, not a critical-agent report
                state.status = "halted_error"
                state.failure_category = "runtime"
                state.failure_summary = f"Crew 1 crashed unexpectedly: {exc}"
                logger.error("run_analyst_crew crashed: %s", exc)
                return

        self._crew1_result = result
        if not result.completed:
            state.status = "halted_agent_failure"
            state.failure_category = "agent_output"
            state.failure_summary = result.failure_message or "Crew 1 reported a critical agent failure."
            logger.error("Crew 1 halted: %s", state.failure_summary)
            return

        state.crew1_completed = True
        state.crew1_degraded = ["eda_insights_analyst"] if result.eda_degraded else []
        logger.info("run_analyst_crew: completed degraded=%s", state.crew1_degraded)

        # Internal Gate 8.4 — run-scoped handoff snapshot, exact bytes,
        # created immediately after Crew 1's final artifacts are written and
        # BEFORE any fault injection can touch them.
        snapshot_dir = handoff_snapshot_dir(state.run_id)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        for src in (result.clean_data_csv, result.dataset_contract_json, result.eda_report_html, result.insights_md):
            (snapshot_dir / src.name).write_bytes(Path(src).read_bytes())
        state.handoff_snapshot_dir = relative_to_root(snapshot_dir)
        logger.info("run_analyst_crew: handoff snapshot created at %s", state.handoff_snapshot_dir)

    # ------------------------------------------------------------------
    # inject_fault_if_requested — the ONE injection point (§P.1)
    # ------------------------------------------------------------------
    @listen(run_analyst_crew)
    def inject_fault_if_requested(self) -> None:
        state = self.state
        if state.status != "running":
            return
        if not state.fault_injection:
            logger.info("inject_fault_if_requested: no-op (fault_injection is None)")
            return

        if state.fault_injection not in _SUPPORTED_FAULTS:
            state.status = "halted_error"
            state.failure_category = "runtime"
            state.failure_summary = f"unknown fault_injection scenario: {state.fault_injection!r}"
            logger.error("inject_fault_if_requested: %s", state.failure_summary)
            return

        snapshot_dir = _resolve(state.handoff_snapshot_dir)
        clean_data_csv = snapshot_dir / "clean_data.csv"
        tmp_path = snapshot_dir / "clean_data.csv.faulted"
        try:
            if state.fault_injection == "scale_change":
                scale_change(clean_data_csv, tmp_path, column=FAULT_SCALE_COLUMN, factor=100.0)
            tmp_path.replace(clean_data_csv)
        except FaultInjectionError as exc:
            state.status = "halted_error"
            state.failure_category = "runtime"
            state.failure_summary = f"fault injection failed: {exc}"
            logger.error("inject_fault_if_requested: %s", exc)
            return

        logger.critical(
            "FAULT INJECTION ACTIVE: %s applied to the run-scoped handoff snapshot only "
            "(column=%s, x100) — artifacts/crew1/* is untouched.",
            state.fault_injection, FAULT_SCALE_COLUMN,
        )

    # ------------------------------------------------------------------
    # validate_handoff — the deterministic gate (§F, sole PASS/FAIL authority)
    # ------------------------------------------------------------------
    @listen(inject_fault_if_requested)
    def validate_handoff(self) -> None:
        state = self.state
        if state.status != "running":
            return

        if state.validate_only:
            csv_path, contract_path = HANDOFF_CLEAN_DATA, HANDOFF_CONTRACT
            eda_path, insights_path = EDA_REPORT_HTML, INSIGHTS_MD
        else:
            snapshot_dir = _resolve(state.handoff_snapshot_dir)
            csv_path = snapshot_dir / "clean_data.csv"
            contract_path = snapshot_dir / "dataset_contract.json"
            eda_path = snapshot_dir / "eda_report.html"
            insights_path = snapshot_dir / "insights.md"

        report = run_validation_gate(
            csv_path, contract_path, eda_path, insights_path,
            run_id=state.run_id, fault_injection=state.fault_injection,
        )
        self._validation_report = report

        VALIDATION.mkdir(parents=True, exist_ok=True)
        VALIDATION_REPORT_JSON.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        VALIDATION_REPORT_MD.write_text(render_validation_report_markdown(report), encoding="utf-8")

        state.validation_passed = report.passed
        state.validation_errors = report.errors
        state.validation_warnings = report.warnings
        if report.contract_version:
            state.contract_version = report.contract_version

        if not state.dataset_name:
            # validate-only mode skipped load_dataset — backfill a real,
            # measured dataset summary from the CSV the gate just validated.
            try:
                probe = pd.read_csv(csv_path)
                state.dataset_name = _DATASET_NAME
                state.dataset_rows = int(len(probe))
                state.dataset_columns = int(len(probe.columns))
            except Exception:  # noqa: BLE001 — purely cosmetic enrichment; the gate already reported any real problem
                pass

        if report.passed:
            logger.info("validate_handoff: PASS (0 errors, %d warning(s))", report.warnings)
        else:
            logger.error("validate_handoff: FAIL (%d error(s), %d warning(s))", report.errors, report.warnings)
            for finding in report.findings:
                if finding.severity == "ERROR":
                    logger.error("  [ERROR] %s :: %s", finding.check_family, finding.message)

    # ------------------------------------------------------------------
    # gate_router — the ONLY place Crew 2's route is decided
    # ------------------------------------------------------------------
    @router(validate_handoff)
    def gate_router(self) -> str:
        state = self.state

        if state.status in ("halted_agent_failure", "halted_error"):
            logger.info("gate_router: pipeline already halted (%s) -> gate_failed", state.status)
            return "gate_failed"

        if not state.validation_passed:
            state.status = "halted_validation"
            state.failure_category = "contract_validation"
            state.failure_summary = (
                f"{state.validation_errors} validation error(s) — see {relative_to_root(VALIDATION_REPORT_JSON)}"
            )
            logger.info("gate_router: FAIL -> gate_failed")
            return "gate_failed"

        if state.validate_only:
            logger.info("gate_router: PASS (validate-only) -> validation_only_complete")
            return "validation_only_complete"

        logger.info("gate_router: PASS -> gate_passed")
        return "gate_passed"

    # ------------------------------------------------------------------
    # halt_pipeline — Crew 2 is structurally unreachable from here
    # ------------------------------------------------------------------
    @listen("gate_failed")
    def halt_pipeline(self) -> None:
        state = self.state
        logger.error(
            "halt_pipeline: status=%s failure_category=%s :: %s",
            state.status, state.failure_category, state.failure_summary,
        )

    # ------------------------------------------------------------------
    # run_scientist_crew (Crew 2) — reachable ONLY via "gate_passed"
    # ------------------------------------------------------------------
    @listen("gate_passed")
    def run_scientist_crew(self) -> None:
        state = self.state
        snapshot_dir = _resolve(state.handoff_snapshot_dir)
        clean_data_csv = snapshot_dir / "clean_data.csv"
        dataset_contract_json = snapshot_dir / "dataset_contract.json"

        state.crew2_started = True
        logger.info("run_scientist_crew: starting (handoff_status=gate_passed)")

        if state.replay_plans:
            try:
                result = replay_crew2(
                    clean_data_csv=clean_data_csv, dataset_contract_json=dataset_contract_json,
                    run_id=state.run_id, workspace=replay_workspace(state.run_id) / "crew2",
                )
            except ReplayMissingArtifactError as exc:
                state.status = "halted_error"
                state.failure_category = "artifact_missing"
                state.failure_summary = str(exc)
                logger.error("run_scientist_crew (replay): %s", exc)
                return
        else:
            try:
                result = _crew2_run_scientist_crew(
                    clean_data_csv=clean_data_csv, dataset_contract_json=dataset_contract_json,
                    run_id=state.run_id, contract_version=state.contract_version,
                    handoff_status="gate_passed", validation_warnings=state.validation_warnings,
                    llm=self._llm,
                )
            except Exception as exc:  # noqa: BLE001 — genuine crash, not a critical-agent report
                state.status = "halted_error"
                state.failure_category = "runtime"
                state.failure_summary = f"Crew 2 crashed unexpectedly: {exc}"
                logger.error("run_scientist_crew crashed: %s", exc)
                return

        self._crew2_result = result
        if not result.completed:
            state.status = "halted_agent_failure"
            state.failure_category = "agent_output"
            state.failure_summary = result.failure_message or "Crew 2 reported a critical agent failure."
            logger.error("Crew 2 halted: %s", state.failure_summary)
            return

        state.crew2_completed = True
        state.crew2_degraded = ["responsible_ai_documenter"] if result.model_card_degraded else []
        logger.info("run_scientist_crew: completed degraded=%s", state.crew2_degraded)

    # ------------------------------------------------------------------
    # verify_crew2_outputs
    # ------------------------------------------------------------------
    @listen(run_scientist_crew)
    def verify_crew2_outputs(self) -> None:
        state = self.state
        if state.status != "running":
            return
        result = self._crew2_result

        required = (
            (result.features_csv, "features.csv"),
            (result.model_joblib, "model.joblib"),
            (result.evaluation_report_md, "evaluation_report.md"),
            (result.model_card_md, "model_card.md"),
        )
        missing = [label for path, label in required if not Path(path).is_file() or Path(path).stat().st_size == 0]
        if missing:
            state.status = "halted_error"
            state.failure_category = "artifact_missing"
            state.failure_summary = f"Crew 2 completed but required artifact(s) missing/empty: {', '.join(missing)}"
            logger.error("verify_crew2_outputs: %s", state.failure_summary)
            return

        # Derived as a sibling of the artifact Crew 2 itself reported, never
        # a hardcoded production constant — correct whether `result` came
        # from a real production run (`artifacts/crew2/`), a replay
        # workspace, or a test's own temp directory.
        experiments_path = Path(result.evaluation_report_md).parent / "experiments.json"
        if not experiments_path.is_file():
            state.status = "halted_error"
            state.failure_category = "artifact_missing"
            state.failure_summary = f"experiments.json not found at {experiments_path}"
            logger.error("verify_crew2_outputs: %s", state.failure_summary)
            return

        experiments = json.loads(experiments_path.read_text(encoding="utf-8"))
        winner = experiments.get("winner") or {}
        winner_name = winner.get("name")
        primary_metric = experiments.get("primary_metric")
        if not winner_name or not primary_metric:
            state.status = "halted_error"
            state.failure_category = "artifact_missing"
            state.failure_summary = "experiments.json is missing a winner name or primary_metric"
            logger.error("verify_crew2_outputs: %s", state.failure_summary)
            return

        try:
            metric_value = verify_metric_in_experiments(
                experiments, variant_name=winner_name, split="test", metric=primary_metric
            )
        except (KeyError, ValueError) as exc:
            state.status = "halted_error"
            state.failure_category = "artifact_missing"
            state.failure_summary = f"experiments.json winner/metric could not be verified: {exc}"
            logger.error("verify_crew2_outputs: %s", state.failure_summary)
            return

        state.best_model_name = winner_name
        state.primary_metric = primary_metric
        state.primary_metric_value = metric_value
        logger.info("verify_crew2_outputs: OK — winner=%s %s=%s", winner_name, primary_metric, metric_value)

    # ------------------------------------------------------------------
    # finalize_success
    # ------------------------------------------------------------------
    @listen(verify_crew2_outputs)
    def finalize_success(self) -> None:
        state = self.state
        if state.status != "running":
            return
        state.status = "completed"
        logger.info(
            "finalize_success: run_id=%s best_model=%s %s=%s",
            state.run_id, state.best_model_name, state.primary_metric, state.primary_metric_value,
        )

    # ------------------------------------------------------------------
    # finalize_validate_only — the successful --validate-only terminal path
    # ------------------------------------------------------------------
    @listen("validation_only_complete")
    def finalize_validate_only(self) -> None:
        state = self.state
        state.status = "completed"
        logger.info("finalize_validate_only: validation PASSED against existing on-disk artifacts; Crew 2 not run")

    # ------------------------------------------------------------------
    # write_run_summary — every terminal path converges here
    # ------------------------------------------------------------------
    @listen(or_(halt_pipeline, finalize_success, finalize_validate_only))
    def write_run_summary(self) -> dict:
        state = self.state
        summary = build_run_summary(state)
        _write_run_summary_file(summary)

        metadata = build_run_metadata(
            run_id=state.run_id,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            contract_version=state.contract_version,
            execution_mode=state.execution_mode,
            fault_injection=state.fault_injection,
            replay_plans=state.replay_plans,
        )
        _write_run_metadata_file(metadata)

        logger.info(
            "write_run_summary: status=%s crew2_started=%s fault_injection=%s",
            state.status, state.crew2_started, state.fault_injection,
        )
        return summary


def generate_flow_diagram(out_dir: "Path | str | None" = None, *, basename: str = "flow_diagram") -> Path:
    """Render the Flow's own graph via the real pinned `flow.plot()` API
    (Internal Gate 8.13) — never a hand-drawn diagram. Constructing a
    `HarborValeFlow()` and calling `.plot()` visualizes the class's
    registered `@start`/`@listen`/`@router` structure; it does not execute
    any node (no dataset, no crew, no LLM call).

    **Environment-specific limitation, verified directly against the
    installed `crewai==1.15.20` renderer** (`crewai.flow.visualization.
    renderers.interactive.render_interactive`): `.plot()` always writes its
    three output files (`<basename>.html` + a sibling `_style.css` +
    `_script.js`) into a fresh OS temp directory and returns that absolute
    path — `filename` is documented as "basename only, no path", not a
    real destination. This function copies all three sibling files into
    `out_dir` (default `docs/`) so `docs/flow_diagram.html` is a real,
    committable, self-contained artifact (its relative CSS/JS references
    stay valid because the three files are copied as siblings).
    """
    import shutil

    out_dir = Path(out_dir) if out_dir is not None else DOCS
    flow = HarborValeFlow()
    generated_html = Path(flow.plot(filename=f"{basename}.html", show=False))

    out_dir.mkdir(parents=True, exist_ok=True)
    for sibling in generated_html.parent.glob(f"{basename}*"):
        shutil.copy2(sibling, out_dir / sibling.name)
    return out_dir / generated_html.name
