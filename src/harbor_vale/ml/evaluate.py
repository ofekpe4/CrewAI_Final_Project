"""Deterministic evaluation + Python-only winner selection (PROJECT_PLAN.md
§G.2: "Python בוחר זוכה (argmax)").

Metrics (§G.2, exact set): ROC-AUC (usual primary), PR-AUC, F1, Precision,
Recall, Accuracy, Confusion Matrix. Computed twice, for two different
purposes that must never be confused:

1. **Cross-validation metrics** (`evaluate_cv_results`) — from each
   variant's out-of-fold predictions on the TRAIN split only. Used for
   model SELECTION. The test set is never involved.
2. **Final test evaluation** (`final_test_evaluation`) — the WINNING
   variant only, on the held-out test set, touched exactly once (§G.2).

`select_winner` is pure Python argmax — no LLM, no randomness, a documented
deterministic tie-break. Every number that ends up in `evaluation_report.md`
later (Phase 6+) must be traceable to this module's output
(`build_experiments_artifact`), never invented by an agent (§G.2 point 7:
"כל מספר בדוח מאומת מול `experiments.json`").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from harbor_vale.ml.train import CVResult, TrainedVariant
from harbor_vale.plans.experiment_plan import ExperimentPlan

_METRIC_KEY_TO_LABEL = {
    "roc_auc": "roc_auc",
    "pr_auc": "pr_auc",
    "f1": "f1",
    "precision": "precision",
    "recall": "recall",
    "accuracy": "accuracy",
}


def compute_metrics(y_true: "np.ndarray", y_pred_proba: "np.ndarray", y_pred_labels: "np.ndarray") -> dict[str, Any]:
    """The full §G.2 metric set for one set of predictions.
    `confusion_matrix` is returned as a plain nested list (`[[tn, fp], [fn, tp]]`)
    — JSON-serializable, no numpy types leak into the returned dict.
    """
    cm = confusion_matrix(y_true, y_pred_labels, labels=[0, 1])
    return {
        "roc_auc": float(roc_auc_score(y_true, y_pred_proba)),
        "pr_auc": float(average_precision_score(y_true, y_pred_proba)),
        "f1": float(f1_score(y_true, y_pred_labels, zero_division=0)),
        "precision": float(precision_score(y_true, y_pred_labels, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred_labels, zero_division=0)),
        "accuracy": float(accuracy_score(y_true, y_pred_labels)),
        "confusion_matrix": cm.tolist(),
    }


def evaluate_cv_results(trained_variants: list[TrainedVariant], y_train: "np.ndarray") -> dict[str, dict[str, Any]]:
    """Per-variant CV metrics from each variant's out-of-fold predictions —
    the ONLY input to model selection. Returns `{variant_name: metrics}`,
    in the variants' own declared order (dict insertion order preserved)."""
    results: dict[str, dict[str, Any]] = {}
    for trained in trained_variants:
        results[trained.variant_name] = compute_metrics(
            np.asarray(y_train), trained.cv_result.oof_predictions, trained.cv_result.oof_predicted_labels
        )
    return results


def select_winner(cv_metrics: dict[str, dict[str, Any]], primary_metric: str, variant_order: list[str]) -> str:
    """Pure Python argmax on `primary_metric` across `cv_metrics`.

    **Deterministic tie-break:** iterates variants in `variant_order` (the
    plan's own declared order) and keeps the first variant whose metric is
    STRICTLY greater than the current best — so an exact tie always
    resolves to whichever variant was declared earliest in the
    `ExperimentPlan`, never to iteration-order-of-a-dict or any other
    incidental ordering. Same `cv_metrics` + same `variant_order` always
    produce the same winner.
    """
    best_name: str | None = None
    best_value = float("-inf")
    for name in variant_order:
        value = cv_metrics[name][primary_metric]
        if value > best_value:
            best_value = value
            best_name = name
    if best_name is None:  # pragma: no cover — variant_order is never empty in practice
        raise ValueError("cannot select a winner from an empty variant list")
    return best_name


def final_test_evaluation(winner: TrainedVariant, X_test, y_test) -> dict[str, Any]:
    """The ONLY place the test set is used — a single `predict_proba` call
    on the winner's pipeline, already fit on the full training split.
    Called exactly once per experiment run (§G.2)."""
    y_pred_proba = winner.fitted_pipeline.predict_proba(X_test)[:, 1]
    y_pred_labels = (y_pred_proba >= 0.5).astype(int)
    return compute_metrics(np.asarray(y_test), y_pred_proba, y_pred_labels)


@dataclass(frozen=True)
class ExperimentRunResult:
    winner_name: str
    winner_estimator: str
    primary_metric: str
    cv_metrics: dict[str, dict[str, Any]]
    test_metrics: dict[str, Any]


def build_experiments_artifact(
    *,
    run_id: str,
    plan: ExperimentPlan,
    trained_variants: list[TrainedVariant],
    cv_metrics: dict[str, dict[str, Any]],
    winner_name: str,
    test_metrics: dict[str, Any],
    created_at: str | None = None,
) -> dict[str, Any]:
    """The full, structured `experiments.json`-shaped artifact — the sole
    machine-readable source of truth every later narrative number must be
    verifiable against (§G.2 point 7)."""
    winner = next(t for t in trained_variants if t.variant_name == winner_name)
    return {
        "run_id": run_id,
        "created_at": created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "primary_metric": plan.primary_metric,
        "metric_rationale": plan.metric_rationale,
        "cv_folds": plan.cv_folds,
        "variants": [
            {
                "name": v.name,
                "estimator": v.estimator,
                "params": v.params,
                "rationale": v.rationale,
                "cv_metrics": cv_metrics[v.name],
            }
            for v in plan.variants
        ],
        "winner": {
            "name": winner_name,
            "estimator": winner.estimator,
            "cv_metrics": cv_metrics[winner_name],
            "test_metrics": test_metrics,
        },
    }


def verify_metric_in_experiments(experiments: dict[str, Any], *, variant_name: str, split: str, metric: str) -> float:
    """Look up one number in an `experiments.json`-shaped dict by exactly
    the same path `build_experiments_artifact` writes it at — the
    deterministic verification helper a future narrative-number-checking
    step (Phase 6+'s "כל מספר בדוח מאומת מול experiments.json") calls
    instead of re-deriving its own parsing logic.

    Args:
        split: `"cv"` or `"test"` — `"test"` is only valid for the winner.
    """
    if split == "cv":
        for variant in experiments["variants"]:
            if variant["name"] == variant_name:
                return float(variant["cv_metrics"][metric])
        raise KeyError(f"no variant named {variant_name!r} in experiments artifact")
    if split == "test":
        if experiments["winner"]["name"] != variant_name:
            raise KeyError(f"{variant_name!r} is not the winner; test metrics exist only for the winner")
        return float(experiments["winner"]["test_metrics"][metric])
    raise ValueError(f"split must be 'cv' or 'test', got {split!r}")
