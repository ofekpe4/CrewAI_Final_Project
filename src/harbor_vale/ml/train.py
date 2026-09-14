"""Deterministic model training (PROJECT_PLAN.md §G.2: "`callback` →
`ml/train.py` (`random_state=42`) → `ml/evaluate.py` → Python בוחר זוכה").

The approved evaluation protocol, exactly:

- `train_test_split(test_size=0.2, stratify=y, random_state=42)`
- `StratifiedKFold(n_splits=5, shuffle=True, random_state=42)` on the
  train split
- ALL preprocessing lives inside an `sklearn.Pipeline` with the estimator
  — fit only on the training side of every split, zero leakage between CV
  folds and zero leakage from the held-out test set.
- the test set is touched exactly once, at final evaluation
  (`ml/evaluate.py`), never during training or cross-validation.

No hyperparameter tuning, no AutoML, no LLM. `random_state=42` is applied
by this module alone — `plans/experiment_plan.py`'s guardrail explicitly
forbids an agent from setting `random_state` itself (see that module's
docstring).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.base import ClassifierMixin, clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split
from sklearn.pipeline import Pipeline

from harbor_vale.plans.experiment_plan import Estimator, ExperimentPlan, ExperimentVariant

RANDOM_STATE = 42
"""The project's single pinned seed (config/settings.yaml `seeds.python_hash`=0,
`numpy`=42 — this module's `random_state=42` matches the `numpy` seed,
per PROJECT_PLAN.md §G.2's explicit `random_state=42`)."""

TEST_SIZE = 0.2
CV_SPLITS_DEFAULT = 5


_ESTIMATOR_FACTORIES = {
    "logistic_regression": LogisticRegression,
    "random_forest": RandomForestClassifier,
    "gradient_boosting": GradientBoostingClassifier,
}
"""Closed mapping — the exact three §G.2 names, nothing else constructible
from an `ExperimentVariant.estimator` value (the `Literal` in
`plans/experiment_plan.py` already prevents any other string from parsing,
this is the second, executor-side half of that closure)."""


def _build_estimator(estimator: Estimator, params: dict) -> ClassifierMixin:
    """Construct one sklearn estimator instance: `params` (already
    allowlist-validated by `plans/experiment_plan.py`'s guardrail) plus the
    project's own pinned `random_state` — an agent's plan can never supply
    `random_state` itself (the guardrail rejects it), so this is the ONLY
    place a variant's seed is ever set.
    """
    factory = _ESTIMATOR_FACTORIES[estimator]
    return factory(random_state=RANDOM_STATE, **params)


def build_pipeline(preprocessor: ColumnTransformer, estimator: Estimator, params: dict) -> Pipeline:
    """One `Pipeline(preprocessor, estimator)` — preprocessing and the
    classifier fit together, so `Pipeline.fit(X_train, y_train)` (or a
    `cross_val_predict` fold) never lets the fitted preprocessor see data
    outside that specific fold/split. `clone(preprocessor)` so every
    variant/fold gets its own unfitted preprocessor instance, never one
    fitted state accidentally shared and reused across variants.
    """
    return Pipeline(
        steps=[
            ("preprocess", clone(preprocessor)),
            ("classify", _build_estimator(estimator, params)),
        ]
    )


@dataclass(frozen=True)
class SplitData:
    X_train: "pd.DataFrame"
    X_test: "pd.DataFrame"
    y_train: "pd.Series"
    y_test: "pd.Series"


def split_train_test(X: "pd.DataFrame", y: "pd.Series") -> SplitData:
    """§G.2's exact split: `test_size=0.2, stratify=y, random_state=42`.
    Called exactly ONCE per experiment run — the resulting `X_test`/`y_test`
    are then touched only by `ml/evaluate.py`'s final evaluation, never
    during CV."""
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE
    )
    return SplitData(X_train=X_train, X_test=X_test, y_train=y_train, y_test=y_test)


@dataclass(frozen=True)
class CVResult:
    variant_name: str
    estimator: Estimator
    cv_folds: int
    oof_predictions: "np.ndarray"
    """Out-of-fold predicted probabilities for the positive class — each
    training-set row's prediction comes from a fold that never trained on
    that row, so this is leakage-free for computing CV metrics."""
    oof_predicted_labels: "np.ndarray"


def run_cross_validation(
    preprocessor: ColumnTransformer,
    variant: ExperimentVariant,
    X_train: "pd.DataFrame",
    y_train: "pd.Series",
    *,
    cv_folds: int,
) -> CVResult:
    """`StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)`
    on `X_train`/`y_train` only — `X_test`/`y_test` are never referenced
    here. Uses `cross_val_predict` with a fresh `Pipeline` per call, so the
    preprocessor is fit independently within each fold (§G.2: "אפס דליפה
    בין folds")."""
    pipeline = build_pipeline(preprocessor, variant.estimator, variant.params)
    cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=RANDOM_STATE)

    oof_probabilities = cross_val_predict(
        pipeline, X_train, y_train, cv=cv, method="predict_proba"
    )[:, 1]
    oof_labels = (oof_probabilities >= 0.5).astype(int)

    return CVResult(
        variant_name=variant.name,
        estimator=variant.estimator,
        cv_folds=cv_folds,
        oof_predictions=oof_probabilities,
        oof_predicted_labels=oof_labels,
    )


@dataclass(frozen=True)
class TrainedVariant:
    variant_name: str
    estimator: Estimator
    cv_result: CVResult
    fitted_pipeline: Pipeline
    """Fit on the FULL `X_train`/`y_train` (not any single CV fold) —
    this is the pipeline a winning variant's `model.joblib` is saved from,
    after being separately, honestly evaluated once on `X_test`."""


def train_all_variants(
    preprocessor: ColumnTransformer,
    plan: ExperimentPlan,
    split: SplitData,
) -> list[TrainedVariant]:
    """Run cross-validation for every variant in `plan.variants`, then fit
    each variant's pipeline on the full training split (still never
    touching `split.X_test`/`split.y_test`). Returns one `TrainedVariant`
    per plan variant, in the plan's own declared order — deterministic."""
    trained: list[TrainedVariant] = []
    for variant in plan.variants:
        cv_result = run_cross_validation(
            preprocessor, variant, split.X_train, split.y_train, cv_folds=plan.cv_folds
        )
        fitted_pipeline = build_pipeline(preprocessor, variant.estimator, variant.params)
        fitted_pipeline.fit(split.X_train, split.y_train)
        trained.append(
            TrainedVariant(
                variant_name=variant.name,
                estimator=variant.estimator,
                cv_result=cv_result,
                fitted_pipeline=fitted_pipeline,
            )
        )
    return trained
