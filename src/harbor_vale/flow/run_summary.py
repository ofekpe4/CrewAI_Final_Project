"""`run_summary.json` — the application's source of truth (PROJECT_PLAN.md §Q.3).

Built entirely from `PipelineState` plus a handful of fixed, well-known
production paths (`io_paths.py`) — zero LLM calls, zero Crew/Agent/Flow
objects. Phase 9's Streamlit app is expected to read this file and NOT
re-run any pipeline logic itself (§Q.5: "האפליקציה לא מריצה לוגיקה — היא
קוראת ארטיפקטים ומציגה").

**On a validation failure, `crew2.started` is explicitly `false` with a
clear `reason`** (§Q.3's own worked example) — never silently omitted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harbor_vale.flow.state import PipelineState
from harbor_vale.io_paths import (
    EDA_REPORT_HTML,
    EVALUATION_REPORT_MD,
    FEATURES_CSV,
    HANDOFF_CLEAN_DATA,
    HANDOFF_CONTRACT,
    INSIGHTS_MD,
    MODEL_CARD_MD,
    MODEL_JOBLIB,
    RUN_SUMMARY_JSON,
    VALIDATION_REPORT_JSON,
    relative_to_root,
)


def _crew2_not_started_reason(state: PipelineState) -> str | None:
    if state.crew2_started:
        return None
    if state.validate_only:
        return "validate-only mode — Crew 2 is intentionally not run"
    if state.status == "halted_agent_failure":
        return "Crew 1 reported a critical agent failure — the pipeline halted before Crew 2 could start"
    if state.status == "halted_validation":
        return "validation gate failed"
    if state.status == "halted_error":
        return "a runtime error halted the pipeline before Crew 2 could start"
    return "the pipeline did not reach the gate-passed route"


def build_run_summary(state: PipelineState) -> dict[str, Any]:
    """Assemble the `run_summary.json` document (§Q.3) from `state`."""
    crew1_artifacts: dict[str, str] = {}
    if state.crew1_completed or state.validate_only:
        crew1_artifacts = {
            "clean_data_csv": relative_to_root(HANDOFF_CLEAN_DATA),
            "dataset_contract_json": relative_to_root(HANDOFF_CONTRACT),
            "eda_report_html": relative_to_root(EDA_REPORT_HTML),
            "insights_md": relative_to_root(INSIGHTS_MD),
        }

    crew2: dict[str, Any] = {"started": state.crew2_started}
    if state.crew2_started:
        crew2["completed"] = state.crew2_completed
        crew2["degraded_agents"] = list(state.crew2_degraded)
        if state.crew2_completed:
            crew2["artifacts"] = {
                "features_csv": relative_to_root(FEATURES_CSV),
                "model_joblib": relative_to_root(MODEL_JOBLIB),
                "evaluation_report_md": relative_to_root(EVALUATION_REPORT_MD),
                "model_card_md": relative_to_root(MODEL_CARD_MD),
            }
            crew2["best_model_name"] = state.best_model_name
            crew2["primary_metric"] = state.primary_metric
            crew2["primary_metric_value"] = state.primary_metric_value
    else:
        crew2["reason"] = _crew2_not_started_reason(state)

    return {
        "run_id": state.run_id,
        "status": state.status,
        "failure_category": state.failure_category,
        "failure_summary": state.failure_summary or None,
        "execution_mode": state.execution_mode,
        "fault_injection": state.fault_injection,
        "dataset": {
            "name": state.dataset_name,
            "rows": state.dataset_rows,
            "columns": state.dataset_columns,
        },
        "crew1": {
            "completed": state.crew1_completed,
            "degraded_agents": list(state.crew1_degraded),
            "artifacts": crew1_artifacts,
        },
        "validation": {
            "passed": state.validation_passed,
            "errors": state.validation_errors,
            "warnings": state.validation_warnings,
            "report_path": relative_to_root(VALIDATION_REPORT_JSON) if VALIDATION_REPORT_JSON.is_file() else None,
        },
        "crew2": crew2,
        "log_path": state.log_path or None,
    }


def write_run_summary(summary: dict[str, Any], *, out_path: Path | None = None) -> Path:
    target = out_path or RUN_SUMMARY_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return target
