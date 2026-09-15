"""Crew 2 — the Data Scientist Crew (PROJECT_PLAN.md §G, §C.2.2 Pattern A,
Phase 7 Internal Gates 7.1-7.6).

**Exactly one CrewAI `Crew`, three `Agent`s, three `Task`s,
`Process.sequential`** — the same Pattern A structure Crew 1 uses.
`build_scientist_crew` constructs it; `run_scientist_crew` is the one
production entry point that wires a `Crew2RunContext`, calls
`crew.kickoff()`, and turns CrewAI's own success/exception outcome into a
`Crew2Result` — never a Phase 8 `PipelineState`/`Flow` (explicitly out of
scope this phase).

**Handoff status as metadata, not as a gate re-run.** §G.0's
`handoff_status`/`contract_version`/`validation_warnings` are carried as
plain attributes on `Crew2RunContext` (populated by the caller — normally
`scripts/run_crew2.py`, which runs the Phase 4 gate itself first) rather
than templated into a Task description via `kickoff(inputs=...)`, for the
same reason Crew 1's `dataset_name` mostly lives on `Crew1RunContext`: one
explicit, inspectable place, not two possibly-divergent ones. **Crew 2 never
re-runs or second-guesses the gate itself** — by the time `run_scientist_crew`
is called, the gate has already decided PASS; this function trusts that
decision and only carries its outcome forward as metadata.

**"Agent plans, Python executes."** No line in this module mutates a
DataFrame, trains a model, or decides PASS/FAIL of anything — that is
entirely `callbacks.py` (deterministic) and the Phase 4 gate (invoked
separately, before this function, never from inside Crew 2 itself).
"""

from pathlib import Path
from typing import Literal

import yaml
from crewai import LLM, Agent, Crew, Process, Task

from config.llm import LLMConfig, load_llm_config
from harbor_vale.access.handoff import Crew2Handoff, build_crew2_handoff
from harbor_vale.crews.scientist_crew.callbacks import (
    persist_feature_plan_and_build_features,
    render_model_card,
    train_and_evaluate,
)
from harbor_vale.crews.scientist_crew.guardrails import (
    GUARDRAIL_MAX_RETRIES,
    guardrail_experiment_plan,
    guardrail_feature_plan,
    guardrail_model_card,
)
from harbor_vale.crews.scientist_crew.runtime import Crew2RunContext, crew2_run_context
from harbor_vale.crews.scientist_crew.tools import (
    profile_handoff_data,
    read_experiment_results,
    read_feature_plan,
    read_handoff,
)
from harbor_vale.io_paths import (
    CREW2_INTERNAL,
    EVALUATION_REPORT_MD,
    EXPERIMENTS_JSON,
    FEATURES_CSV,
    MODEL_CARD_MD,
    MODEL_JOBLIB,
)
from harbor_vale.plans.experiment_plan import ExperimentPlan
from harbor_vale.plans.feature_plan import FeaturePlan
from harbor_vale.plans.model_card import ModelCard

_CONFIG_DIR = Path(__file__).resolve().parent / "config"
_AGENTS_YAML = _CONFIG_DIR / "agents.yaml"
_TASKS_YAML = _CONFIG_DIR / "tasks.yaml"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _build_llm(config: LLMConfig | None = None) -> LLM:
    """The one, centralized place Crew 2 builds its LLM — identical pattern
    to Crew 1's `_build_llm` (PROJECT_PLAN.md §L)."""
    config = config or load_llm_config()
    return LLM(**config.as_crewai_llm_kwargs())


def build_scientist_crew(ctx: Crew2RunContext, *, llm: LLM | None = None) -> Crew:
    """Construct the one Crew 2 `Crew` — 3 agents, 3 tasks, `Process.sequential`.

    Does not call `crew.kickoff()`. `ctx` must already be the active
    `Crew2RunContext` (normally via `run_scientist_crew`'s
    `with crew2_run_context(ctx):` block) — every tool/guardrail/callback
    wired onto the returned `Crew` reads it via
    `runtime.get_active_context()` when the crew actually runs.
    """
    llm = llm or _build_llm()
    agents_cfg = _load_yaml(_AGENTS_YAML)
    tasks_cfg = _load_yaml(_TASKS_YAML)

    feature_engineer = Agent(
        role=agents_cfg["feature_engineer"]["role"].strip(),
        goal=agents_cfg["feature_engineer"]["goal"].strip(),
        backstory=agents_cfg["feature_engineer"]["backstory"].strip(),
        llm=llm,
        tools=[read_handoff, profile_handoff_data],
        allow_delegation=False,
        verbose=True,
    )
    modeling_specialist = Agent(
        role=agents_cfg["modeling_specialist"]["role"].strip(),
        goal=agents_cfg["modeling_specialist"]["goal"].strip(),
        backstory=agents_cfg["modeling_specialist"]["backstory"].strip(),
        llm=llm,
        tools=[read_handoff, read_feature_plan],
        allow_delegation=False,
        verbose=True,
    )
    responsible_ai_documenter = Agent(
        role=agents_cfg["responsible_ai_documenter"]["role"].strip(),
        goal=agents_cfg["responsible_ai_documenter"]["goal"].strip(),
        backstory=agents_cfg["responsible_ai_documenter"]["backstory"].strip(),
        llm=llm,
        tools=[read_handoff, read_feature_plan, read_experiment_results],
        allow_delegation=False,
        verbose=True,
    )

    feature_task = Task(
        description=tasks_cfg["feature_engineer_task"]["description"].strip(),
        expected_output=tasks_cfg["feature_engineer_task"]["expected_output"].strip(),
        agent=feature_engineer,
        context=[],
        output_pydantic=FeaturePlan,
        guardrail=guardrail_feature_plan,
        guardrail_max_retries=GUARDRAIL_MAX_RETRIES,
        callback=persist_feature_plan_and_build_features,
    )
    modeling_task = Task(
        description=tasks_cfg["modeling_specialist_task"]["description"].strip(),
        expected_output=tasks_cfg["modeling_specialist_task"]["expected_output"].strip(),
        agent=modeling_specialist,
        context=[feature_task],
        output_pydantic=ExperimentPlan,
        guardrail=guardrail_experiment_plan,
        guardrail_max_retries=GUARDRAIL_MAX_RETRIES,
        callback=train_and_evaluate,
    )
    documenter_task = Task(
        description=tasks_cfg["responsible_ai_documenter_task"]["description"].strip(),
        expected_output=tasks_cfg["responsible_ai_documenter_task"]["expected_output"].strip(),
        agent=responsible_ai_documenter,
        context=[feature_task, modeling_task],
        output_pydantic=ModelCard,
        guardrail=guardrail_model_card,
        guardrail_max_retries=GUARDRAIL_MAX_RETRIES,
        callback=render_model_card,
    )

    return Crew(
        agents=[feature_engineer, modeling_specialist, responsible_ai_documenter],
        tasks=[feature_task, modeling_task, documenter_task],
        process=Process.sequential,
        verbose=True,
    )


