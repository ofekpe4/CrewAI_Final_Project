"""The production Dataset Contract schema (PROJECT_PLAN.md §E).

The central rule (§E.1, §E.2): **`observed` != `constraints`.**

- `observed.*` fields are measurements. Deterministic Python writes them
  (see `contract/builder.py`). They describe what the current dataset looks
  like and are never, by themselves, an enforceable rule.
- `constraints.*` fields are enforceable rules. They exist only when a human
  or an LLM agent explicitly declared them, and every constraint the Plan
  requires justification for (`business_range`, `unit`, `closed_domain`,
  `scale_drift`, uniqueness) is rejected by this schema if that justification
  is missing or empty. A constraint field left `None` means **no
  corresponding enforcement** — that is a legitimate, common state, not an
  error.

This module defines *shape* and *internal self-consistency* only. It has no
opinion about any specific dataset's real column list — that cross-check
(declared columns vs. the actual CSV's columns) is the deterministic
builder's job (`contract/builder.py`), because only the builder has read the
real file. See `docs/contract_spec.md` for the full human-readable reference,
including the paired BAD/GOOD examples this schema is built to reject/allow.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enums — closed vocabularies. Only the categories PROJECT_PLAN.md §E.4
# actually defines are implemented for `ExclusionType`; nothing invented.
# ---------------------------------------------------------------------------


class ExclusionType(str, Enum):
    """PROJECT_PLAN.md §E.4 — the exact five categories the Plan defines.

    `target_leakage` requires genuine temporal/semantic justification (a
    column measured or created *after* the outcome, or one that encodes the
    label some other way) — never merely "this column correlates with the
    target" (§E.4: that is `redundancy_collinearity`). The Phase 2 decision
    that `total_charges` is redundant/collinear, **not** leakage, is the
    canonical example (data/README.md §6.3).
    """

    IDENTIFIER = "identifier"
    TARGET_LEAKAGE = "target_leakage"
    REDUNDANCY_COLLINEARITY = "redundancy_collinearity"
    MODELING_SIMPLICITY = "modeling_simplicity"
    ETHICAL_SENSITIVE = "ethical_sensitive"


class EnforcementLevel(str, Enum):
    """PROJECT_PLAN.md §E.4 — `hard` (ERROR if the feature is used) or `advisory` (WARN only)."""

    HARD = "hard"
    ADVISORY = "advisory"


class Severity(str, Enum):
    """Finding severity for constraints that carry one (§E.2 `scale_drift`, `closed_domain`)."""

    ERROR = "ERROR"
    WARN = "WARN"


class SemanticType(str, Enum):
    """Per-column semantic category.

    Not a closed vocabulary the Plan itself enumerates (§D.3 leaves
    `semantic_type` as free-form) — this is an implementation choice to get
    schema-level validation instead of an unchecked string. Documented as
    such in docs/contract_spec.md; extend if a future dataset needs a
    category not listed here (that is not a Plan-authority question the way
    `ExclusionType` is).
    """

    IDENTIFIER = "identifier"
    MONETARY = "monetary"
    CATEGORICAL = "categorical"
    BINARY = "binary"
    NUMERIC = "numeric"
    TEMPORAL = "temporal"
    TEXT = "text"
    OTHER = "other"


def _non_empty(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be empty")
    return stripped


# ---------------------------------------------------------------------------
# Constraint primitives — every one that the Plan requires justification for
# enforces it at the field level, so a missing/empty justification is
# rejected the instant the object is constructed, independent of where it is
# nested (column, target, or primary key).
# ---------------------------------------------------------------------------


class DtypeConstraint(BaseModel):
    """§E.2 example: `{"expected": "float64", "justification": "..."}`."""

    model_config = ConfigDict(extra="forbid")

    expected: str
    justification: str

    @field_validator("justification")
    @classmethod
    def _justification_not_empty(cls, v: str) -> str:
        return _non_empty(v, "dtype.justification")


class NullableConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: bool
    justification: str

    @field_validator("justification")
    @classmethod
    def _justification_not_empty(cls, v: str) -> str:
        return _non_empty(v, "nullable.justification")


class UnitConstraint(BaseModel):
    """§E.2 rule: a unit declaration must always carry evidence — including
    the honest `"currency_unspecified"` state (§Phase 2 criterion 11,
    data/README.md §6.2). Evidence is never optional; what varies is only
    *what* the evidence says.
    """

    model_config = ConfigDict(extra="forbid")

    value: str
    evidence: str
    confidence: Literal["high", "medium", "low"] | None = None

    @field_validator("value", "evidence")
    @classmethod
    def _not_empty(cls, v: str, info) -> str:  # noqa: ANN001
        return _non_empty(v, f"unit.{info.field_name}")


class BusinessRangeConstraint(BaseModel):
    """§E.2 rule: `business_range` requires a non-empty `justification` —
    enforced here, not left to a downstream validator, so a malformed
    contract can never be constructed at all (§Phase 3 required semantic
    rule #1).
    """

    model_config = ConfigDict(extra="forbid")

    min: float | None = None
    max: float | None = None
    justification: str

    @field_validator("justification")
    @classmethod
    def _justification_not_empty(cls, v: str) -> str:
        return _non_empty(v, "business_range.justification")

    @model_validator(mode="after")
    def _at_least_one_bound(self) -> "BusinessRangeConstraint":
        if self.min is None and self.max is None:
            raise ValueError(
                "business_range must declare at least one of min/max — "
                "an empty range constrains nothing and should be omitted "
                "(constraints.business_range = null) instead"
            )
        return self


class ClosedDomainConstraint(BaseModel):
    """§E.2 rule: enforceable only when a column deliberately declares
    closure, and only with a justification (§Phase 3 required semantic rule
    #5). An undeclared domain is `None` — a new category then WARNs, it does
    not ERROR.
    """

    model_config = ConfigDict(extra="forbid")

    values: list[str]
    justification: str
    severity: Severity = Severity.ERROR

    @field_validator("values")
    @classmethod
    def _values_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("closed_domain.values must not be empty")
        return v

    @field_validator("justification")
    @classmethod
    def _justification_not_empty(cls, v: str) -> str:
        return _non_empty(v, "closed_domain.justification")


class ScaleDriftConstraint(BaseModel):
    """§E.2/§E.3 — a **change detector**, not a business rule (§Phase 3 rule
    #6). Declares how much the observed median may move, relative to the
    contract's own snapshot, before it is flagged as a suspected scale
    change. The runtime comparison itself is Phase 4's validation gate; this
    model only carries the declared policy.
    """

    model_config = ConfigDict(extra="forbid")

    median_rel_tolerance: float = Field(gt=0, le=1)
    justification: str
    severity: Severity = Severity.ERROR

    @field_validator("justification")
    @classmethod
    def _justification_not_empty(cls, v: str) -> str:
        return _non_empty(v, "scale_drift.justification")


class UniqueConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: bool
    justification: str

    @field_validator("justification")
    @classmethod
    def _justification_not_empty(cls, v: str) -> str:
        return _non_empty(v, "unique.justification")


class TargetDriftConstraint(BaseModel):
    """§E.2 example: `positive_rate_tolerance_abs` + justification.

    Not Phase 2's measured 26.54% turned into a permanent invariant — this
    is an explicit, separately-justified policy about how much the *base
    rate* may move before it signals the label's meaning changed, matching
    §E.2's own wording ("a large shift in base rate implies the label's
    meaning changed").
    """

    model_config = ConfigDict(extra="forbid")

    positive_rate_tolerance_abs: float = Field(gt=0, le=1)
    justification: str

    @field_validator("justification")
    @classmethod
    def _justification_not_empty(cls, v: str) -> str:
        return _non_empty(v, "target.drift.justification")


# ---------------------------------------------------------------------------
# Observed — measurements only. Every field here is filled by the builder
# from real pandas output; nothing here is ever copied into `constraints`
# automatically (proven in tests/unit/test_observed_not_enforced.py).
# ---------------------------------------------------------------------------


class ColumnObserved(BaseModel):
    """Per-column measured facts (§E.2 "A. תיאורי" block). Written only by
    `contract/builder.py`. Numeric fields are `None` for non-numeric columns.
    """

    model_config = ConfigDict(extra="forbid")

    dtype: str
    null_count: int = Field(ge=0)
    unique_count: int = Field(ge=0)
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    median: float | None = None
    p05: float | None = None
    p95: float | None = None
    std: float | None = None
    decimal_places_max: int | None = Field(default=None, ge=0)
    value_distribution: dict[str, float] | None = None


class TargetObserved(BaseModel):
    model_config = ConfigDict(extra="forbid")

    positive_rate: float = Field(ge=0, le=1)
    class_counts: dict[str, int]


# ---------------------------------------------------------------------------
# Constraints containers — every field optional; `None` means "not enforced".
# ---------------------------------------------------------------------------


class ColumnConstraints(BaseModel):
    """§E.2 "B. נאכף" block. Every field defaults to `None` — a constraint
    exists only if someone declared it (§Phase 3 rule: "missing constraint
    means NO corresponding hard enforcement").
    """

    model_config = ConfigDict(extra="forbid")

    dtype: DtypeConstraint | None = None
    nullable: NullableConstraint | None = None
    unit: UnitConstraint | None = None
    business_range: BusinessRangeConstraint | None = None
    closed_domain: ClosedDomainConstraint | None = None
    scale_drift: ScaleDriftConstraint | None = None


class TargetConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dtype: DtypeConstraint | None = None
    closed_domain: ClosedDomainConstraint | None = None
    nullable: NullableConstraint | None = None


# ---------------------------------------------------------------------------
# Column / target / primary-key / exclusion containers
# ---------------------------------------------------------------------------


class ColumnContract(BaseModel):
    """One non-target column's full contract entry: semantics + observed + constraints."""

    model_config = ConfigDict(extra="forbid")

    name: str
    semantic_type: SemanticType
    observed: ColumnObserved
    constraints: ColumnConstraints

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        return _non_empty(v, "column.name")


class TargetContract(BaseModel):
    """The target section (§E.2). Defined exactly once at the top level of
    `DatasetContract` — there is no list of targets, so "target defined
    exactly once" (§Phase 3 rule #8) is a structural guarantee of this being
    a single field, not a collection.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    task_type: Literal["binary_classification"]
    constraints: TargetConstraints
    observed: TargetObserved
    drift: TargetDriftConstraint | None = None

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        return _non_empty(v, "target.name")


class ExcludedFeature(BaseModel):
    """§E.4. `exclusion_type` is the closed enum; every exclusion needs a
    non-empty justification regardless of `enforcement` level.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    exclusion_type: ExclusionType
    enforcement: EnforcementLevel
    justification: str

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        return _non_empty(v, "excluded_feature.name")

    @field_validator("justification")
    @classmethod
    def _justification_not_empty(cls, v: str) -> str:
        return _non_empty(v, "excluded_feature.justification")


class PrimaryKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[str]
    constraints: "PrimaryKeyConstraints"

    @field_validator("columns")
    @classmethod
    def _columns_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("primary_key.columns must not be empty")
        return v


class PrimaryKeyConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique: UniqueConstraint


PrimaryKey.model_rebuild()


class Integrity(BaseModel):
    """§E.2. Written entirely by the builder from the actual CSV bytes —
    never by an agent (§Phase 3: "SHA256 must be deterministic and based on
    the exact CSV file bytes").
    """

    model_config = ConfigDict(extra="forbid")

    clean_data_sha256: str
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    column_order: list[str]

    @field_validator("clean_data_sha256")
    @classmethod
    def _sha256_shape(cls, v: str) -> str:
        v = v.lower()
        if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
            raise ValueError("clean_data_sha256 must be a 64-character hex SHA256 digest")
        return v

    @model_validator(mode="after")
    def _column_count_matches_order(self) -> "Integrity":
        if self.column_count != len(self.column_order):
            raise ValueError(
                f"column_count ({self.column_count}) does not match "
                f"len(column_order) ({len(self.column_order)})"
            )
        if len(set(self.column_order)) != len(self.column_order):
            raise ValueError("column_order contains duplicate column names")
        return self


class ValidationPolicy(BaseModel):
    """Declares Phase 4 gate policy knobs. Phase 3 only *carries* this
    declaration — it does not implement or run the gate (that is
    `contract/validator.py`, explicitly out of scope here).
    """

    model_config = ConfigDict(extra="forbid")

    on_unknown_column: Literal["warn", "error", "ignore"] = "warn"
    on_missing_column: Literal["warn", "error"] = "error"
    on_integrity_mismatch: Literal["warn", "error"] = "error"
    scale_change_ratio_hints: list[float] = Field(
        default_factory=lambda: [0.001, 0.01, 0.1, 10, 100, 1000]
    )


# ---------------------------------------------------------------------------
# The contract itself
# ---------------------------------------------------------------------------


class DatasetContract(BaseModel):
    """The full Dataset Contract (§E.2). Crew 1's and the validation gate's
    shared interface — never hand-written, always produced by
    `contract/builder.py` from a validated `ContractDraft` + real CSV bytes.
    """

    model_config = ConfigDict(extra="forbid")

    contract_version: str
    created_at: str
    created_by: str
    run_id: str
    dataset_name: str
    source_documentation_url: str

    target: TargetContract
    required_features: list[str]
    excluded_features: list[ExcludedFeature]
    primary_key: PrimaryKey
    columns: list[ColumnContract]
    integrity: Integrity
    assumptions: list[str]
    validation_policy: ValidationPolicy

    @field_validator("created_at")
    @classmethod
    def _created_at_is_iso8601(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"created_at must be ISO-8601: {exc}") from exc
        return v

    @field_validator("dataset_name", "created_by", "run_id", "source_documentation_url")
    @classmethod
    def _metadata_not_empty(cls, v: str, info) -> str:  # noqa: ANN001
        return _non_empty(v, info.field_name)

    # --- cross-field self-consistency (no external CSV access needed) ------

    @model_validator(mode="after")
    def _target_not_duplicated_as_a_column(self) -> "DatasetContract":
        column_names = [c.name for c in self.columns]
        if self.target.name in column_names:
            raise ValueError(
                f"target {self.target.name!r} must not also appear in `columns` "
                "— the target is declared exactly once, in the `target` section"
            )
        return self

    @model_validator(mode="after")
    def _column_names_unique(self) -> "DatasetContract":
        column_names = [c.name for c in self.columns]
        if len(set(column_names)) != len(column_names):
            raise ValueError("`columns` contains duplicate column names")
        return self

    @model_validator(mode="after")
    def _required_and_excluded_reference_declared_columns(self) -> "DatasetContract":
        declared = {c.name for c in self.columns}

        unresolved_required = [n for n in self.required_features if n not in declared]
        if unresolved_required:
            raise ValueError(
                f"required_features references undeclared column(s): {unresolved_required}"
            )
        if self.target.name in self.required_features:
            raise ValueError("target must not also appear in required_features")

        unresolved_excluded = [f.name for f in self.excluded_features if f.name not in declared]
        if unresolved_excluded:
            raise ValueError(
                f"excluded_features references undeclared column(s): {unresolved_excluded}"
            )

        hard_excluded = {
            f.name for f in self.excluded_features if f.enforcement == EnforcementLevel.HARD
        }
        conflict = hard_excluded & set(self.required_features)
        if conflict:
            raise ValueError(
                f"column(s) both hard-excluded and required_features: {sorted(conflict)}"
            )
        return self

    @model_validator(mode="after")
    def _primary_key_references_declared_columns(self) -> "DatasetContract":
        declared = {c.name for c in self.columns}
        unresolved = [n for n in self.primary_key.columns if n not in declared]
        if unresolved:
            raise ValueError(f"primary_key references undeclared column(s): {unresolved}")
        return self

    @model_validator(mode="after")
    def _integrity_column_order_matches_declared_columns(self) -> "DatasetContract":
        expected = {self.target.name} | {c.name for c in self.columns}
        actual = set(self.integrity.column_order)
        if expected != actual:
            missing = expected - actual
            extra = actual - expected
            detail = []
            if missing:
                detail.append(f"missing from column_order: {sorted(missing)}")
            if extra:
                detail.append(f"in column_order but not declared anywhere: {sorted(extra)}")
            raise ValueError(
                "integrity.column_order does not match {target} + columns: "
                + "; ".join(detail)
            )
        return self
