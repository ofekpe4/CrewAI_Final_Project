"""Shared UI utilities for the Streamlit app (PROJECT_PLAN.md §Q.5, Phase 9,
Internal Gate 9.2).

Pure presentation plumbing: safe artifact loading, status derivation from
`run_summary.json`, and small rendering/formatting helpers reused across the
six pages. **No business/pipeline logic lives here** — no validation rule,
no contract check, no feature/model logic is re-implemented; every number
and verdict shown by the app is read from an artifact `src/harbor_vale/*`
already wrote.

Every loader returns an `ArtifactResult` instead of raising — a missing or
corrupt artifact is a normal, expected UI state (Internal Gate 9.10/9.11),
never an uncaught exception.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --- sys.path bootstrap — every app entrypoint derives this independently ---
# (same pattern as conftest.py / scripts/run_pipeline.py: no absolute paths,
# no shared import-time side effect).
_APP_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _APP_ROOT.parent
for _p in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from harbor_vale.io_paths import (  # noqa: E402
    ARTIFACTS,
    CREW1,
    CREW1_FIGURES,
    CREW2,
    EDA_REPORT_HTML,
    EVALUATION_REPORT_MD,
    EXPERIMENTS_JSON,
    FEATURES_CSV,
    HANDOFF_CLEAN_DATA,
    HANDOFF_CONTRACT,
    INSIGHTS_MD,
    LOGS,
    MODEL_CARD_MD,
    RUN_METADATA_JSON,
    RUN_SUMMARY_JSON,
    VALIDATION_REPORT_JSON,
    VALIDATION_REPORT_MD,
)

PROJECT_ROOT = _PROJECT_ROOT

__all__ = [
    "PROJECT_ROOT",
    "ARTIFACTS", "CREW1", "CREW1_FIGURES", "CREW2", "LOGS",
    "HANDOFF_CLEAN_DATA", "HANDOFF_CONTRACT", "EDA_REPORT_HTML", "INSIGHTS_MD",
    "VALIDATION_REPORT_JSON", "VALIDATION_REPORT_MD",
    "FEATURES_CSV", "EXPERIMENTS_JSON", "EVALUATION_REPORT_MD", "MODEL_CARD_MD",
    "RUN_SUMMARY_JSON", "RUN_METADATA_JSON",
    "ArtifactResult", "load_json", "load_markdown", "load_csv_preview",
    "read_log_tail", "artifact_exists", "load_run_summary", "load_run_metadata",
    "compute_status", "render_banner", "render_missing", "render_error",
    "status_icon", "format_metric", "inject_css", "level_from_log_line",
]


# ---------------------------------------------------------------------------
# Safe artifact loading — never raises, never fabricates data.
# ---------------------------------------------------------------------------


@dataclass
class ArtifactResult:
    """The outcome of trying to load one artifact off disk.

    Exactly one of three states: `MISSING` (file absent — a legitimate,
    expected "no run yet" state), `CORRUPT` (file present but unreadable —
    shown as a visible error, never silently treated as empty/PASS), or
    `OK` (`data` populated).
    """

    ok: bool
    data: Any = None
    missing: bool = False
    error: str | None = None
    path: Path | None = None


def artifact_exists(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def load_json(path: Path) -> ArtifactResult:
    import json

    if not path.is_file():
        return ArtifactResult(ok=False, missing=True, path=path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ArtifactResult(ok=False, error=f"could not read file: {exc}", path=path)
    if not raw.strip():
        return ArtifactResult(ok=False, error="file is empty", path=path)
    try:
        return ArtifactResult(ok=True, data=json.loads(raw), path=path)
    except json.JSONDecodeError as exc:
        return ArtifactResult(ok=False, error=f"malformed JSON: {exc}", path=path)


def load_markdown(path: Path) -> ArtifactResult:
    if not path.is_file():
        return ArtifactResult(ok=False, missing=True, path=path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ArtifactResult(ok=False, error=f"could not read file: {exc}", path=path)
    return ArtifactResult(ok=True, data=text, path=path)


def load_html(path: Path) -> ArtifactResult:
    if not path.is_file():
        return ArtifactResult(ok=False, missing=True, path=path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ArtifactResult(ok=False, error=f"could not read file: {exc}", path=path)
    return ArtifactResult(ok=True, data=text, path=path)


def load_csv_preview(path: Path, n: int = 20) -> ArtifactResult:
    """Loads a CSV for display. Returns the full DataFrame in `.data` (the
    committed handoff/feature CSVs are small enough — 7k rows — to load
    whole) so callers can report shape as well as a `.head(n)` preview; the
    UI itself decides how many rows to actually render."""
    if not path.is_file():
        return ArtifactResult(ok=False, missing=True, path=path)
    try:
        df = pd.read_csv(path)
    except (OSError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        return ArtifactResult(ok=False, error=f"could not parse CSV: {exc}", path=path)
    return ArtifactResult(ok=True, data=df, path=path)


def read_log_tail(path: Path, max_lines: int = 2000) -> ArtifactResult:
    if not path.is_file():
        return ArtifactResult(ok=False, missing=True, path=path)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return ArtifactResult(ok=False, error=f"could not read log: {exc}", path=path)
    return ArtifactResult(ok=True, data=lines[-max_lines:], path=path)


def level_from_log_line(line: str) -> str | None:
    """Best-effort level extraction from this project's fixed log format
    (`logging_setup.py`): ``TIMESTAMP LEVEL logger.name | message``. Returns
    `None` (shown as "unknown") rather than guessing on an unrecognized line
    — never invents a severity that was not actually in the line."""
    for level in ("CRITICAL", "ERROR", "WARNING", "WARN", "INFO", "DEBUG"):
        if f" {level} " in line or f" {level}\t" in line:
            return "WARNING" if level == "WARN" else level
    return None


def load_run_summary() -> ArtifactResult:
    return load_json(RUN_SUMMARY_JSON)


def load_run_metadata() -> ArtifactResult:
    return load_json(RUN_METADATA_JSON)


# ---------------------------------------------------------------------------
# Status derivation — reads run_summary.json fields only, never guesses from
# file presence alone (Phase 9 objective's explicit requirement).
# ---------------------------------------------------------------------------

_FAILING_STATUSES = {"halted_validation", "halted_agent_failure", "halted_error"}


@dataclass
class PipelineStatus:
    """The UI's derived view of one run — every field traced back to an
    exact `run_summary.json` field, never inferred from file presence."""

    has_run: bool = False
    run_id: str | None = None
    status: str | None = None
    execution_mode: str | None = None
    is_pass: bool = False
    is_fail: bool = False
    is_demo: bool = False
    is_degraded: bool = False
    failure_category: str | None = None
    failure_summary: str | None = None
    degraded_agents: list[str] = field(default_factory=list)
    fault_injection: str | None = None
    crew1_completed: bool = False
    validation_passed: bool | None = None
    crew2_started: bool = False
    crew2_completed: bool = False
    crew2_not_started_reason: str | None = None
    best_model_name: str | None = None
    primary_metric: str | None = None
    primary_metric_value: float | None = None
    headline: str = "No pipeline run available yet"


def compute_status(run_summary: dict | None) -> PipelineStatus:
    """Derives banner/status flags strictly from `run_summary.json` (§Q.3,
    the application's documented source of truth) — never from whether an
    artifact file merely exists on disk."""
    if not run_summary:
        return PipelineStatus()

    status = run_summary.get("status")
    fault = run_summary.get("fault_injection")
    crew1 = run_summary.get("crew1") or {}
    crew2 = run_summary.get("crew2") or {}
    degraded = list(crew1.get("degraded_agents") or []) + list(crew2.get("degraded_agents") or [])

    is_pass = status == "completed"
    is_fail = status in _FAILING_STATUSES
    is_demo = fault is not None
    is_degraded = bool(degraded)

    if is_fail:
        headline = f"Pipeline FAILED — {run_summary.get('failure_category') or status}"
    elif is_pass:
        headline = "Pipeline completed successfully"
    elif status == "running":
        headline = "Pipeline is running"
    elif status == "pending":
        headline = "Pipeline run recorded but not started"
    else:
        headline = f"Pipeline status: {status}"

    validation = run_summary.get("validation") or {}
    return PipelineStatus(
        has_run=True,
        run_id=run_summary.get("run_id"),
        status=status,
        execution_mode=run_summary.get("execution_mode"),
        is_pass=is_pass,
        is_fail=is_fail,
        is_demo=is_demo,
        is_degraded=is_degraded,
        failure_category=run_summary.get("failure_category"),
        failure_summary=run_summary.get("failure_summary"),
        degraded_agents=degraded,
        fault_injection=fault,
        crew1_completed=bool(crew1.get("completed")),
        validation_passed=validation.get("passed"),
        crew2_started=bool(crew2.get("started")),
        crew2_completed=bool(crew2.get("completed")),
        crew2_not_started_reason=crew2.get("reason"),
        best_model_name=crew2.get("best_model_name"),
        primary_metric=crew2.get("primary_metric"),
        primary_metric_value=crew2.get("primary_metric_value"),
        headline=headline,
    )


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def inject_css() -> None:
    """Injects `app/assets/style.css` once per page. Missing/unreadable CSS
    degrades to Streamlit's default styling — never a crash."""
    css_path = _APP_ROOT / "assets" / "style.css"
    if not css_path.is_file():
        return
    try:
        css = css_path.read_text(encoding="utf-8")
    except OSError:
        return
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


_BANNER_KIND = {
    "pass": ("hv-banner-pass", "✅ PASS"),
    "fail": ("hv-banner-fail", "❌ FAIL"),
    "demo": ("hv-banner-demo", "🎭 DEMO MODE"),
    "degraded": ("hv-banner-degraded", "⚠️ DEGRADED"),
    "none": ("hv-banner-none", "ℹ️ NO RUN YET"),
}


def render_banner(kind: str, title: str | None = None, message: str = "") -> None:
    """Renders one of the five fixed banner kinds (`pass`/`fail`/`demo`/
    `degraded`/`none`) via `app/assets/style.css` classes. Kinds are visually
    distinct by design (Internal Gate 9.11) — DEGRADED must never look like
    FAIL."""
    css_class, default_title = _BANNER_KIND.get(kind, _BANNER_KIND["none"])
    heading = title or default_title
    body = f"<div class='hv-banner {css_class}'><div class='hv-banner-title'>{heading}</div>"
    if message:
        body += f"<div class='hv-banner-message'>{message}</div>"
    body += "</div>"
    st.markdown(body, unsafe_allow_html=True)


def render_missing(message: str = "No pipeline run available yet.") -> None:
    st.info(message)


def render_error(result: ArtifactResult, label: str) -> None:
    """Visible, non-fatal error surface for a corrupt/unreadable artifact —
    never silently treated as a pass or as empty data."""
    st.error(f"{label}: {result.error}")


def status_icon(ok: bool | None) -> str:
    if ok is True:
        return "✅"
    if ok is False:
        return "❌"
    return "⏳"


def format_metric(value: Any, digits: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return str(value)
