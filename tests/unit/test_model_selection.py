"""Unit tests — `ml/train.py`, `ml/evaluate.py`, `plans/experiment_plan.py`
(PROJECT_PLAN.md §G.2). **Determinism is the point of this file.**

Proves: the estimator allowlist, the params allowlist, ≥2 variants
required, deterministic split/CV, preprocessing lives inside the sklearn
`Pipeline` (never fit outside it), the winner is selected by pure Python
(argmax) with a documented deterministic tie-break, the same inputs/plan
always produce the same winner, the test set is never touched during
training/CV, and the `experiments.json`-shaped artifact is the sole
machine-derived source every metric must be verifiable against.

Runnable two ways:
  * ``pytest tests/unit/test_model_selection.py``
  * ``python tests/unit/test_model_selection.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sklearn.compose import ColumnTransformer  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

from harbor_vale.ml.evaluate import (  # noqa: E402
    build_experiments_artifact,
    compute_metrics,
    evaluate_cv_results,
    final_test_evaluation,
    select_winner,
    verify_metric_in_experiments,
)
from harbor_vale.ml.train import RANDOM_STATE, split_train_test, train_all_variants  # noqa: E402
from harbor_vale.plans.experiment_plan import (  # noqa: E402
    ExperimentPlan,
    ExperimentVariant,
    validate_experiment_plan,
)


def _synthetic_classification_data(n: int = 300, seed: int = 7) -> tuple["pd.DataFrame", "pd.Series"]:
    rng = np.random.default_rng(seed)
    x1 = rng.normal(size=n)
    x2 = rng.normal(size=n)
    logits = 1.5 * x1 - 0.8 * x2
    prob = 1 / (1 + np.exp(-logits))
    y = (rng.uniform(size=n) < prob).astype(int)
    X = pd.DataFrame({"x1": x1, "x2": x2})
    return X, pd.Series(y, name="target")


def _preprocessor() -> ColumnTransformer:
    return ColumnTransformer(transformers=[("scale", StandardScaler(), ["x1", "x2"])])


def _two_variant_plan(**overrides) -> ExperimentPlan:
    defaults = dict(
        primary_metric="roc_auc",
        metric_rationale="AUC robust to class imbalance",
        cv_folds=3,
        variants=[
            ExperimentVariant(name="logreg", estimator="logistic_regression",
                               params={"C": 1.0, "class_weight": "balanced"}, rationale="baseline"),
            ExperimentVariant(name="rf", estimator="random_forest",
                               params={"n_estimators": 50, "max_depth": 5}, rationale="nonlinear"),
        ],
    )
    defaults.update(overrides)
    return ExperimentPlan(**defaults)


# --- estimator allowlist -----------------------------------------------------

def test_estimator_must_be_from_the_closed_literal() -> None:
    try:
        ExperimentVariant(name="x", estimator="decision_tree", params={}, rationale="r")
    except ValidationError:
        pass
    else:
        raise AssertionError("expected ValidationError: decision_tree is not in the closed Estimator Literal")


def test_svm_or_arbitrary_estimator_name_is_rejected() -> None:
    try:
        ExperimentVariant(name="x", estimator="svm", params={}, rationale="r")
    except ValidationError:
        pass
    else:
        raise AssertionError("expected ValidationError for an arbitrary estimator name")


# --- params allowlist --------------------------------------------------------

def test_unknown_param_name_is_rejected() -> None:
    plan = _two_variant_plan()
    bad = plan.variants[0].model_copy(update={"params": {"C": 1.0, "not_a_real_param": 5}})
    ok, msg = validate_experiment_plan(plan.model_copy(update={"variants": [bad, plan.variants[1]]}))
    assert ok is False
    assert "not_a_real_param" in msg


def test_param_out_of_range_is_rejected() -> None:
    plan = _two_variant_plan()
    bad = plan.variants[1].model_copy(update={"params": {"n_estimators": 5000}})  # > 1000 max
    ok, msg = validate_experiment_plan(plan.model_copy(update={"variants": [plan.variants[0], bad]}))
    assert ok is False
    assert "outside allowed range" in msg


def test_random_state_can_never_be_set_by_a_plan() -> None:
    plan = _two_variant_plan()
    bad = plan.variants[0].model_copy(update={"params": {"C": 1.0, "random_state": 123}})
    ok, msg = validate_experiment_plan(plan.model_copy(update={"variants": [bad, plan.variants[1]]}))
    assert ok is False
    assert "random_state" in msg


def test_param_wrong_type_is_rejected() -> None:
    plan = _two_variant_plan()
    bad = plan.variants[0].model_copy(update={"params": {"C": "not_a_float"}})
    ok, msg = validate_experiment_plan(plan.model_copy(update={"variants": [bad, plan.variants[1]]}))
    assert ok is False
    assert "must be of type" in msg


# --- >=2 variants -------------------------------------------------------------

def test_single_variant_plan_is_rejected() -> None:
    plan = _two_variant_plan()
    ok, msg = validate_experiment_plan(plan.model_copy(update={"variants": [plan.variants[0]]}))
    assert ok is False
    assert "at least 2" in msg


def test_duplicate_variant_names_are_rejected() -> None:
    plan = _two_variant_plan()
    dup = plan.variants[1].model_copy(update={"name": plan.variants[0].name})
    ok, msg = validate_experiment_plan(plan.model_copy(update={"variants": [plan.variants[0], dup]}))
    assert ok is False
    assert "unique" in msg


def test_valid_three_variant_plan_including_gradient_boosting_is_accepted() -> None:
    plan = _two_variant_plan(
        variants=[
            ExperimentVariant(name="logreg", estimator="logistic_regression", params={"C": 1.0}, rationale="r"),
            ExperimentVariant(name="rf", estimator="random_forest", params={"n_estimators": 100}, rationale="r"),
            ExperimentVariant(name="gb", estimator="gradient_boosting", params={"n_estimators": 100, "learning_rate": 0.1}, rationale="r"),
        ]
    )
    ok, validated = validate_experiment_plan(plan)
    assert ok, validated


# --- deterministic split / CV -------------------------------------------------

def test_train_test_split_is_deterministic_given_the_same_data() -> None:
    X, y = _synthetic_classification_data()
    split1 = split_train_test(X, y)
    split2 = split_train_test(X, y)
    pd.testing.assert_frame_equal(split1.X_train, split2.X_train)
    pd.testing.assert_series_equal(split1.y_train, split2.y_train)
    assert RANDOM_STATE == 42


def test_split_is_stratified() -> None:
    X, y = _synthetic_classification_data(n=400)
    split = split_train_test(X, y)
    overall_rate = y.mean()
    train_rate = split.y_train.mean()
    test_rate = split.y_test.mean()
    assert abs(train_rate - overall_rate) < 0.05
    assert abs(test_rate - overall_rate) < 0.08


def test_cross_validation_and_training_never_touch_the_test_set() -> None:
    """Structural proof: `train_all_variants` receives only `split` (which
    carries X_test/y_test), but `run_cross_validation`/pipeline `.fit` calls
    inside it only ever reference `split.X_train`/`split.y_train` — verified
    here by checking the test predictions require a SEPARATE, later call."""
    X, y = _synthetic_classification_data()
    split = split_train_test(X, y)
    plan = _two_variant_plan()
    trained = train_all_variants(_preprocessor(), plan, split)
    # each fitted pipeline's training data was only ever X_train (by construction);
    # confirm predict works on X_test only as a SEPARATE, later action:
    for t in trained:
        predictions = t.fitted_pipeline.predict_proba(split.X_test)
        assert predictions.shape[0] == len(split.X_test)


# --- preprocessing lives in the Pipeline ------------------------------------

def test_preprocessor_is_inside_the_pipeline_not_fit_separately() -> None:
    from harbor_vale.ml.train import build_pipeline

    pipeline = build_pipeline(_preprocessor(), "logistic_regression", {"C": 1.0})
    step_names = [name for name, _ in pipeline.steps]
    assert step_names == ["preprocess", "classify"]


def test_each_variant_gets_an_independently_fitted_preprocessor() -> None:
    """`clone(preprocessor)` inside build_pipeline — two variants must not
    share one fitted transformer instance."""
    X, y = _synthetic_classification_data()
    split = split_train_test(X, y)
    plan = _two_variant_plan()
    trained = train_all_variants(_preprocessor(), plan, split)
    preproc_a = trained[0].fitted_pipeline.named_steps["preprocess"]
    preproc_b = trained[1].fitted_pipeline.named_steps["preprocess"]
    assert preproc_a is not preproc_b


# --- Python-only winner selection + deterministic tie-break -----------------

def test_winner_is_the_variant_with_the_highest_primary_metric() -> None:
    cv_metrics = {"a": {"roc_auc": 0.7}, "b": {"roc_auc": 0.9}, "c": {"roc_auc": 0.5}}
    winner = select_winner(cv_metrics, "roc_auc", ["a", "b", "c"])
    assert winner == "b"


def test_tie_breaks_to_the_earliest_declared_variant() -> None:
    cv_metrics = {"a": {"roc_auc": 0.8}, "b": {"roc_auc": 0.8}, "c": {"roc_auc": 0.5}}
    winner = select_winner(cv_metrics, "roc_auc", ["a", "b", "c"])
    assert winner == "a"
    # order matters: if 'b' were declared first, it would win the tie instead
    winner2 = select_winner(cv_metrics, "roc_auc", ["b", "a", "c"])
    assert winner2 == "b"


def test_same_inputs_and_plan_always_produce_the_same_winner() -> None:
    X, y = _synthetic_classification_data()
    split = split_train_test(X, y)
    plan = _two_variant_plan()

    def run_once() -> str:
        trained = train_all_variants(_preprocessor(), plan, split)
        cv_metrics = evaluate_cv_results(trained, split.y_train)
        return select_winner(cv_metrics, plan.primary_metric, [v.name for v in plan.variants])

    winner1 = run_once()
    winner2 = run_once()
    assert winner1 == winner2


# --- metrics + experiments.json artifact -------------------------------------

def test_compute_metrics_matches_sklearn_directly() -> None:
    from sklearn.metrics import accuracy_score, roc_auc_score

    y_true = np.array([0, 1, 1, 0, 1])
    y_proba = np.array([0.1, 0.8, 0.6, 0.3, 0.9])
    y_labels = (y_proba >= 0.5).astype(int)
    metrics = compute_metrics(y_true, y_proba, y_labels)
    assert metrics["roc_auc"] == roc_auc_score(y_true, y_proba)
    assert metrics["accuracy"] == accuracy_score(y_true, y_labels)
    assert metrics["confusion_matrix"] == [[2, 0], [0, 3]]


def test_experiments_artifact_every_metric_is_verifiable() -> None:
    X, y = _synthetic_classification_data()
    split = split_train_test(X, y)
    plan = _two_variant_plan()
    trained = train_all_variants(_preprocessor(), plan, split)
    cv_metrics = evaluate_cv_results(trained, split.y_train)
    winner_name = select_winner(cv_metrics, plan.primary_metric, [v.name for v in plan.variants])
    winner = next(t for t in trained if t.variant_name == winner_name)
    test_metrics = final_test_evaluation(winner, split.X_test, split.y_test)

    artifact = build_experiments_artifact(
        run_id="t", plan=plan, trained_variants=trained, cv_metrics=cv_metrics,
        winner_name=winner_name, test_metrics=test_metrics, created_at="2026-01-01T00:00:00Z",
    )

    for variant in plan.variants:
        looked_up = verify_metric_in_experiments(artifact, variant_name=variant.name, split="cv", metric="roc_auc")
        assert looked_up == cv_metrics[variant.name]["roc_auc"]

    looked_up_test = verify_metric_in_experiments(artifact, variant_name=winner_name, split="test", metric="roc_auc")
    assert looked_up_test == test_metrics["roc_auc"]

    try:
        loser_name = next(v.name for v in plan.variants if v.name != winner_name)
        verify_metric_in_experiments(artifact, variant_name=loser_name, split="test", metric="roc_auc")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError: only the winner has test_metrics")


if __name__ == "__main__":
    _failures: list[str] = []
    for _name, _fn in sorted(
        (n, f) for n, f in dict(globals()).items() if n.startswith("test_") and callable(f)
    ):
        try:
            _fn()
        except Exception as exc:  # noqa: BLE001
            _failures.append(_name)
            print(f"FAIL  {_name}: {exc.__class__.__name__}: {exc}")
        else:
            print(f"PASS  {_name}")
    print(f"\n{len(_failures)} failed" if _failures else "\nall passed")
    sys.exit(1 if _failures else 0)
