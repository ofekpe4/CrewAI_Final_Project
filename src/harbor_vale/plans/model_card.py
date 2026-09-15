"""`ModelCard` — the Responsible AI Documenter agent's output (PROJECT_PLAN.md
§G.3 point 6).

**Anti-fabrication design (§G.3 point 5/7):** the agent may narrate
limitations, ethics, and monitoring recommendations — judgment text, §G.3
point 1's own framing — but it may never invent a metric, and it may never
claim measured fairness the project never measured. Both are enforced
mechanically, not by trusting the narrative:

- `metrics_summary` is a list of **typed** `MetricClaim`s — `metric` is
  drawn from the exact closed vocabulary `ml/evaluate.py` actually computes
  (`roc_auc`, `pr_auc`, `f1`, `precision`, `recall`, `accuracy`). There is
  no `"fairness"` (or any other) value this field can structurally hold —
  the closed `Literal` makes an unmeasured-fairness numeric claim
  inexpressible, not merely disallowed by convention.
- Every `MetricClaim`'s `value` is cross-checked against a real
  `experiments.json`-shaped dict via
  `ml.evaluate.verify_metric_in_experiments` — the exact same lookup
  `ml/evaluate.py` itself uses, not a second, divergent verification path.
  An invented metric/variant/split, or a claimed value that doesn't match
  the real one, is rejected.

Deliberate omission: no `from __future__ import annotations` (Sessions
17–18's proven CrewAI guardrail-annotation rule — see
`plans/contract_draft.py`'s docstring for the full explanation). The
context-parameter default pattern below follows the Phase 5 finding
documented in `docs/architecture.md`'s Phase 5 addendum (`Task.guardrail`
only counts REQUIRED parameters).
"""

from typing import Any, Literal, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from harbor_vale.contract.schema import DatasetContract
from harbor_vale.ml.evaluate import verify_metric_in_experiments