class Crew2Result:
    """The outcome of one `run_scientist_crew` call — a local, Crew-2-scoped
    result object. **Not `PipelineState`** (Phase 8)."""

    def __init__(self, ctx: Crew2RunContext) -> None:
        self.run_id = ctx.run_id
        self.status: Literal["completed", "halted_agent_failure"] = ctx.status  # type: ignore[assignment]
        self.failure_category = ctx.failure_category
        self.failure_message = ctx.failure_message
        self.model_card_degraded = ctx.model_card_degraded
        self.model_card_degraded_reason = ctx.model_card_degraded_reason
        self.features_csv = ctx.features_csv
        self.model_joblib = ctx.model_joblib
        self.experiments_json = ctx.experiments_json
        self.evaluation_report_md = ctx.evaluation_report_md
        self.model_card_md = ctx.model_card_md
        self.winner_name = ctx.winner_name
        self.ctx = ctx

    @property
    def completed(self) -> bool:
        return self.status == "completed"


def run_scientist_crew(
    *,
    clean_data_csv: Path,
    dataset_contract_json: Path,
    run_id: str,
    contract_version: str,
    handoff_status: str = "gate_passed",
    validation_warnings: int = 0,
    workspace: Path | None = None,
    llm: LLM | None = None,
) -> Crew2Result:
    """Run Crew 2 once, end to end, against one approved Crew 1 handoff.

    Args:
        clean_data_csv: the approved `clean_data.csv` — the ONLY clean-data
            path this function (trusted orchestration) ever touches; Crew 2
            itself reaches it exclusively through `read_handoff`.
        dataset_contract_json: the approved `dataset_contract.json`.
        contract_version: the gate-verified contract version — carried as
            metadata only (§G.0); Crew 2 does not re-verify the gate.
        handoff_status: injected pipeline metadata (§G.0) — e.g.
            `"gate_passed"`. Never the validation report itself.
        workspace: if given, every Crew 2 artifact is written under this
            directory instead of the real `artifacts/crew2/` tree (used by
            mocked/offline tests). Defaults to `None`, meaning the real
            `artifacts/crew2/` paths from `io_paths.py`.
    """
    if workspace is not None:
        crew2_dir = Path(workspace)
        features_csv = crew2_dir / "features.csv"
        model_joblib = crew2_dir / "model.joblib"
        experiments_json = crew2_dir / "experiments.json"
        evaluation_report_md = crew2_dir / "evaluation_report.md"
        model_card_md = crew2_dir / "model_card.md"
        internal_dir = crew2_dir / "_internal"
    else:
        features_csv = FEATURES_CSV
        model_joblib = MODEL_JOBLIB
        experiments_json = EXPERIMENTS_JSON
        evaluation_report_md = EVALUATION_REPORT_MD
        model_card_md = MODEL_CARD_MD
        internal_dir = CREW2_INTERNAL

    handoff = Crew2Handoff(build_crew2_handoff(clean_data_csv, dataset_contract_json, actor="crew2"))

    ctx = Crew2RunContext(
        run_id=run_id,
        handoff=handoff,
        handoff_status=handoff_status,
        contract_version=contract_version,
        validation_warnings=validation_warnings,
        features_csv=features_csv,
        model_joblib=model_joblib,
        experiments_json=experiments_json,
        evaluation_report_md=evaluation_report_md,
        model_card_md=model_card_md,
        internal_dir=internal_dir,
    )

    crew = build_scientist_crew(ctx, llm=llm)

    with crew2_run_context(ctx):
        try:
            crew.kickoff()
            ctx.status = "completed"
        except Exception as exc:  # noqa: BLE001 — turn a raised exception into a reported halt, never a crash
            ctx.status = "halted_agent_failure"
            ctx.failure_category = "halted_agent_failure"
            ctx.failure_message = str(exc)

            ctx.internal_dir.mkdir(parents=True, exist_ok=True)
            if ctx.feature_plan is None and ctx.last_rejected_feature_plan_raw is not None:
                (ctx.internal_dir / "rejected_feature_plan.json").write_text(
                    ctx.last_rejected_feature_plan_raw, encoding="utf-8"
                )
            if ctx.experiment_plan is None and ctx.last_rejected_experiment_plan_raw is not None:
                (ctx.internal_dir / "rejected_experiment_plan.json").write_text(
                    ctx.last_rejected_experiment_plan_raw, encoding="utf-8"
                )

        return Crew2Result(ctx)
