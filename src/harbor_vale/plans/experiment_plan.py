"""`ExperimentPlan` — the Modeling & Experimentation Specialist agent's
output (PROJECT_PLAN.md §G.2 point 6).

The estimator vocabulary is closed to exactly the three PROJECT_PLAN.md §G.2
itself names as intentionally frozen (§ Chapter X — no hyperparameter
tuning, no additional model families): `logistic_regression`,
`random_forest`, `gradient_boosting`. Every estimator's hyperparameters are
checked against an explicit, closed allowlist (`_PARAM_ALLOWLISTS` below) —
no arbitrary sklearn class, no arbitrary kwarg, no `eval`.

`random_state` is deliberately NEVER an agent-settable parameter — allowing
it would let an agent pick a seed to game reproducibility. `ml/train.py`
always injects `random_state=42` itself (§G.2: "`random_state=42`").

Deliberate omission: no `from __future__ import annotations` (Sessions
17–18's proven CrewAI guardrail-annotation rule).
"""

from typing import Any, Literal, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


def _non_empty(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be empty")
    return stripped


Estimator = Literal["logistic_regression", "random_forest", "gradient_boosting"]
"""§G.2: "3 וריאציות (קפוא בכוונה)" — exactly these three. Not
`decision_tree` or any other family; PROJECT_PLAN.md's own G.2 table never
names a fourth."""

PrimaryMetric = Literal["roc_auc", "pr_auc", "f1", "precision", "recall", "accuracy"]
"""§G.2's metric list. All six are valid for `binary_classification` — the
only `task_type` this project implements (`contract.schema.TargetContract.task_type`)."""

# Closed hyperparameter allowlists — each value is (type, constraint). An
# agent may set ONLY these keys, within these bounds; anything else is a
# structural rejection.
_PARAM_ALLOWLISTS: dict[Estimator, dict[str, tuple[type, tuple[Any, ...] | None]]] = {
    "logistic_regression": {
        "C": (float, (0.0, 100.0)),  # exclusive lower bound enforced separately
        "class_weight": (str, ("balanced",)),
        "max_iter": (int, (10, 10000)),
    },
    "random_forest": {
        "n_estimators": (int, (10, 1000)),
        "max_depth": (int, (1, 100)),
        "class_weight": (str, ("balanced", "balanced_subsample")),
        "min_samples_leaf": (int, (1, 100)),
    },
    "gradient_boosting": {
        "n_estimators": (int, (10, 1000)),
        "learning_rate": (float, (0.0001, 1.0)),
        "max_depth": (int, (1, 10)),
    },
}

_FORBIDDEN_PARAM_NAMES = {"random_state", "n_jobs", "verbose"}
"""Explicitly never agent-settable, regardless of estimator — `random_state`
for reproducibility integrity (see module docstring); `n_jobs`/`verbose`
are execution-environment concerns, not modeling decisions."""


class ExperimentVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    estimator: Estimator
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str

    @field_validator("name", "rationale")
    @classmethod
    def _not_empty(cls, v: str, info) -> str:  # noqa: ANN001
        return _non_empty(v, f"variant.{info.field_name}")


class ExperimentPlan(BaseModel):
    """§G.2 point 6's full output."""

    model_config = ConfigDict(extra="forbid")

    primary_metric: PrimaryMetric
    metric_rationale: str
    cv_folds: int = Field(ge=2, le=10)
    variants: list[ExperimentVariant]

    @field_validator("metric_rationale")
    @classmethod
    def _rationale_not_empty(cls, v: str) -> str:
        return _non_empty(v, "metric_rationale")


# ---------------------------------------------------------------------------
# Guardrail
# ---------------------------------------------------------------------------


class ExperimentPlanRejected(Exception):
    """Internal marker for `validate_experiment_plan`'s semantic failures —
    caught inside the function; never escapes it."""


def _validate_params(variant: ExperimentVariant) -> None:
    allowlist = _PARAM_ALLOWLISTS[variant.estimator]
    for key, value in variant.params.items():
        if key in _FORBIDDEN_PARAM_NAMES:
            raise ExperimentPlanRejected(
                f"variant {variant.name!r}: param {key!r} may never be set by a plan "
                "(reproducibility/environment concern, controlled by ml/train.py only)"
            )
        if key not in allowlist:
            raise ExperimentPlanRejected(
                f"variant {variant.name!r}: param {key!r} is not in the allowlist for "
                f"estimator {variant.estimator!r} (allowed: {sorted(allowlist)})"
            )
        expected_type, bounds = allowlist[key]
        # bool is a subclass of int in Python — explicitly reject a bool
        # where an int/float was expected so `class_weight` never accepts
        # True/False in place of a real string, and numeric params never
        # silently accept True/False either.
        if isinstance(value, bool) or not isinstance(value, expected_type):
            raise ExperimentPlanRejected(
                f"variant {variant.name!r}: param {key!r} must be of type "
                f"{expected_type.__name__}, got {type(value).__name__}"
            )
        if expected_type is str:
            if value not in bounds:
                raise ExperimentPlanRejected(
                    f"variant {variant.name!r}: param {key!r}={value!r} not in allowed values {bounds}"
                )
        else:
            lo, hi = bounds
            if not (lo <= value <= hi):
                raise ExperimentPlanRejected(
                    f"variant {variant.name!r}: param {key!r}={value!r} outside allowed range [{lo}, {hi}]"
                )


def _validate_semantics(plan: ExperimentPlan, *, task_type: str) -> None:
    if task_type != "binary_classification":
        raise ExperimentPlanRejected(
            f"unsupported task_type {task_type!r} — this project implements binary_classification only"
        )
    if len(plan.variants) < 2:
        raise ExperimentPlanRejected(
            f"at least 2 variants are required (§G.2 point 7); got {len(plan.variants)}"
        )
    names = [v.name for v in plan.variants]
    if len(set(names)) != len(names):
        raise ExperimentPlanRejected(f"variant names must be unique; got {names}")
    for variant in plan.variants:
        _validate_params(variant)


def validate_experiment_plan(output, *, task_type: str = "binary_classification") -> Tuple[bool, Any]:
    """Parse and validate an `ExperimentPlan` (§G.2 point 7).

    Same guardrail contract as every other `plans/*` validator: accepts a
    `TaskOutput`-shaped object (`.raw`), raw JSON `str`/`bytes`, a `dict`,
    or an already-constructed `ExperimentPlan`; never raises; returns
    `(True, ExperimentPlan)` or `(False, message)`.
    """
    raw = getattr(output, "raw", output)

    try:
        if isinstance(raw, ExperimentPlan):
            plan = raw
        elif isinstance(raw, (str, bytes, bytearray)):
            plan = ExperimentPlan.model_validate_json(raw)
        elif isinstance(raw, dict):
            plan = ExperimentPlan.model_validate(raw)
        else:
            return False, f"unsupported guardrail input type: {type(raw).__name__}"
    except ValidationError as exc:
        return False, f"ExperimentPlan failed schema validation: {exc}"
    except Exception as exc:  # noqa: BLE001 — a guardrail must never raise
        return False, f"ExperimentPlan could not be parsed: {exc}"

    try:
        _validate_semantics(plan, task_type=task_type)
    except ExperimentPlanRejected as exc:
        return False, f"ExperimentPlan failed semantic validation: {exc}"

    return True, plan
