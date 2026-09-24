"""Page 2 — Crew 1 Analysis (PROJECT_PLAN.md §Q.5, Phase 9 Internal Gate 9.5).

Presents Crew 1's human-readable output as-is: the cleaned data preview,
the existing `eda_report.html`, and `insights.md`. Nothing here recomputes
EDA or insights — the existing artifacts are the source of truth.
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

st.set_page_config(page_title="Crew 1 Analysis · Harbor & Vale", page_icon="🔎", layout="wide")
ui.inject_css()

st.title("🔎 Crew 1 — Analyst Crew")
st.caption("Data Quality Inspector · Contract Architect · Insight Analyst")

summary_result = ui.load_run_summary()
status = ui.compute_status(summary_result.data) if summary_result.ok else ui.compute_status(None)

if not status.has_run:
    ui.render_missing("No pipeline run available yet — Crew 1 has not produced any artifacts.")
elif not status.crew1_completed:
    ui.render_banner("fail", message="Crew 1 did not complete.")
    if status.failure_summary:
        st.error(status.failure_summary)
else:
    crew1_degraded = (summary_result.data or {}).get("crew1", {}).get("degraded_agents") or []
    if crew1_degraded:
        ui.render_banner("degraded", message=f"Narrative fallback used for: {', '.join(crew1_degraded)}")
    else:
        st.success("Crew 1 completed — no degraded agents.")

st.divider()

# --- Cleaned data preview --------------------------------------------------

st.subheader("Cleaned dataset preview")
csv_result = ui.load_csv_preview(ui.HANDOFF_CLEAN_DATA)
if csv_result.missing:
    ui.render_missing("clean_data.csv not available yet.")
elif not csv_result.ok:
    ui.render_error(csv_result, "artifacts/crew1/clean_data.csv")
else:
    df = csv_result.data
    st.caption(f"{df.shape[0]:,} rows × {df.shape[1]} columns")
    st.dataframe(df.head(50), width="stretch")

st.divider()

# --- EDA report -------------------------------------------------------------

st.subheader("EDA report")
eda_result = ui.load_html(ui.EDA_REPORT_HTML)
if eda_result.missing:
    ui.render_missing("eda_report.html not available yet.")
elif not eda_result.ok:
    ui.render_error(eda_result, "artifacts/crew1/eda_report.html")
else:
    st.iframe(eda_result.data, height=900)

st.divider()

# --- Business insights -------------------------------------------------------

st.subheader("Business insights")
insights_result = ui.load_markdown(ui.INSIGHTS_MD)
if insights_result.missing:
    ui.render_missing("insights.md not available yet.")
elif not insights_result.ok:
    ui.render_error(insights_result, "artifacts/crew1/insights.md")
else:
    st.markdown(insights_result.data)

# --- Figures ------------------------------------------------------------------

figures_dir = ui.CREW1_FIGURES
figure_files = sorted(figures_dir.glob("*.png")) if figures_dir.is_dir() else []
if figure_files:
    st.divider()
    st.subheader("Figures")
    cols = st.columns(2)
    for i, fig_path in enumerate(figure_files):
        with cols[i % 2]:
            st.image(str(fig_path), caption=fig_path.stem, width="stretch")
