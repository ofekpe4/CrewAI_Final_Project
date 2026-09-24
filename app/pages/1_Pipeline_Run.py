"""Page 1 — Pipeline Run: the operator view (PROJECT_PLAN.md §Q.5, Phase 9
Internal Gate 9.4).

Shows current run status stage-by-stage and offers a controlled way to run
the existing pipeline. **This page never re-implements pipeline logic** —
"Run" invokes the exact same `scripts/run_pipeline.py` entrypoint a human
would run from the terminal, as a fixed-argv subprocess
(`lib/pipeline_runner.py`), and progress is reported via `st.status()` only
as the real process proves each step, never guessed ahead of time.
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

from config.llm import LLMConfig  # noqa: E402
from lib import pipeline_runner as runner  # noqa: E402
from lib import ui_helpers as ui  # noqa: E402

st.set_page_config(page_title="Pipeline Run · Harbor & Vale", page_icon="▶️", layout="wide")
ui.inject_css()

st.title("▶️ Pipeline Run")
st.caption("Operator view — current run status and a controlled way to run the existing pipeline.")

summary_result = ui.load_run_summary()
status = ui.compute_status(summary_result.data) if summary_result.ok else ui.compute_status(None)

# --- Current status -----------------------------------------------------

if summary_result.missing:
    ui.render_banner("none", message="No pipeline run has been executed yet.")
elif not summary_result.ok:
    ui.render_error(summary_result, "artifacts/run_summary.json")
else:
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

    st.subheader("Stages")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"**{ui.status_icon(status.crew1_completed or None)} Crew 1 — Analyst**")
        st.caption("completed" if status.crew1_completed else "not completed")
    with c2:
        st.markdown(f"**{ui.status_icon(status.validation_passed)} Validation Gate**")
        st.caption(
            "PASS" if status.validation_passed else ("FAIL" if status.validation_passed is False else "not run")
        )
    with c3:
        if status.crew2_started:
            st.markdown(f"**{ui.status_icon(status.crew2_completed or None)} Crew 2 — Scientist**")
            st.caption("completed" if status.crew2_completed else "started, not completed")
        else:
            st.markdown("**⏹ Crew 2 — Scientist**")
            st.caption(f"NOT STARTED — {status.crew2_not_started_reason or 'gate did not pass'}")

    if status.crew2_completed and status.best_model_name:
        st.success(
            f"Best model: **{status.best_model_name}** · "
            f"{status.primary_metric or 'metric'} = **{ui.format_metric(status.primary_metric_value)}**"
        )

    if status.is_fail and status.failure_summary:
        st.error(f"Failure reason ({status.failure_category}): {status.failure_summary}")

st.divider()

# --- Run controls ---------------------------------------------------------

st.subheader("Run the pipeline")

api_key_present = LLMConfig().api_key_present
mode_labels = {
    "normal": "Normal run (Crew 1 → Gate → Crew 2)",
    "validate_only": "Validate only (gate against existing artifacts/crew1/*, no crews, no LLM)",
    "replay_plans": "Replay plans (deterministic re-execution of stored plans, no LLM)",
}
mode_key = st.radio(
    "Run mode",
    options=list(mode_labels.keys()),
    format_func=lambda k: mode_labels[k],
    index=0,
    horizontal=False,
)

if mode_key == "normal" and not api_key_present:
    st.warning("OPENAI_API_KEY is not set — a normal run needs a live LLM call and will fail. "
               "`validate_only` and `replay_plans` do not require it.")

fault_injection: str | None = None
with st.expander("⚠️ Demo controls (fault injection) — off by default"):
    st.caption(
        "Injects the mandatory `scale_change` fault into a run-scoped copy of the Crew 1 "
        "handoff, strictly after Crew 1 and before the gate — the gate is expected to FAIL. "
        "Never applied unless explicitly enabled here."
    )
    inject = st.checkbox("Enable fault injection (scale_change)", value=False)
    if inject:
        if mode_key == "validate_only":
            st.error("Fault injection cannot be combined with validate-only mode.")
        else:
            fault_injection = "scale_change"
            st.warning("🎭 DEMO MODE will be active for this run.")

run_clicked = st.button("Run pipeline", type="primary", disabled=(inject and mode_key == "validate_only"))

if run_clicked:
    try:
        cmd_preview = runner.build_command(mode_key, fault_injection)
    except runner.InvalidRunRequest as exc:
        st.error(str(exc))
    else:
        st.caption(f"`{' '.join(cmd_preview)}`")
        exit_code: int | None = None
        with st.status("Running pipeline…", expanded=True) as status_box:
            try:
                for line in runner.stream_pipeline_run(mode_key, fault_injection):
                    if line.startswith("__EXIT_CODE__:"):
                        exit_code = int(line.split(":", 1)[1])
                    else:
                        st.write(line)
            except runner.InvalidRunRequest as exc:
                status_box.update(label=str(exc), state="error")
            else:
                if exit_code == 0:
                    status_box.update(label="Pipeline completed", state="complete")
                elif exit_code == 2:
                    status_box.update(label="Pipeline halted — validation gate FAILED", state="error")
                else:
                    status_box.update(label=f"Pipeline exited with code {exit_code}", state="error")

        # Reload run_summary.json / run_metadata.json / artifacts by
        # re-running this page script fresh (Internal Gate 9.4: "after
        # completion, reload ... and refresh the UI").
        st.rerun()
