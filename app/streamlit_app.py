"""Harbor & Vale — Streamlit application entrypoint (PROJECT_PLAN.md §Q,
Phase 9).

**Architecture rule (Internal Gate 9.3):** this app PRESENTS and INVOKES the
already-existing pipeline (`src/harbor_vale/*`, `scripts/run_pipeline.py`).
It never reimplements validation, contract checking, feature engineering,
model training, winner selection, or fault injection — every fact shown
here is read from an artifact those modules already wrote.

Run with:
    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _APP_ROOT.parent
for _p in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / "src"), str(_APP_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import streamlit as st  # noqa: E402

from lib import ui_helpers as ui  # noqa: E402

st.set_page_config(page_title="Harbor & Vale", page_icon="⛵", layout="wide")
ui.inject_css()

st.title("⛵ Harbor & Vale")
st.caption("An industry-simulated AI product workflow — two CrewAI crews, separated by a machine-enforced dataset contract and a deterministic validation gate.")

st.markdown(
    "**The problem this pipeline solves:** predict customer churn on the "
    "Telco Customer Churn dataset. **Crew 1** (Data Quality Inspector, "
    "Contract Architect, Insight Analyst) cleans the raw data, writes a "
    "`DatasetContract`, and produces EDA + business insights. A "
    "**deterministic Python gate** — never an LLM — then checks the "
    "candidate handoff against that contract. Only on a PASS does "
    "**Crew 2** (Feature Engineer, Modeling Specialist, Responsible AI "
    "Documenter) train and compare models, select a winner, and document it."
)

summary_result = ui.load_run_summary()
metadata_result = ui.load_run_metadata()

if summary_result.missing:
    ui.render_banner("none", message="No pipeline run has been executed yet.")
    st.info(
        "Go to **1 · Pipeline Run** in the sidebar to start the first run, "
        "or run `make run` from the terminal and come back."
    )
elif not summary_result.ok:
    ui.render_error(summary_result, "artifacts/run_summary.json")
else:
    status = ui.compute_status(summary_result.data)

    if status.is_fail:
        ui.render_banner("fail", message=status.headline)
    elif status.is_pass:
        ui.render_banner("pass", message=status.headline)
    else:
        ui.render_banner("none", message=status.headline)

    if status.is_demo:
        ui.render_banner("demo", message=f"Fault injection active: {status.fault_injection}")
    if status.is_degraded:
        ui.render_banner("degraded", message=f"Degraded agent(s): {', '.join(status.degraded_agents)}")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Run ID", status.run_id or "—")
    col2.metric("Execution mode", status.execution_mode or "—")
    col3.metric("Validation", "PASS" if status.validation_passed else ("FAIL" if status.validation_passed is False else "—"))
    if status.crew2_completed and status.primary_metric_value is not None:
        col4.metric(status.primary_metric or "primary metric", ui.format_metric(status.primary_metric_value))
    else:
        col4.metric("Crew 2", "started" if status.crew2_started else "not started")

    if metadata_result.ok:
        meta = metadata_result.data
        with st.expander("Latest run metadata"):
            m1, m2, m3 = st.columns(3)
            m1.write(f"**Python:** {meta.get('python_version', '—')}")
            m1.write(f"**crewai:** {meta.get('package_versions', {}).get('crewai', '—')}")
            m2.write(f"**LLM model:** {meta.get('llm', {}).get('model', '—')}")
            m2.write(f"**Contract version:** {meta.get('contract_version', '—')}")
            m3.write(f"**Git commit:** {(meta.get('git_commit') or '—')[:12]}")
            m3.write(f"**Replay plans:** {meta.get('replay_plans', '—')}")
    elif metadata_result.error:
        ui.render_error(metadata_result, "artifacts/run_metadata.json")

st.divider()
st.subheader("Navigation")
st.markdown(
    "- **1 · Pipeline Run** — operator view: current status, stage-by-stage progress, run the pipeline\n"
    "- **2 · Crew 1 Analysis** — cleaned data preview, EDA report, business insights\n"
    "- **3 · Dataset Contract** — the `DatasetContract`, observed vs. enforced constraints\n"
    "- **4 · Validation Gate** — PASS/FAIL, findings, and why\n"
    "- **5 · Crew 2 Modeling** — feature summary, model comparison, the winner, Model Card\n"
    "- **6 · Logs** — the current run's log file"
)
