"""Crew 1 — the Data Analyst Crew (PROJECT_PLAN.md §D, §C.2.2 Pattern A,
Phase 6 Internal Gates 6.1-6.4).

**Exactly one CrewAI `Crew`, three `Agent`s, three `Task`s,
`Process.sequential`** — the Pattern A structure the Phase 1 spike proved
(`docs/architecture.md`). `build_analyst_crew` constructs it; `run_analyst_crew`
is the one production entry point that wires a `Crew1RunContext`, calls
`crew.kickoff()`, and turns CrewAI's own success/exception outcome into a
`Crew1Result` — never a Phase 8 `PipelineState`/`Flow` (explicitly out of
scope this phase).

**"Agent plans, Python executes."** No line in this module mutates a
DataFrame, writes a production artifact, or decides PASS/FAIL of anything —
that is entirely `callbacks.py` (deterministic) and `contract/validator.py`
(Phase 4, invoked separately as the acceptance gate, not from inside Crew 1
itself — PROJECT_PLAN.md §F.0: the gate is a layer AFTER Crew 1, not part of
it).
"""

from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from crewai import LLM, Agent, Crew, Process, Task

from config.llm import LLMConfig, load_llm_config
from harbor_vale.crews.analyst_crew.callbacks import (
    build_final_contract,
    execute_cleaning_and_profile,
    render_eda_and_insights,
)
from harbor_vale.crews.analyst_crew.guardrails import (
    GUARDRAIL_MAX_RETRIES,
    guardrail_cleaning_plan,
    guardrail_contract_draft,
    guardrail_insights_doc,
)
from harbor_vale.crews.analyst_crew.runtime import Crew1RunContext, crew1_run_context
from harbor_vale.crews.analyst_crew.tools import (
    get_eda_statistics,
    get_numeric_correlations,
    list_eda_figures,
    preview_sample_tool,
    profile_clean_dataset,
    profile_dataset,
    read_insights_report,
    read_source_documentation,
)
from harbor_vale.io_paths import CREW1, CREW1_FIGURES, CREW1_INTERNAL, DATA_README, EDA_REPORT_HTML, HANDOFF_CLEAN_DATA, HANDOFF_CONTRACT, INSIGHTS_MD
from harbor_vale.plans.cleaning_plan import CleaningPlan
from harbor_vale.plans.contract_draft import ContractDraft
from harbor_vale.plans.insights_doc import InsightsDoc
from harbor_vale.tools.profiling_tools import DatasetProfile, profile_dataframe

_CONFIG_DIR = Path(__file__).resolve().parent / "config"
_AGENTS_YAML = _CONFIG_DIR / "agents.yaml"
_TASKS_YAML = _CONFIG_DIR / "tasks.yaml"

RAW_TARGET_COLUMN = "Churn"  # the raw source column name, before Task 1 renames it (data/README.md §6.5)


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _build_llm(config: LLMConfig | None = None) -> LLM:
    """The one, centralized place Crew 1 builds its LLM — every Agent gets
    the identical instance (PROJECT_PLAN.md §L: "config/llm.py הוא המקום
    היחיד שבו LLM מוגדר"). Reads the model/temperature `config/llm.py`
    already resolved from `settings.yaml`; never reads the API key itself
    (litellm/CrewAI read `OPENAI_API_KEY` from the environment at call
    time)."""
    config = config or load_llm_config()
    return LLM(**config.as_crewai_llm_kwargs())


def build_analyst_crew(ctx: Crew1RunContext, *, llm: LLM | None = None) -> Crew:
    """Construct the one Crew 1 `Crew` — 3 agents, 3 tasks, `Process.sequential`.

    Does not call `crew.kickoff()`. `ctx` must already be the active
    `Crew1RunContext` (i.e. this is normally called from inside
    `run_analyst_crew`'s `with crew1_run_context(ctx):` block) — the tools/
    guardrails/callbacks wired onto the returned `Crew` read it via
    `runtime.get_active_context()` when the crew actually runs.
    """
    llm = llm or _build_llm()
    agents_cfg = _load_yaml(_AGENTS_YAML)
    tasks_cfg = _load_yaml(_TASKS_YAML)

    inspector = Agent(
        role=agents_cfg["data_quality_inspector"]["role"].strip(),
        goal=agents_cfg["data_quality_inspector"]["goal"].strip(),
        backstory=agents_cfg["data_quality_inspector"]["backstory"].strip(),
        llm=llm,
        tools=[profile_dataset, preview_sample_tool],
        allow_delegation=False,
        verbose=True,
    )
    analyst = Agent(
        role=agents_cfg["eda_insights_analyst"]["role"].strip(),
        goal=agents_cfg["eda_insights_analyst"]["goal"].strip(),
        backstory=agents_cfg["eda_insights_analyst"]["backstory"].strip(),
        llm=llm,
        tools=[get_eda_statistics, get_numeric_correlations, list_eda_figures],
        allow_delegation=False,
        verbose=True,
    )
    architect = Agent(
        role=agents_cfg["data_contract_architect"]["role"].strip(),
        goal=agents_cfg["data_contract_architect"]["goal"].strip(),
        backstory=agents_cfg["data_contract_architect"]["backstory"].strip(),
        llm=llm,
        tools=[profile_clean_dataset, read_insights_report, read_source_documentation],
        allow_delegation=False,
        verbose=True,
    )

    inspect_task = Task(
        description=tasks_cfg["inspect_cleaning_task"]["description"].strip().format(dataset_name=ctx.dataset_name),
        expected_output=tasks_cfg["inspect_cleaning_task"]["expected_output"].strip(),
        agent=inspector,
        context=[],
        output_pydantic=CleaningPlan,
        guardrail=guardrail_cleaning_plan,
        guardrail_max_retries=GUARDRAIL_MAX_RETRIES,
        callback=execute_cleaning_and_profile,
    )
    eda_task = Task(
        description=tasks_cfg["eda_insights_task"]["description"].strip(),
        expected_output=tasks_cfg["eda_insights_task"]["expected_output"].strip(),
        agent=analyst,
        context=[inspect_task],
        output_pydantic=InsightsDoc,
        guardrail=guardrail_insights_doc,
        guardrail_max_retries=GUARDRAIL_MAX_RETRIES,
        callback=render_eda_and_insights,
    )
    contract_task = Task(
        description=tasks_cfg["contract_architect_task"]["description"].strip(),
        expected_output=tasks_cfg["contract_architect_task"]["expected_output"].strip(),
        agent=architect,
        context=[inspect_task, eda_task],
        output_pydantic=ContractDraft,
        guardrail=guardrail_contract_draft,
        guardrail_max_retries=GUARDRAIL_MAX_RETRIES,
        callback=build_final_contract,
    )

    return Crew(
        agents=[inspector, analyst, architect],
        tasks=[inspect_task, eda_task, contract_task],
        process=Process.sequential,
        verbose=True,
    )


