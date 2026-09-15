"""Crew 2's thin CrewAI tool wrappers (PROJECT_PLAN.md §G.0, §G.1/§G.2/§G.3
point 3, Phase 7 Internal Gates 7.1-7.3).

**`read_handoff` is the ONLY way any Crew 2 agent reaches Crew 1 output.**
Its `name` parameter is annotated with the `Literal[...]` INLINED directly
in the signature — never via a module-level named alias — per
`docs/architecture.md`'s Finding 3 (a named `Literal` alias fails CrewAI's
dynamic per-tool Pydantic model construction with
`PydanticUndefinedAnnotation`; inlining it is one of the two proven fixes).
For the same reason this module carries **no**
`from __future__ import annotations` — a stringized annotation compounds the
same resolution gap.

Every other tool here is either zero-argument (reads state already cached on
the active `Crew2RunContext`) or a thin wrapper with no path parameter
whatsoever — the "no unconstrained arbitrary path input" principle §G.0
establishes and Crew 1's own `tools.py` already follows.
"""

import io
from typing import Any, Literal

import pandas as pd
from crewai.tools import tool

from harbor_vale.contract.schema import DatasetContract
from harbor_vale.crews.scientist_crew.runtime import Crew2RunContext, get_active_context
from harbor_vale.tools.modeling_tools import get_experiment_results as _read_experiment_results_file
from harbor_vale.tools.modeling_tools import read_feature_plan as _read_feature_plan_file
from harbor_vale.tools.profiling_tools import profile_dataframe


# ---------------------------------------------------------------------------
# Loaders — every one reaches Crew 1 data EXCLUSIVELY through
# ctx.handoff.read_handoff(name), never a filesystem shortcut. Cached on the
# context so repeated calls (by different agents/tools) parse the same bytes
# exactly once.
# ---------------------------------------------------------------------------


def ensure_contract_loaded(ctx: Crew2RunContext) -> DatasetContract:
    """Return `ctx.contract`, loading it via the allowlisted handoff on
    first use. This is the ONE place Crew 2 ever parses
    `dataset_contract.json` — guardrails and tools both call this, so there
    is exactly one loader to audit."""
    if ctx.contract is None:
        raw = ctx.handoff.read_handoff("dataset_contract")
        ctx.contract = DatasetContract.model_validate_json(raw)
    return ctx.contract


def ensure_clean_df_loaded(ctx: Crew2RunContext) -> "pd.DataFrame":
    """Return `ctx.clean_df`, loading it via the allowlisted handoff on
    first use — the ONE place Crew 2 ever parses `clean_data.csv`."""
    if ctx.clean_df is None:
        raw = ctx.handoff.read_handoff("clean_data")
        ctx.clean_df = pd.read_csv(io.StringIO(raw))
    return ctx.clean_df


# ---------------------------------------------------------------------------
# Agent 4/5/6 shared tool — the approved two-file handoff, logical names only.
# ---------------------------------------------------------------------------


@tool("read_handoff")
def read_handoff(name: Literal["clean_data", "dataset_contract"]) -> str:
    """Read one of Crew 1's approved handoff files by LOGICAL NAME.
    `name` must be exactly `clean_data` or `dataset_contract` — there is no
    path parameter, and no other value is a valid input to this tool. This
    is the ONLY way to reach Crew 1 output; raw data, Crew 1 internals,
    `insights.md`, and `eda_report.html` are never reachable through this or
    any other Crew 2 tool."""
    ctx = get_active_context()
    return ctx.handoff.read_handoff(name)


@tool("profile_handoff_data")
def profile_handoff_data() -> dict[str, Any]:
    """Return the deterministic profile of the approved `clean_data.csv`
    (per-column dtype, null/unique counts, min/max/mean/median for numeric
    columns) — measured by Python from the SAME bytes `read_handoff`
    exposes, never invented. Use this to ground every feature/transform
    decision in real, measured statistics."""
    ctx = get_active_context()
    contract = ensure_contract_loaded(ctx)
    clean_df = ensure_clean_df_loaded(ctx)
    if ctx.clean_profile is None:
        ctx.clean_profile = profile_dataframe(clean_df, target_column=contract.target.name)
    return ctx.clean_profile.model_dump()


# ---------------------------------------------------------------------------
# Agent 5/6 — read Crew 2's OWN already-written artifacts (never a Crew 1
# internal, never the raw dataset). Zero-argument, run-bound.
# ---------------------------------------------------------------------------


@tool("read_feature_plan")
def read_feature_plan() -> dict[str, Any]:
    """Return the FeaturePlan Crew 2's own Feature Engineer step already
    produced and validated this run (its own artifact, not a Crew 1
    internal) — as a plain JSON-safe dict."""
    ctx = get_active_context()
    if ctx.internal_dir is None or not (ctx.internal_dir / "feature_plan.json").is_file():
        raise RuntimeError("feature_plan.json not yet written — this tool was called before Task 1's callback ran")
    return _read_feature_plan_file(ctx.internal_dir / "feature_plan.json").model_dump()


@tool("read_experiment_results")
def read_experiment_results() -> dict[str, Any]:
    """Return the `experiments.json`-shaped machine-measured results Crew
    2's own Modeling & Experimentation step already produced this run —
    every metric here is real, computed by `ml/evaluate.py`, never agent-
    declared."""
    ctx = get_active_context()
    if not ctx.experiments_json.is_file():
        raise RuntimeError("experiments.json not yet written — this tool was called before Task 2's callback ran")
    return _read_experiment_results_file(ctx.experiments_json)
