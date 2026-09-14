"""`FeaturePlan` — the Feature Engineer agent's output (PROJECT_PLAN.md §G.1
point 6): which features to use, how to derive/transform/encode them, and
an explicit acknowledgment of the `DatasetContract` (§F.0 layer 2 —
"non-blocking acknowledgment", never the gate itself).

Guardrail validation (§G.1 point 7) cross-checks the plan against the
ACTUAL `DatasetContract`, not just its own Pydantic shape: every feature
must be a real declared column, no `hard`-excluded feature may be used,
every `required_features` entry must be included, the target must never
appear as a feature, and every `advisory`-excluded feature used requires an
explicit override with a justification.

Deliberate omission: no `from __future__ import annotations` (Sessions
17–18's proven CrewAI guardrail-annotation rule).
"""

from typing import Any, Literal, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from harbor_vale.contract.schema import DatasetContract, EnforcementLevel


def _non_empty(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be empty")
    return stripped


# ---------------------------------------------------------------------------
# Closed sub-structures
# ---------------------------------------------------------------------------


class ContractAcknowledgment(BaseModel):
    """§F.0 layer 2's exact shape: `contract_acknowledgment{contract_version,
    target_confirmed, required_features_confirmed,
    excluded_features_respected[], constraints_relied_upon[]}`. This is a
    documented, auditable declaration — never a second enforcement path
    (the gate, Phase 4, is the only PASS/FAIL authority)."""

    model_config = ConfigDict(extra="forbid")

    contract_version: str
    target_confirmed: bool
    required_features_confirmed: bool
    excluded_features_respected: list[str] = Field(
        description="Names of excluded_features the agent confirms it respected."
    )
    constraints_relied_upon: list[str] = Field(
        default_factory=list,
        description="Free-text list of which contract constraints this plan relies on.",
    )

    @field_validator("contract_version")
    @classmethod
    def _version_not_empty(cls, v: str) -> str:
        return _non_empty(v, "contract_acknowledgment.contract_version")


EncoderKind = Literal["onehot", "ordinal"]


class EncoderSpec(BaseModel):
    """Maps directly onto an sklearn `ColumnTransformer` entry
    (`tools/feature_tools.py`) — a closed set of two encoder kinds, never an
    arbitrary encoder class."""

    model_config = ConfigDict(extra="forbid")

    column: str
    kind: EncoderKind

    @field_validator("column")
    @classmethod
    def _column_not_empty(cls, v: str) -> str:
        return _non_empty(v, "encoder.column")


TransformKind = Literal["log1p", "standard_scale", "minmax_scale"]


class TransformSpec(BaseModel):
    """A closed numeric transform applied to one column before/instead of
    encoding — e.g. `log1p` for a right-skewed monetary column (§G.1 point 2:
    "log על מוטה"). Never an arbitrary expression."""

    model_config = ConfigDict(extra="forbid")

    column: str
    kind: TransformKind

    @field_validator("column")
    @classmethod
    def _column_not_empty(cls, v: str) -> str:
        return _non_empty(v, "transform.column")


DerivedFeatureKind = Literal["ratio"]
"""Deliberately a single closed kind for this project's scope — a ratio of
two existing numeric columns (e.g. `total_charges / tenure_months`, a
plausible "average monthly spend" derivation). Extending this vocabulary is
a deliberate future decision, not something a plan can request ad hoc; no
`eval`, no arbitrary expression, ever."""


class DerivedFeatureSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: DerivedFeatureKind
    numerator: str
    denominator: str
    description: str

    @field_validator("name", "numerator", "denominator", "description")
    @classmethod
    def _not_empty(cls, v: str, info) -> str:  # noqa: ANN001
        return _non_empty(v, f"derived.{info.field_name}")


class DroppedFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    reason: str

    @field_validator("column", "reason")
    @classmethod
    def _not_empty(cls, v: str, info) -> str:  # noqa: ANN001
        return _non_empty(v, f"dropped.{info.field_name}")


class AdvisoryOverride(BaseModel):
    """§G.1 point 6/7: using an `advisory`-excluded feature requires an
    explicit override WITH justification — never silent inclusion."""

    model_config = ConfigDict(extra="forbid")

    column: str
    justification: str

    @field_validator("column", "justification")
    @classmethod
    def _not_empty(cls, v: str, info) -> str:  # noqa: ANN001
        return _non_empty(v, f"advisory_override.{info.field_name}")


class FeaturePlan(BaseModel):
    """§G.1 point 6's full output."""

    model_config = ConfigDict(extra="forbid")

    contract_acknowledgment: ContractAcknowledgment
    use_features: list[str]
    derived: list[DerivedFeatureSpec] = []
    transforms: list[TransformSpec] = []
    encoders: list[EncoderSpec] = []
    dropped: list[DroppedFeature] = []
    advisory_overrides: list[AdvisoryOverride] = []


# ---------------------------------------------------------------------------
# Guardrail — cross-validated against the actual DatasetContract.
# ---------------------------------------------------------------------------


class FeaturePlanRejected(Exception):
    """Internal marker for `validate_feature_plan`'s semantic failures —
    caught inside the function; never escapes it."""


def _validate_semantics(plan: FeaturePlan, contract: DatasetContract) -> None:
    if plan.contract_acknowledgment.contract_version != contract.contract_version:
        raise FeaturePlanRejected(
            f"contract_acknowledgment.contract_version "
            f"{plan.contract_acknowledgment.contract_version!r} does not match the actual "
            f"contract version {contract.contract_version!r}"
        )
    if not plan.contract_acknowledgment.target_confirmed:
        raise FeaturePlanRejected("contract_acknowledgment.target_confirmed must be true")
    if not plan.contract_acknowledgment.required_features_confirmed:
        raise FeaturePlanRejected("contract_acknowledgment.required_features_confirmed must be true")

    declared_columns = {c.name for c in contract.columns}
    target_name = contract.target.name
    hard_excluded = {
        f.name for f in contract.excluded_features if f.enforcement == EnforcementLevel.HARD
    }
    advisory_excluded = {
        f.name for f in contract.excluded_features if f.enforcement == EnforcementLevel.ADVISORY
    }

    if target_name in plan.use_features:
        raise FeaturePlanRejected(f"target {target_name!r} must never appear in use_features")

    unresolved = [c for c in plan.use_features if c not in declared_columns]
    if unresolved:
        raise FeaturePlanRejected(f"use_features references undeclared column(s): {unresolved}")

    hard_used = [c for c in plan.use_features if c in hard_excluded]
    if hard_used:
        raise FeaturePlanRejected(
            f"use_features includes hard-excluded feature(s), which must never be used: {hard_used}"
        )

    overridden = {o.column for o in plan.advisory_overrides}
    advisory_used_without_override = [
        c for c in plan.use_features if c in advisory_excluded and c not in overridden
    ]
    if advisory_used_without_override:
        raise FeaturePlanRejected(
            "use_features includes advisory-excluded feature(s) with no matching "
            f"advisory_overrides entry (justification required): {advisory_used_without_override}"
        )
    for override in plan.advisory_overrides:
        if override.column not in advisory_excluded:
            raise FeaturePlanRejected(
                f"advisory_overrides references {override.column!r}, which is not an "
                "advisory-excluded feature in this contract"
            )

    missing_required = [f for f in contract.required_features if f not in plan.use_features]
    if missing_required:
        raise FeaturePlanRejected(
            f"required_features not included in use_features: {missing_required}"
        )

    for derived in plan.derived:
        for col in (derived.numerator, derived.denominator):
            if col not in declared_columns and col not in {d.name for d in plan.derived}:
                raise FeaturePlanRejected(
                    f"derived feature {derived.name!r} references undeclared column {col!r}"
                )

    known_feature_names = set(plan.use_features) | {d.name for d in plan.derived}
    for transform in plan.transforms:
        if transform.column not in known_feature_names:
            raise FeaturePlanRejected(
                f"transform references {transform.column!r}, which is not in use_features or derived"
            )
    for encoder in plan.encoders:
        if encoder.column not in known_feature_names:
            raise FeaturePlanRejected(
                f"encoder references {encoder.column!r}, which is not in use_features or derived"
            )

    for dropped in plan.dropped:
        if dropped.column not in declared_columns:
            raise FeaturePlanRejected(
                f"dropped references undeclared column {dropped.column!r}"
            )


def validate_feature_plan(output, *, contract: DatasetContract | None = None) -> Tuple[bool, Any]:
    """Parse and validate a `FeaturePlan` (§G.1 point 7).

    Same guardrail contract as every other `plans/*` validator: accepts a
    `TaskOutput`-shaped object (`.raw`), raw JSON `str`/`bytes`, a `dict`,
    or an already-constructed `FeaturePlan`; never raises; returns
    `(True, FeaturePlan)` or `(False, message)`.

    Args:
        contract: the actual `DatasetContract` this plan claims to
            acknowledge — every cross-check runs against this real object,
            never against the plan's own self-description of the contract.
            Defaults to `None` only so this function stays constructible as
            a bare `Task(guardrail=...)` (CrewAI 1.15.20 only counts
            REQUIRED parameters against its "exactly one parameter" rule —
            verified empirically); a real caller (Phase 6+, via a
            one-argument closure per `Task`) must always supply a real
            `contract`.
    """
    if contract is None:
        return False, "validate_feature_plan: no contract supplied — this is a caller wiring error, not a plan defect"

    raw = getattr(output, "raw", output)

    try:
        if isinstance(raw, FeaturePlan):
            plan = raw
        elif isinstance(raw, (str, bytes, bytearray)):
            plan = FeaturePlan.model_validate_json(raw)
        elif isinstance(raw, dict):
            plan = FeaturePlan.model_validate(raw)
        else:
            return False, f"unsupported guardrail input type: {type(raw).__name__}"
    except ValidationError as exc:
        return False, f"FeaturePlan failed schema validation: {exc}"
    except Exception as exc:  # noqa: BLE001 — a guardrail must never raise
        return False, f"FeaturePlan could not be parsed: {exc}"

    try:
        _validate_semantics(plan, contract)
    except FeaturePlanRejected as exc:
        return False, f"FeaturePlan failed semantic validation: {exc}"

    return True, plan
