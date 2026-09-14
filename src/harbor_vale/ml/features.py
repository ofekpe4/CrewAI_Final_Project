"""sklearn mechanics behind `tools/feature_tools.build_features()`
(PROJECT_PLAN.md §G.1 point 8: `ColumnTransformer`).

This module is where the actual `sklearn.compose.ColumnTransformer` gets
built from a validated `FeaturePlan` — a closed, deterministic mapping from
the plan's `encoders`/`transforms` vocabulary to real sklearn transformer
instances. No arbitrary transform: every `EncoderKind`/`TransformKind` the
schema allows (`plans/feature_plan.py`) has exactly one sklearn
implementation here, and nothing else is constructible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import (
    FunctionTransformer,
    MinMaxScaler,
    OneHotEncoder,
    OrdinalEncoder,
    StandardScaler,
)

from harbor_vale.plans.feature_plan import DerivedFeatureSpec, FeaturePlan


class FeatureBuildError(ValueError):
    """Raised when a validated `FeaturePlan` still cannot be built against
    the ACTUAL clean data — e.g. a categorical `use_features` column with
    no declared encoder (a genuine plan gap the contract-cross-validation
    guardrail does not check, since it is about column existence/exclusion
    rules, not about "is every non-numeric feature encoded"). Never an
    arbitrary Python error — always a specific, named condition.
    """


def compute_derived_features(df: "pd.DataFrame", derived: list[DerivedFeatureSpec]) -> "pd.DataFrame":
    """Return a COPY of `df` with every `derived` column added.

    The only implemented `DerivedFeatureKind` is `"ratio"`
    (`numerator / denominator`), computed safely: a zero denominator is
    replaced with `1` before dividing (never `0/0` -> `NaN`, never a
    `ZeroDivisionError`/`inf`) — deterministic and documented, not a silent
    edge case. `df` itself is never mutated.
    """
    result = df.copy(deep=True)
    for spec in derived:
        if spec.kind == "ratio":
            denominator = result[spec.denominator].replace(0, 1)
            result[spec.name] = result[spec.numerator] / denominator
        else:  # pragma: no cover — FeaturePlan's DerivedFeatureKind is closed to "ratio"
            raise FeatureBuildError(f"unsupported derived feature kind: {spec.kind!r}")
    return result


def _column_dtype_is_numeric(series: "pd.Series") -> bool:
    return bool(pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series))


_TRANSFORM_FACTORIES = {
    "log1p": lambda: FunctionTransformer(np.log1p, feature_names_out="one-to-one"),
    "standard_scale": StandardScaler,
    "minmax_scale": MinMaxScaler,
}

_ENCODER_FACTORIES = {
    "onehot": lambda: OneHotEncoder(handle_unknown="ignore"),
    "ordinal": lambda: OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
}


def build_preprocessor(
    plan: FeaturePlan, df_with_derived: "pd.DataFrame"
) -> tuple[ColumnTransformer, list[str]]:
    """Build the `ColumnTransformer` for `plan`, and return the deterministic
    ordered list of feature-column names it will consume as input (the
    order this function iterates the plan in — used by
    `tools/feature_tools.build_features` to slice the input DataFrame in
    the exact same order the transformer expects).

    Every feature named in `plan.use_features`/`plan.derived` is placed into
    exactly one of three groups, in this deterministic order:

    1. **Encoded** — has a declared `EncoderSpec` (categorical).
    2. **Transformed** — has a declared `TransformSpec` (numeric), applied
       then left as a single numeric output column.
    3. **Passthrough numeric** — no declared encoder/transform; must be a
       genuinely numeric column in the data, and gets a default
       `StandardScaler` (a defensible, standard default — never left raw
       next to scaled/encoded columns, which would bias distance/gradient-
       based estimators).

    A non-numeric `use_features`/`derived` column with no declared encoder
    is a `FeatureBuildError` — the plan must explicitly decide how to
    encode every categorical feature it uses; nothing here silently guesses.
    """
    encoded_columns = {e.column: e.kind for e in plan.encoders}
    transformed_columns = {t.column: t.kind for t in plan.transforms}
    all_feature_names = list(plan.use_features) + [d.name for d in plan.derived]

    transformers: list[tuple[str, object, list[str]]] = []
    passthrough_numeric: list[str] = []

    for name in all_feature_names:
        if name not in df_with_derived.columns:
            raise FeatureBuildError(f"feature {name!r} is not present in the data")
        if name in encoded_columns:
            kind = encoded_columns[name]
            transformers.append((f"encode_{name}", _ENCODER_FACTORIES[kind](), [name]))
        elif name in transformed_columns:
            kind = transformed_columns[name]
            transformers.append((f"transform_{name}", _TRANSFORM_FACTORIES[kind](), [name]))
        else:
            if not _column_dtype_is_numeric(df_with_derived[name]):
                raise FeatureBuildError(
                    f"feature {name!r} is not numeric and has no declared encoder in the "
                    "FeaturePlan — every categorical feature must have an explicit encoder"
                )
            passthrough_numeric.append(name)

    if passthrough_numeric:
        transformers.append(("scale_passthrough", StandardScaler(), passthrough_numeric))

    preprocessor = ColumnTransformer(transformers=transformers, remainder="drop")
    return preprocessor, all_feature_names
