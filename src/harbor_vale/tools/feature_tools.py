"""`build_features()` — the Feature Engineer's execution tool (PROJECT_PLAN.md
§G.1 point 8: "`callback` → `feature_tools.build_features()` → `ColumnTransformer`
→ `features.csv`").

Consumes: the approved `clean_data.csv` (already loaded as a DataFrame),
a validated `DatasetContract`, and an already-`validate_feature_plan`-approved
`FeaturePlan`. Produces: a raw (not-yet-preprocessed) feature `DataFrame`,
the target `Series`, and an UNFITTED `sklearn.compose.ColumnTransformer` —
deliberately unfitted, so `ml/train.py` can fit the whole
`Pipeline(preprocessor, estimator)` only on the training split (§G.2's
"אפס דליפה בין folds" — zero leakage between CV folds, and by the same
logic, zero leakage from the held-out test set either).

An agent never sees this module's output directly — it is what a
CrewAI `callback` (Phase 6+) invokes after the guardrail approves a
`FeaturePlan`. This function itself has no CrewAI dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.compose import ColumnTransformer

from harbor_vale.contract.schema import DatasetContract, EnforcementLevel
from harbor_vale.ml.features import FeatureBuildError, build_preprocessor, compute_derived_features
from harbor_vale.plans.feature_plan import FeaturePlan


@dataclass(frozen=True)
class FeatureBuildResult:
    """The Feature Engineer's tool output — everything `ml/train.py` needs,
    with the target already correctly separated and the preprocessor left
    unfitted (see module docstring)."""

    X: "pd.DataFrame"
    """Raw (pre-`ColumnTransformer`) feature columns — `use_features` plus
    any `derived` columns, in the plan's deterministic order. The target
    column is never present here."""

    y: "pd.Series"
    preprocessor: ColumnTransformer
    """Unfitted. Fit it only on a training split — never on `X` as a whole."""

    feature_names: list[str]
    """The deterministic order `preprocessor` expects its input columns in."""


def build_features(
    clean_df: "pd.DataFrame", contract: DatasetContract, plan: FeaturePlan
) -> FeatureBuildResult:
    """Build model-ready features from `clean_df` per `plan` — mechanically
    re-checked against `contract`, in addition to whatever
    `validate_feature_plan` already checked at guardrail time (defense in
    depth, matching this project's practice everywhere else a validated
    plan is executed — e.g. `contract/builder.py`, `tools/cleaning_tools.py`).

    Raises `FeatureBuildError` for any condition that can only be
    discovered against the real data (a non-numeric feature with no
    encoder — see `ml/features.build_preprocessor`) or that re-confirms an
    invariant the guardrail already enforced (a hard-excluded feature in
    `use_features`, the target appearing as a feature).
    """
    target_name = contract.target.name
    hard_excluded = {
        f.name for f in contract.excluded_features if f.enforcement == EnforcementLevel.HARD
    }

    if target_name in plan.use_features:
        raise FeatureBuildError(f"target {target_name!r} must never appear in use_features")
    hard_used = [c for c in plan.use_features if c in hard_excluded]
    if hard_used:
        raise FeatureBuildError(f"use_features includes hard-excluded feature(s): {hard_used}")
    if target_name not in clean_df.columns:
        raise FeatureBuildError(f"target {target_name!r} is not present in the candidate data")

    missing_source_columns = [c for c in plan.use_features if c not in clean_df.columns]
    if missing_source_columns:
        raise FeatureBuildError(f"use_features references column(s) not in the data: {missing_source_columns}")

    df_with_derived = compute_derived_features(clean_df, plan.derived)
    preprocessor, feature_names = build_preprocessor(plan, df_with_derived)

    X = df_with_derived[feature_names].copy(deep=True)
    y = df_with_derived[target_name].copy(deep=True)

    return FeatureBuildResult(X=X, y=y, preprocessor=preprocessor, feature_names=feature_names)
