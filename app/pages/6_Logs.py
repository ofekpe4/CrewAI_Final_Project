"""Page 6 — Logs (PROJECT_PLAN.md §Q.1-Q.2, Phase 9 Internal Gate 9.9).

Displays the current run's log file, located via `run_summary.json`'s own
`log_path` field — never a guessed or reconstructed path. Never exposes
`.env`, API keys, or secrets: only the fixed `logs/pipeline_<run_id>.log`
file this project's own `logging_setup.py` writes is ever read.
"""

from __future__ import annotations

import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _APP_ROOT.parent
for _p in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / "src"), str(_APP_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import streamlit as st  # noqa: E402

from lib import ui_helpers as ui  # noqa: E402

st.set_page_config(page_title="Logs · Harbor & Vale", page_icon="📄", layout="wide")
ui.inject_css()

st.title("📄 Logs")

summary_result = ui.load_run_summary()

if summary_result.missing:
    ui.render_missing("No pipeline run available yet — no log to show.")
    st.stop()
if not summary_result.ok:
    ui.render_error(summary_result, "artifacts/run_summary.json")
    st.stop()

run_summary = summary_result.data
run_id = run_summary.get("run_id") or "—"
log_path_str = run_summary.get("log_path")

st.caption(f"Current run: `{run_id}`")

if not log_path_str:
    ui.render_missing("This run's summary has no log_path recorded.")
    st.stop()

# log_path in run_summary.json is always project-root-relative (io_paths'
# relative_to_root) — never an absolute, machine-specific path.
log_path = ui.PROJECT_ROOT / log_path_str
st.caption(f"Log file: `{log_path_str}`")

log_result = ui.read_log_tail(log_path)

if log_result.missing:
    ui.render_missing(f"Log file not found on disk: {log_path_str}")
    st.stop()
if not log_result.ok:
    ui.render_error(log_result, log_path_str)
    st.stop()

lines = log_result.data

levels = ["ALL", "CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]
selected_level = st.selectbox("Filter by level", levels, index=0)

if selected_level != "ALL":
    lines = [ln for ln in lines if ui.level_from_log_line(ln) == selected_level]

st.caption(f"{len(lines)} line(s) shown (most recent {min(len(log_result.data), 2000)} lines of the file scanned).")

if not lines:
    st.info("No log lines match this filter.")
else:
    st.code("\n".join(lines), language="text", height=600)
