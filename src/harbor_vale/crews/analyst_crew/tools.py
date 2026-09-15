"""Crew 1's thin CrewAI tool wrappers (PROJECT_PLAN.md §D.1/§D.2/§D.3 point 3,
Phase 6 Internal Gate 6.5).

**Every function here is a thin wrapper around an already-tested Phase 5
deterministic function.** No business logic is reimplemented — each tool
either (a) returns a JSON-safe view of data already measured/computed and
cached on the active `Crew1RunContext`, or (b) calls straight through to a
`tools.profiling_tools` / `tools.eda_tools` function with the run's own
DataFrame, never an agent-supplied path.

**No arbitrary path input anywhere.** Every tool is either zero-argument
(reads the run-bound context) or takes a small, bounded, non-path parameter
(`n: int` for a preview size). This is the "run-bound tools / closures"
design PROJECT_PLAN.md's Phase 6 Gate 6.1 asks for — the agent never
chooses a filesystem path.
"""

from typing import Any

from crewai.tools import tool

from harbor_vale.crews.analyst_crew.runtime import get_active_context
from harbor_vale.tools.eda_tools import compute_numeric_correlations
from harbor_vale.tools.profiling_tools import preview_sample

_PREVIEW_MAX_ROWS = 50  # hard cap — never let an agent request an unbounded preview


# ---------------------------------------------------------------------------
# Agent 1 — Data Quality Inspector: read-only access to the RAW profile.
# ---------------------------------------------------------------------------


@tool("profile_dataset")
def profile_dataset() -> dict[str, Any]:
    """Return the deterministic profile of the raw dataset for this run:
    per-column dtype, null/blank counts, min/max/mean/median for numeric
    columns, and top values for categorical columns. Measured by Python
    (`tools.profiling_tools.profile_dataframe`) — never invented."""
    ctx = get_active_context()
    return ctx.raw_profile.model_dump()


@tool("preview_sample")
def preview_sample_tool(n: int = 20) -> list[dict[str, Any]]:
    """Return the first `n` rows (capped at 50) of the raw dataset as JSON
    records, so you can see real example values alongside the profile."""
    ctx = get_active_context()
    bounded_n = max(1, min(int(n), _PREVIEW_MAX_ROWS))
    return preview_sample(ctx.raw_df, n=bounded_n)


# ---------------------------------------------------------------------------
# Agent 2 — EDA & Insights Analyst: read-only access to MEASURED EDA
# evidence. The statistics/figures were already computed once, deterministically,
# by Task 1's callback (`callbacks.execute_cleaning_and_profile`) — these
# tools expose that single cached computation; they do not recompute it, so
# there is exactly one source of truth an evidence_stat_key can ever be
# checked against (the same dict the guardrail validates against).
# ---------------------------------------------------------------------------


@tool("get_eda_statistics")
def get_eda_statistics() -> dict[str, Any]:
    """Return the deterministic EDA statistics dict for the cleaned dataset
    — per-column count/mean/median/std/min/max for numeric columns,
    unique_count for categorical columns, and (where the target is binary)
    target rate broken down by category. Every `evidence_stat_key` you cite
    in your `InsightsDoc` MUST be a real key in this dictionary — an
    invented key is mechanically rejected."""
    ctx = get_active_context()
    if ctx.eda_stats is None:
        raise RuntimeError("eda_stats not yet computed — this tool was called before Task 1's callback ran")
    return ctx.eda_stats


@tool("get_numeric_correlations")
def get_numeric_correlations() -> dict[str, float]:
    """Return pairwise Pearson correlations between numeric columns of the
    cleaned dataset, keyed `"<col_a>__vs__<col_b>"` — only pairs with a
    defined (non-NaN) correlation are included."""
    ctx = get_active_context()
    if ctx.numeric_correlations is None:
        if ctx.clean_df is None:
            raise RuntimeError("clean_df not yet available — this tool was called before Task 1's callback ran")
        ctx.numeric_correlations = compute_numeric_correlations(ctx.clean_df)
    return ctx.numeric_correlations


@tool("list_eda_figures")
def list_eda_figures() -> list[str]:
    """Return the relative paths of the deterministic EDA figures already
    generated for this run (target-rate-by-category bar charts, a numeric
    distribution histogram) — for reference only; you do not draw figures
    yourself."""
    ctx = get_active_context()
    return list(ctx.figure_relpaths)


# ---------------------------------------------------------------------------
# Agent 3 — Data Contract Architect: read-only access to the CLEAN profile,
# Crew 1's own already-rendered `insights.md`, and curated dataset source
# documentation (evidence for unit/leakage claims — §D.3 point 3).
# ---------------------------------------------------------------------------

@tool("profile_clean_dataset")
def profile_clean_dataset() -> dict[str, Any]:
    """Return the deterministic profile of the CLEANED dataset for this run
    — the same shape as `profile_dataset`, but measured after Task 1's
    cleaning executed. Use this, not the raw profile, to ground every
    semantic judgement in `ContractDraft`."""
    ctx = get_active_context()
    if ctx.clean_profile is None:
        raise RuntimeError("clean_profile not yet available — this tool was called before Task 1's callback ran")
    return ctx.clean_profile.model_dump()


@tool("read_insights_report")
def read_insights_report() -> str:
    """Read back Crew 1's own already-rendered `insights.md` for this run
    (the EDA & Insights Analyst's validated interpretation, or its visible
    degraded-fallback banner) — the ONLY Crew 1 narrative artifact this
    tool exposes. Zero-argument, run-bound: there is no path parameter to
    choose (§G.0's "no unconstrained arbitrary path input" principle,
    applied even before the actual Crew 1 -> Crew 2 handoff boundary
    exists), so ground contract semantics (e.g. which features the
    business already cares about) in the prior agent's interpretation."""
    ctx = get_active_context()
    if not ctx.insights_md.is_file():
        raise RuntimeError("insights.md not yet written — this tool was called before Task 2's callback ran")
    return ctx.insights_md.read_text(encoding="utf-8")


@tool("read_source_documentation")
def read_source_documentation() -> str:
    """Return the dataset's curated source documentation (`data/README.md`
    §6-11: per-column semantic evidence, measured data-quality issues, the
    scale-sensitive column, closed-domain categorical candidates, known
    assumptions, and explicitly-unknown facts such as currency). Use this as
    your EVIDENCE for any `unit`/`closed_domain`/`business_range` claim —
    never declare a unit or a closed domain without pointing to something
    here (or to the measured profile)."""
    ctx = get_active_context()
    return ctx.source_documentation_excerpt