class Crew1Result:
    """The outcome of one `run_analyst_crew` call — a local, Crew-1-scoped
    result object. **Not `PipelineState`** (Phase 8); Phase 8's Flow will
    read fields off this (or an equivalent) to build its own state, not the
    other way around.
    """

    def __init__(self, ctx: Crew1RunContext) -> None:
        self.run_id = ctx.run_id
        self.status: Literal["completed", "halted_agent_failure"] = ctx.status  # type: ignore[assignment]
        self.failure_category = ctx.failure_category
        self.failure_message = ctx.failure_message
        self.eda_degraded = ctx.eda_degraded
        self.eda_degraded_reason = ctx.eda_degraded_reason
        self.clean_data_csv = ctx.clean_data_csv
        self.dataset_contract_json = ctx.dataset_contract_json
        self.eda_report_html = ctx.eda_report_html
        self.insights_md = ctx.insights_md
        self.ctx = ctx

    @property
    def completed(self) -> bool:
        return self.status == "completed"


def run_analyst_crew(
    raw_df: "pd.DataFrame",
    *,
    run_id: str,
    dataset_name: str = "telco_customer_churn",
    source_documentation_url: str = "https://github.com/IBM/telco-customer-churn-on-icp4d",
    business_context: dict | None = None,
    raw_target_column: str = RAW_TARGET_COLUMN,
    workspace: Path | None = None,
    llm: LLM | None = None,
) -> Crew1Result:
    """Run Crew 1 once, end to end, on `raw_df`.

    Args:
        workspace: if given, every Crew 1 artifact is written under this
            directory instead of the real `artifacts/crew1/` tree (used by
            mocked/offline tests so they never touch production paths).
            Defaults to `None`, meaning the real `artifacts/crew1/` paths
            from `io_paths.py`.
    """
    if workspace is not None:
        crew1_dir = Path(workspace)
        clean_data_csv = crew1_dir / "clean_data.csv"
        dataset_contract_json = crew1_dir / "dataset_contract.json"
        eda_report_html = crew1_dir / "eda_report.html"
        insights_md = crew1_dir / "insights.md"
        internal_dir = crew1_dir / "_internal"
        figures_dir = crew1_dir / "figures"
    else:
        clean_data_csv = HANDOFF_CLEAN_DATA
        dataset_contract_json = HANDOFF_CONTRACT
        eda_report_html = EDA_REPORT_HTML
        insights_md = INSIGHTS_MD
        internal_dir = CREW1_INTERNAL
        figures_dir = CREW1_FIGURES

    raw_profile: DatasetProfile = profile_dataframe(raw_df, target_column=raw_target_column)

    ctx = Crew1RunContext(
        run_id=run_id,
        dataset_name=dataset_name,
        source_documentation_url=source_documentation_url,
        business_context=business_context or {},
        source_documentation_excerpt=DATA_README.read_text(encoding="utf-8") if DATA_README.is_file() else "",
        clean_data_csv=clean_data_csv,
        dataset_contract_json=dataset_contract_json,
        eda_report_html=eda_report_html,
        insights_md=insights_md,
        internal_dir=internal_dir,
        figures_dir=figures_dir,
        raw_df=raw_df,
        raw_profile=raw_profile,
    )

    crew = build_analyst_crew(ctx, llm=llm)

    with crew1_run_context(ctx):
        try:
            crew.kickoff()
            ctx.status = "completed"
        except Exception as exc:  # noqa: BLE001 — the whole point: turn a raised exception into a reported halt, never a crash
            ctx.status = "halted_agent_failure"
            ctx.failure_category = "halted_agent_failure"
            ctx.failure_message = str(exc)

            ctx.internal_dir.mkdir(parents=True, exist_ok=True)
            if ctx.cleaning_plan is None and ctx.last_rejected_cleaning_plan_raw is not None:
                (ctx.internal_dir / "rejected_cleaning_plan.json").write_text(
                    ctx.last_rejected_cleaning_plan_raw, encoding="utf-8"
                )
            if ctx.contract_draft is None and ctx.last_rejected_contract_draft_raw is not None:
                (ctx.internal_dir / "rejected_contract_draft.json").write_text(
                    ctx.last_rejected_contract_draft_raw, encoding="utf-8"
                )

        return Crew1Result(ctx)
