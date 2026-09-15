"""Crew 1's `Task.callback` functions (PROJECT_PLAN.md §D.1/§D.2/§D.3 point 8,
Phase 6 Internal Gates 6.1-6.4).

**Every function here is a plain, module-level, synchronous function** —
required by `Task.callback`'s `SerializableCallable` typing
(docs/architecture.md §7; see `runtime.py`'s docstring for the full
explanation). Each one calls `runtime.get_active_context()` first, then
performs ONLY deterministic Python work — no LLM call, no judgement.

**Ordering guarantee this design relies on** (docs/architecture.md §7,
verified against `crewai==1.15.20`): a Task's callback runs synchronously,
blocks the crew loop, and fully finishes before the next Task's agent
starts. So `execute_cleaning_and_profile` (Task 1) is guaranteed to have
written `clean_data.csv` and populated every `ctx.eda_*`/`ctx.clean_*` field
before Agent 2 ever runs; `render_eda_and_insights` (Task 2) is guaranteed
to have written `eda_report.html`/`insights.md` before Agent 3 ever runs.

**By the time any of these functions runs, its Task's guardrail has already
returned success** (docs/architecture.md §7: "callback is called after the
guardrail loop") — a guardrail that never succeeds raises a plain
`Exception` instead, which propagates out of `crew.kickoff()` and this
callback never executes at all. So `ctx.cleaning_plan`/`ctx.contract_draft`
are guaranteed non-`None` here for Tasks 1/3; Task 2's callback is the one
exception, since its guardrail can force an *accepted-but-degraded* result
(see `guardrails.py`) — `render_eda_and_insights` checks `ctx.eda_degraded`
explicitly rather than assuming `ctx.insights_doc` is set.

**A callback that raises propagates the original exception out of
`kickoff()`, halting the crew** (docs/architecture.md §7/§12) — exactly the
critical-agent policy this project wants for Tasks 1 and 3 (§D.1/§D.3 point
9: "propagate the error and halt. Never silently continue."). Neither
callback below catches its own deterministic-executor errors.
"""

from harbor_vale.contract.builder import build_contract
from harbor_vale.crews.analyst_crew.runtime import get_active_context
from harbor_vale.tools.cleaning_tools import execute_plan
from harbor_vale.tools.eda_tools import (
    compute_eda_stats,
    generate_numeric_distribution_figure,
    generate_target_rate_figure,
    render_eda_report_html,
    render_insights_markdown,
)
from harbor_vale.tools.profiling_tools import profile_dataframe

# The Telco-specific target/column names this Crew 1 build is grounded in
# (data/README.md §6.5's canonical mapping — the same one
# `tests/fixtures/hardcoded_plans.py`/`build_example_contract.py` already
# use). `_TARGET_COLUMN` is a hard requirement the task description states
# explicitly (§config/tasks.yaml), so it is safe to assume literally. The
# other two are only PREFERRED names — the Inspector agent is free to
# rename (or not rename) every other column however it judges best (§D.1:
# "renaming ... to clear snake_case names" is guidance, not a hard
# requirement), so figure selection below resolves them case/underscore-
# insensitively against whatever the agent actually produced, with a
# measured (never agent-declared) fallback if neither name is present at
# all — Run 1 of Phase 6's live acceptance run (working flow session 23)
# is the concrete evidence this fallback exists to cover: the agent left
# most columns in their original raw casing, and a literal-name-only match
# would have silently produced zero figures.
_TARGET_COLUMN = "churn"
# Each inner tuple is one figure "slot": synonyms for both the canonical
# renamed name AND the raw Telco source name (data/README.md §6.5), since
# the agent may produce either — or, per the Run 1 evidence above, neither
# consistently.
_TARGET_RATE_FIGURE_CANDIDATES = (("contract_type", "contract"), ("payment_method",))
_DISTRIBUTION_FIGURE_CANDIDATES = ("monthly_charges",)
_MAX_TARGET_RATE_FIGURES = 2
_FALLBACK_CATEGORY_MIN_LEVELS = 2
_FALLBACK_CATEGORY_MAX_LEVELS = 10


def _normalize(name: str) -> str:
    return name.strip().lower().replace(" ", "").replace("_", "")


def _resolve_column(columns, *candidates: str) -> "str | None":
    """Case/underscore/space-insensitive lookup: the Inspector agent may
    rename `PaymentMethod` to `payment_method`, leave it as `PaymentMethod`,
    or something else entirely — this matches any of those against a
    canonical candidate name. Returns the REAL column name (as it actually
    exists in `columns`), never the candidate string itself."""
    normalized_lookup = {_normalize(c): c for c in columns}
    for candidate in candidates:
        match = normalized_lookup.get(_normalize(candidate))
        if match is not None:
            return match
    return None


def _fallback_target_rate_columns(profile, target_column: str, already_chosen: set, limit: int) -> list[str]:
    """Deterministic, measured fallback when neither preferred candidate
    name exists: the first `limit` categorical columns (excluding the
    target and anything already chosen) whose measured cardinality is
    low enough for a legible target-rate-by-category bar chart."""
    picks: list[str] = []
    for col in profile.columns:
        if len(picks) >= limit:
            break
        if col.name == target_column or col.name in already_chosen or col.is_numeric:
            continue
        if _FALLBACK_CATEGORY_MIN_LEVELS <= col.unique_count <= _FALLBACK_CATEGORY_MAX_LEVELS:
            picks.append(col.name)
    return picks