def _non_empty(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be empty")
    return stripped


def _non_empty_list_items(values: list[str], field_name: str) -> list[str]:
    for v in values:
        _non_empty(v, field_name)
    return values


MetricName = Literal["roc_auc", "pr_auc", "f1", "precision", "recall", "accuracy"]
"""The exact closed vocabulary `ml/evaluate.compute_metrics` computes —
identical to `plans/experiment_plan.py`'s `PrimaryMetric`. No other value
(in particular, no unmeasured `"fairness"`-shaped metric) can be
constructed here."""

MetricSplit = Literal["cv", "test"]


class MetricClaim(BaseModel):
    """One numeric claim in `metrics_summary` — a typed, mechanically
    verifiable statement instead of a free-text number. `variant_name`
    must be a real declared variant; `split="test"` is only valid for
    the actual winning variant (mirrors
    `ml.evaluate.verify_metric_in_experiments`'s own rule)."""

    model_config = ConfigDict(extra="forbid")

    metric: MetricName
    split: MetricSplit
    variant_name: str
    value: float

    @field_validator("variant_name")
    @classmethod
    def _variant_name_not_empty(cls, v: str) -> str:
        return _non_empty(v, "metric_claim.variant_name")


class ModelCard(BaseModel):
    """§G.3 point 6's full output — exactly these nine fields, nothing else."""

    model_config = ConfigDict(extra="forbid")

    purpose: str
    intended_use: str
    out_of_scope_use: list[str] = Field(default_factory=list)
    training_data_summary: str
    metrics_summary: list[MetricClaim]
    limitations: list[str] = Field(default_factory=list)
    ethical_considerations: list[str] = Field(default_factory=list)
    contract_dependencies: list[str]
    monitoring_recommendations: list[str] = Field(default_factory=list)

    @field_validator("purpose", "intended_use", "training_data_summary")
    @classmethod
    def _narrative_not_empty(cls, v: str, info) -> str:  # noqa: ANN001
        return _non_empty(v, info.field_name)

    @field_validator("out_of_scope_use", "limitations", "ethical_considerations", "monitoring_recommendations", "contract_dependencies")
    @classmethod
    def _list_items_not_empty(cls, v: list[str], info) -> list[str]:  # noqa: ANN001
        return _non_empty_list_items(v, info.field_name)

    @field_validator("metrics_summary")
    @classmethod
    def _at_least_one_metric(cls, v: list[MetricClaim]) -> list[MetricClaim]:
        if not v:
            raise ValueError("metrics_summary must not be empty — a model card with zero measured metrics is not defensible")
        return v

    @field_validator("contract_dependencies")
    @classmethod
    def _contract_dependencies_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("contract_dependencies must not be empty (§G.3 point 7)")
        return v


# ---------------------------------------------------------------------------
# Guardrail — cross-validated against experiments.json AND the DatasetContract.
# ---------------------------------------------------------------------------


class ModelCardRejected(Exception):
    """Internal marker for `validate_model_card`'s semantic failures —
    caught inside the function; never escapes it."""


def _validate_semantics(
    card: ModelCard, experiments: dict[str, Any], contract: DatasetContract
) -> None:
    # A. every numeric claim resolves to a real, matching experiments.json value.
    for i, claim in enumerate(card.metrics_summary):
        try:
            actual = verify_metric_in_experiments(
                experiments, variant_name=claim.variant_name, split=claim.split, metric=claim.metric
            )
        except (KeyError, ValueError) as exc:
            raise ModelCardRejected(
                f"metrics_summary[{i}]: {claim.metric}/{claim.split} for variant "
                f"{claim.variant_name!r} does not exist in experiments.json ({exc})"
            ) from exc
        if claim.value != actual:
            raise ModelCardRejected(
                f"metrics_summary[{i}]: claimed {claim.metric}={claim.value} for variant "
                f"{claim.variant_name!r} ({claim.split}) does not match the real measured "
                f"value {actual} in experiments.json — a model card may not invent or "
                "round-differently a machine-measured number"
            )

    # B. contract_dependencies must reference at least one REAL contract assumption.
    #    A mechanical set-membership check, not a substring/keyword search —
    #    the assumption text must appear verbatim, exactly as the contract
    #    itself declares it.
    referenced_assumptions = set(card.contract_dependencies) & set(contract.assumptions)
    if not referenced_assumptions:
        raise ModelCardRejected(
            "contract_dependencies must include at least one entry that exactly matches "
            f"a real contract.assumptions string (§G.3 point 7); contract declares: "
            f"{contract.assumptions}"
        )


def validate_model_card(
    output, *, experiments: dict[str, Any] | None = None, contract: DatasetContract | None = None
) -> Tuple[bool, Any]:
    """Parse and validate a `ModelCard` (§G.3 point 7).

    Same guardrail contract as every other `plans/*` validator in this
    project: accepts a CrewAI `TaskOutput`-shaped object (`.raw`), raw JSON
    `str`/`bytes`, a `dict`, or an already-constructed `ModelCard`; never
    lets a bare `pydantic.ValidationError` (structural failure) or
    `ModelCardRejected` (semantic failure) escape; returns `(True,
    ModelCard)` or `(False, message)`. Never raises.

    Args:
        experiments: the real `experiments.json`-shaped dict
            (`ml.evaluate.build_experiments_artifact`'s output) for the SAME
            run this card describes — the sole source every numeric claim
            is checked against.
        contract: the actual `DatasetContract` this card's
            `contract_dependencies` claims to draw from.

        Both default to `None` ONLY so this function stays constructible as
        a bare `Task(guardrail=...)` — CrewAI 1.15.20 counts only REQUIRED
        parameters against its "exactly one parameter" rule (verified
        empirically, `docs/architecture.md`'s Phase 5 addendum). A real
        caller (Phase 7+, via a one-argument closure per `Task`) must
        always supply both real values, e.g.
        `lambda output: validate_model_card(output, experiments=this_run_experiments, contract=this_run_contract)`.
    """
    if experiments is None or contract is None:
        missing = "experiments" if experiments is None else "contract"
        return False, f"validate_model_card: no {missing} supplied — this is a caller wiring error, not a card defect"

    raw = getattr(output, "raw", output)

    try:
        if isinstance(raw, ModelCard):
            card = raw
        elif isinstance(raw, (str, bytes, bytearray)):
            card = ModelCard.model_validate_json(raw)
        elif isinstance(raw, dict):
            card = ModelCard.model_validate(raw)
        else:
            return False, f"unsupported guardrail input type: {type(raw).__name__}"
    except ValidationError as exc:
        return False, f"ModelCard failed schema validation: {exc}"
    except Exception as exc:  # noqa: BLE001 — a guardrail must never raise
        return False, f"ModelCard could not be parsed: {exc}"

    try:
        _validate_semantics(card, experiments, contract)
    except ModelCardRejected as exc:
        return False, f"ModelCard failed semantic validation: {exc}"

    return True, card
