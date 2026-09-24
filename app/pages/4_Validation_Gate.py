"""Page 4 — Validation Gate (PROJECT_PLAN.md §F, Phase 9 Internal Gate 9.7).

Reads `artifacts/validation/validation_report.json` — written entirely by
`src/harbor_vale/contract/validator.py`'s deterministic Python gate — and
renders it. **This page never recomputes a single check**; PASS/FAIL and
every finding shown here are exactly what the gate already decided.
"""

from __future__ import annotations

import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _APP_ROOT.parent
for _p in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / "src"), str(_APP_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from lib import ui_helpers as ui  # noqa: E402

st.set_page_config(page_title="Validation Gate · Harbor & Vale", page_icon="🚦", layout="wide")
ui.inject_css()

st.title("🚦 Validation Gate")
st.caption("Deterministic Python only — no LLM ever decides PASS/FAIL here.")

report_result = ui.load_json(ui.VALIDATION_REPORT_JSON)

if report_result.missing:
    ui.render_missing("No validation report yet — the gate has not run.")
    st.stop()
if not report_result.ok:
    ui.render_error(report_result, "artifacts/validation/validation_report.json")
    st.stop()

report = report_result.data
passed = report.get("passed")

if report.get("fault_injection"):
    ui.render_banner("demo", message=f"Fault injection active: {report['fault_injection']}")

if passed:
    ui.render_banner("pass", message=f"{report.get('checks_run', 0)} checks run · 0 errors · {report.get('warnings', 0)} warning(s)")
else:
    ui.render_banner("fail", message=f"{report.get('errors', 0)} error(s) · {report.get('warnings', 0)} warning(s) among {report.get('checks_run', 0)} checks run")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Checks run", report.get("checks_run", "—"))
c2.metric("Errors", report.get("errors", "—"))
c3.metric("Warnings", report.get("warnings", "—"))
c4.metric("Contract version", report.get("contract_version", "—"))

findings = report.get("findings") or []

st.divider()
st.subheader("Findings")

if not findings:
    st.success("No findings. Every applicable check passed cleanly.")
else:
    # Scale drift is the project's flagship failure signature — surface it
    # first and prominently, never buried in a generic table row.
    scale_drift_findings = [f for f in findings if f.get("check_family") == "scale_drift"]
    for f in scale_drift_findings:
        st.error(f"**SCALE DRIFT** — `{f.get('column')}`: {f.get('message')}")
        if f.get("contract_justification"):
            st.caption(f"Contract justification: “{f['contract_justification']}”")

    rows = []
    for f in findings:
        rows.append({
            "severity": f.get("severity"),
            "check_id": f.get("check_id"),
            "family": f.get("check_family"),
            "column": f.get("column") or "—",
            "message": f.get("message"),
            "expected": f.get("expected"),
            "observed": f.get("observed"),
            "justification": f.get("contract_justification") or "—",
        })
    df = pd.DataFrame(rows).sort_values(
        by="severity", key=lambda s: s.map({"ERROR": 0, "WARN": 1, "INFO": 2}).fillna(3)
    )
    st.dataframe(df, width="stretch", hide_index=True)

    with st.expander("Findings grouped by check family"):
        for family in sorted({f.get("check_family") for f in findings}):
            fam_findings = [f for f in findings if f.get("check_family") == family]
            st.markdown(f"**{family}** ({len(fam_findings)})")
            for f in fam_findings:
                sev = f.get("severity", "INFO")
                st.markdown(
                    f"<span class='hv-sev-{sev}'>{sev}</span> · `{f.get('check_id')}` "
                    f"({f.get('column') or 'dataset-level'}): {f.get('message')}",
                    unsafe_allow_html=True,
                )

st.divider()
md_result = ui.load_markdown(ui.VALIDATION_REPORT_MD)
if md_result.ok:
    with st.expander("Full validation_report.md"):
        st.markdown(md_result.data)
elif not md_result.missing:
    ui.render_error(md_result, "artifacts/validation/validation_report.md")
