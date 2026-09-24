"""Page 5 — Crew 2 Modeling (PROJECT_PLAN.md §Q.5, Phase 9 Internal Gate 9.8).

Reads `experiments.json` for every number shown — **never parses agent
prose to determine the winner or a metric value**. The winner shown here is
always the Python-selected winner already written to that file; the
narrative `evaluation_report.md`/`model_card.md` are shown as-is for
context, not as a source of numbers.
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

st.set_page_config(page_title="Crew 2 Modeling · Harbor & Vale", page_icon="🧪", layout="wide")
ui.inject_css()

st.title("🧪 Crew 2 — Scientist Crew")
st.caption("Feature Engineer · Modeling Specialist · Responsible AI Documenter")

summary_result = ui.load_run_summary()
status = ui.compute_status(summary_result.data) if summary_result.ok else ui.compute_status(None)

if not status.has_run:
    ui.render_missing("No pipeline run available yet.")
    st.stop()
if not status.crew2_started:
    ui.render_banner("none", message=f"Crew 2 — NOT STARTED ({status.crew2_not_started_reason or 'gate did not pass'})")
    st.stop()
if not status.crew2_completed:
    ui.render_banner("fail", message="Crew 2 started but did not complete.")
    if status.failure_summary:
        st.error(status.failure_summary)

crew2_degraded = (summary_result.data or {}).get("crew2", {}).get("degraded_agents") or []
if crew2_degraded:
    ui.render_banner("degraded", message=f"Narrative fallback used for: {', '.join(crew2_degraded)}")
elif status.crew2_completed:
    st.success("Crew 2 completed — no degraded agents.")

st.divider()

# --- Feature preview ---------------------------------------------------------

st.subheader("Feature summary")
features_result = ui.load_csv_preview(ui.FEATURES_CSV)
if features_result.missing:
    ui.render_missing("features.csv not available yet.")
elif not features_result.ok:
    ui.render_error(features_result, "artifacts/crew2/features.csv")
else:
    df = features_result.data
    st.caption(f"{df.shape[0]:,} rows × {df.shape[1]} columns")
    st.dataframe(df.head(50), width="stretch")

st.divider()

# --- Model comparison — read only from experiments.json ---------------------

st.subheader("Model comparison")
exp_result = ui.load_json(ui.EXPERIMENTS_JSON)

if exp_result.missing:
    ui.render_missing("experiments.json not available yet.")
elif not exp_result.ok:
    ui.render_error(exp_result, "artifacts/crew2/experiments.json")
else:
    experiments = exp_result.data
    primary_metric = experiments.get("primary_metric", "—")
    winner = experiments.get("winner") or {}
    st.caption(f"Primary metric: **{primary_metric}** — {experiments.get('metric_rationale', '')}")

    variants = experiments.get("variants") or []
    rows = []
    for v in variants:
        cv = v.get("cv_metrics") or {}
        row = {"variant": v.get("name"), "estimator": v.get("estimator")}
        for m in ("roc_auc", "pr_auc", "f1", "precision", "recall", "accuracy"):
            if m in cv:
                row[m] = cv[m]
        row["winner"] = "🏆" if v.get("name") == winner.get("name") else ""
        rows.append(row)
    if rows:
        comp_df = pd.DataFrame(rows)
        st.dataframe(comp_df, width="stretch", hide_index=True)
        metric_col = primary_metric if primary_metric in comp_df.columns else None
        if metric_col:
            st.bar_chart(comp_df.set_index("variant")[metric_col])

    if winner:
        st.success(f"Python-selected winner: **{winner.get('name')}** ({winner.get('estimator')})")
        test_metrics = winner.get("test_metrics") or {}
        m1, m2, m3, m4 = st.columns(4)
        m1.metric(primary_metric, ui.format_metric(test_metrics.get(primary_metric)))
        m2.metric("F1", ui.format_metric(test_metrics.get("f1")))
        m3.metric("Precision", ui.format_metric(test_metrics.get("precision")))
        m4.metric("Recall", ui.format_metric(test_metrics.get("recall")))

        cm = test_metrics.get("confusion_matrix")
        if cm and len(cm) == 2:
            st.markdown("**Confusion matrix (test set)**")
            cm_df = pd.DataFrame(
                cm, index=["actual: 0", "actual: 1"], columns=["predicted: 0", "predicted: 1"]
            )
            st.dataframe(cm_df, width="content")

st.divider()

# --- Narrative reports (shown as-is, not parsed for numbers) ----------------

st.subheader("Evaluation report")
eval_result = ui.load_markdown(ui.EVALUATION_REPORT_MD)
if eval_result.missing:
    ui.render_missing("evaluation_report.md not available yet.")
elif not eval_result.ok:
    ui.render_error(eval_result, "artifacts/crew2/evaluation_report.md")
else:
    st.markdown(eval_result.data)

st.divider()

st.subheader("Model card")
card_result = ui.load_markdown(ui.MODEL_CARD_MD)
if card_result.missing:
    ui.render_missing("model_card.md not available yet.")
elif not card_result.ok:
    ui.render_error(card_result, "artifacts/crew2/model_card.md")
else:
    st.markdown(card_result.data)
