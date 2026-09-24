"""Page 3 — Dataset Contract (PROJECT_PLAN.md §E, Phase 9 Internal Gate 9.6).

The project's central story: `dataset_contract.json` separates **OBSERVED**
(what Python measured off the candidate data) from **CONSTRAINTS** (what
the system may enforce, always with a `justification`). This page renders
that separation visually — never flattens the two into one generic JSON
blob — while still offering a raw JSON view as a secondary option.
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

st.set_page_config(page_title="Dataset Contract · Harbor & Vale", page_icon="📜", layout="wide")
ui.inject_css()

st.title("📜 Dataset Contract")
st.caption("What Python measured (OBSERVED) vs. what the system enforces, with justification (CONSTRAINTS).")

contract_result = ui.load_json(ui.HANDOFF_CONTRACT)

if contract_result.missing:
    ui.render_missing("dataset_contract.json not available yet — Crew 1 has not produced a contract.")
    st.stop()
if not contract_result.ok:
    ui.render_error(contract_result, "artifacts/crew1/dataset_contract.json")
    st.stop()

contract = contract_result.data

# --- Header metadata ---------------------------------------------------------

h1, h2, h3, h4 = st.columns(4)
h1.metric("Contract version", contract.get("contract_version", "—"))
h2.metric("Dataset", contract.get("dataset_name", "—"))
target = contract.get("target") or {}
h3.metric("Target", target.get("name", "—"))
h4.metric("Task type", target.get("task_type", "—"))
st.caption(f"Created by `{contract.get('created_by', '—')}` at {contract.get('created_at', '—')} · run `{contract.get('run_id', '—')}`")


def render_observed_constraints(observed: dict | None, constraints: dict | None, key_prefix: str) -> None:
    """The one visual pattern this whole page is built around — two
    side-by-side boxes, never merged."""
    col_o, col_c = st.columns(2)
    with col_o:
        st.markdown("<div class='hv-observed'><div class='hv-col-label'>👁 Observed — what Python measured</div>", unsafe_allow_html=True)
        if observed:
            for k, v in observed.items():
                if v is None:
                    continue
                st.markdown(f"<div class='hv-mono'>{k}: <b>{v}</b></div>", unsafe_allow_html=True)
        else:
            st.markdown("<span class='hv-muted'>no observed statistics recorded</span>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with col_c:
        st.markdown("<div class='hv-constraints'><div class='hv-col-label'>🔒 Constraints — what the system enforces</div>", unsafe_allow_html=True)
        if constraints:
            for cname, cval in constraints.items():
                if cval is None:
                    continue
                st.markdown(f"**{cname}**")
                if isinstance(cval, dict):
                    justification = cval.get("justification")
                    for ck, cv in cval.items():
                        if ck == "justification":
                            continue
                        st.markdown(f"<div class='hv-mono'>&nbsp;&nbsp;{ck}: {cv}</div>", unsafe_allow_html=True)
                    if justification:
                        st.markdown(f"<div class='hv-justification'>“{justification}”</div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<div class='hv-mono'>&nbsp;&nbsp;{cval}</div>", unsafe_allow_html=True)
        else:
            st.markdown("<span class='hv-muted'>no constraints declared</span>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)


st.divider()
st.subheader(f"Target — `{target.get('name', '—')}`")
render_observed_constraints(target.get("observed"), target.get("constraints"), "target")
if target.get("drift"):
    st.markdown("**Target drift policy**")
    st.json(target["drift"])

st.divider()
st.subheader("Columns")
columns = contract.get("columns") or []
column_names = [c.get("name", f"col_{i}") for i, c in enumerate(columns)]
if not columns:
    st.info("No columns declared in this contract.")
else:
    selected_name = st.selectbox("Select a column", column_names)
    selected = next((c for c in columns if c.get("name") == selected_name), None)
    if selected:
        st.caption(f"semantic_type: `{selected.get('semantic_type', '—')}`")
        render_observed_constraints(selected.get("observed"), selected.get("constraints"), f"col-{selected_name}")

st.divider()
c_left, c_right = st.columns(2)

with c_left:
    st.subheader("Required features")
    required = contract.get("required_features") or []
    st.write(", ".join(required) if required else "—")

    st.subheader("Primary key")
    pk = contract.get("primary_key") or {}
    st.write(f"Columns: {', '.join(pk.get('columns') or []) or '—'}")
    pk_constraints = pk.get("constraints") or {}
    for cname, cval in pk_constraints.items():
        if isinstance(cval, dict) and cval.get("justification"):
            st.caption(f"{cname}: {cval.get('value')} — “{cval['justification']}”")

with c_right:
    st.subheader("Excluded features")
    excluded = contract.get("excluded_features") or []
    if excluded:
        for ex in excluded:
            st.markdown(
                f"**`{ex.get('name')}`** — exclusion_type=`{ex.get('exclusion_type')}`, "
                f"enforcement=`{ex.get('enforcement')}`"
            )
            just = ex.get("justification")
            if just:
                st.markdown(f"<div class='hv-justification'>“{just}”</div>", unsafe_allow_html=True)
    else:
        st.write("—")

st.divider()
c_int, c_assume = st.columns(2)

with c_int:
    st.subheader("Integrity metadata")
    integrity = contract.get("integrity") or {}
    st.markdown(f"<span class='hv-mono'>sha256: {integrity.get('clean_data_sha256', '—')}</span>", unsafe_allow_html=True)
    st.write(f"Row count: {integrity.get('row_count', '—')} · Column count: {integrity.get('column_count', '—')}")
    with st.expander("Column order"):
        st.write(integrity.get("column_order") or [])

with c_assume:
    st.subheader("Assumptions")
    assumptions = contract.get("assumptions") or []
    if assumptions:
        for a in assumptions:
            st.markdown(f"- {a}")
    else:
        st.write("—")

validation_policy = contract.get("validation_policy") or {}
if validation_policy:
    st.divider()
    st.subheader("Validation policy")
    st.json(validation_policy)

st.divider()
with st.expander("Raw contract JSON"):
    st.json(contract)