def _fallback_distribution_column(profile, target_column: str) -> "str | None":
    """Deterministic, measured fallback: the numeric column (excluding the
    target) with the largest measured standard deviation — the most
    visually informative distribution among what was actually measured,
    never an agent-declared choice."""
    best_name: "str | None" = None
    best_std = -1.0
    for col in profile.columns:
        if col.name == target_column or not col.is_numeric or col.std is None:
            continue
        if col.std > best_std:
            best_std = col.std
            best_name = col.name
    return best_name


def execute_cleaning_and_profile(task_output) -> None:  # noqa: ARG001 — CrewAI calls this with the TaskOutput; state lives on ctx
    """Task 1 (Data Quality Inspector) callback — CRITICAL (§D.1 point 8).

    1. Persists the accepted `CleaningPlan` under `_internal/` (debug trail).
    2. Executes it via `cleaning_tools.execute_plan` -> `clean_data.csv`.
    3. Builds the clean-data profile downstream Tasks need.
    4. Computes deterministic EDA statistics/figures so Task 2's guardrail
       has a real `eda_stats` dict to validate `evidence_stat_key` against,
       and Task 2's tools have something real to read.
    """
    ctx = get_active_context()
    if ctx.cleaning_plan is None:  # pragma: no cover — guarded by CrewAI's own guardrail-then-callback ordering
        raise RuntimeError("execute_cleaning_and_profile: ctx.cleaning_plan is None — guardrail did not run first")

    ctx.internal_dir.mkdir(parents=True, exist_ok=True)
    (ctx.internal_dir / "cleaning_plan.json").write_text(
        ctx.cleaning_plan.model_dump_json(indent=2), encoding="utf-8"
    )

    clean_df = execute_plan(ctx.raw_df, ctx.cleaning_plan)
    ctx.clean_data_csv.parent.mkdir(parents=True, exist_ok=True)
    clean_df.to_csv(ctx.clean_data_csv, index=False)
    ctx.clean_df = clean_df
    ctx.clean_columns = set(clean_df.columns)

    ctx.clean_profile = profile_dataframe(clean_df, target_column=_TARGET_COLUMN)
    ctx.eda_stats = compute_eda_stats(clean_df, target_column=_TARGET_COLUMN)

    figure_paths = []
    if _TARGET_COLUMN in clean_df.columns:
        target_rate_columns = [
            col for col in (_resolve_column(clean_df.columns, *slot) for slot in _TARGET_RATE_FIGURE_CANDIDATES)
            if col is not None
        ]
        if not target_rate_columns:
            target_rate_columns = _fallback_target_rate_columns(
                ctx.clean_profile, _TARGET_COLUMN, set(), _MAX_TARGET_RATE_FIGURES
            )
        for column in target_rate_columns[:_MAX_TARGET_RATE_FIGURES]:
            figure_paths.append(
                generate_target_rate_figure(
                    clean_df, column=column, target_column=_TARGET_COLUMN, out_dir=ctx.figures_dir
                )
            )

    distribution_column = _resolve_column(clean_df.columns, *_DISTRIBUTION_FIGURE_CANDIDATES)
    if distribution_column is None:
        distribution_column = _fallback_distribution_column(ctx.clean_profile, _TARGET_COLUMN)
    if distribution_column is not None:
        figure_paths.append(
            generate_numeric_distribution_figure(clean_df, column=distribution_column, out_dir=ctx.figures_dir)
        )
    ctx.figure_relpaths = [f"figures/{p.name}" for p in figure_paths]


def render_eda_and_insights(task_output) -> None:  # noqa: ARG001
    """Task 2 (EDA & Insights Analyst) callback — NARRATIVE, visible fallback
    (§D.2 point 8/9). Renders from `ctx`, never from `task_output` — see the
    module docstring and `guardrails.py`'s docstring for why."""
    ctx = get_active_context()
    if ctx.eda_stats is None:  # pragma: no cover — guarded by Task ordering
        raise RuntimeError("render_eda_and_insights: ctx.eda_stats is None — Task 1's callback did not run first")

    degraded_reason = ctx.eda_degraded_reason if ctx.eda_degraded else None
    insights = None if ctx.eda_degraded else ctx.insights_doc

    render_eda_report_html(
        dataset_name=ctx.dataset_name,
        stats=ctx.eda_stats,
        figures=list(ctx.figure_relpaths),
        insights=insights,
        out_path=ctx.eda_report_html,
        degraded_reason=degraded_reason,
    )
    render_insights_markdown(
        dataset_name=ctx.dataset_name,
        insights=insights,
        out_path=ctx.insights_md,
        degraded_reason=degraded_reason,
    )


def build_final_contract(task_output) -> None:  # noqa: ARG001
    """Task 3 (Data Contract Architect) callback — CRITICAL (§D.3 point 8).

    The agent never writes `dataset_contract.json` itself — this callback is
    the ONLY production path that does, merging the validated `ContractDraft`
    with measured facts from the real `clean_data.csv` via
    `contract/builder.build_contract` (dtypes, observed stats, SHA256,
    row/column counts — nothing here is agent-declared).
    """
    ctx = get_active_context()
    if ctx.contract_draft is None:  # pragma: no cover — guarded by CrewAI's own guardrail-then-callback ordering
        raise RuntimeError("build_final_contract: ctx.contract_draft is None — guardrail did not run first")

    contract = build_contract(
        ctx.contract_draft,
        ctx.clean_data_csv,
        contract_version="1.0.0",
        run_id=ctx.run_id,
        created_by="crew1.contract_architect",
        dataset_name=ctx.dataset_name,
        source_documentation_url=ctx.source_documentation_url,
    )
    ctx.dataset_contract_json.parent.mkdir(parents=True, exist_ok=True)
    ctx.dataset_contract_json.write_text(contract.model_dump_json(indent=2), encoding="utf-8")
    ctx.final_contract = contract
