"""Unit tests for `harbor_vale.contract.schema` (PROJECT_PLAN.md §E).

Focus: `observed` / `constraints` really are separate models; every
constraint the Plan requires justification for (`business_range`, `unit`,
`closed_domain`, `scale_drift`, uniqueness) rejects a missing/empty one;
`exclusion_type` is a closed enum; cross-field references
(required/excluded features, primary key, target, integrity column order)
must resolve against the contract's own declared columns; and no
measurement-shaped field can be smuggled into a place only `constraints`
should occupy.

Runnable two ways:
  * ``pytest tests/unit/test_contract_schema.py``   (once pytest is installed)
  * ``python tests/unit/test_contract_schema.py``   (no test dependency required)
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from pydantic import ValidationError  # noqa: E402

from harbor_vale.contract.schema import (  # noqa: E402
    BusinessRangeConstraint,
    ClosedDomainConstraint,
    ColumnConstraints,
    ColumnContract,
    ColumnObserved,
    DatasetContract,
    DtypeConstraint,
    EnforcementLevel,
    ExcludedFeature,
    ExclusionType,
    Integrity,
    NullableConstraint,
    PrimaryKey,
    PrimaryKeyConstraints,
    ScaleDriftConstraint,
    SemanticType,
    TargetConstraints,
    TargetContract,
    TargetObserved,
    UnitConstraint,
    UniqueConstraint,
    ValidationPolicy,
)


def _minimal_target() -> TargetContract:
    return TargetContract(
        name="churn",
        task_type="binary_classification",
        constraints=TargetConstraints(
            dtype=DtypeConstraint(expected="int64", justification="binary label by construction"),
            closed_domain=ClosedDomainConstraint(values=["0", "1"], justification="binary label by construction"),
            nullable=NullableConstraint(value=False, justification="a row without a label is unusable"),
        ),
        observed=TargetObserved(positive_rate=0.2654, class_counts={"0": 5174, "1": 1869}),
    )


def _minimal_column(name: str = "monthly_charges", **constraint_overrides) -> ColumnContract:
    constraints = ColumnConstraints(
        nullable=NullableConstraint(value=False, justification="every account has this value"),
        **constraint_overrides,
    )
    return ColumnContract(
        name=name,
        semantic_type=SemanticType.MONETARY,
        observed=ColumnObserved(dtype="float64", null_count=0, unique_count=1585, min=18.25, max=118.75),
        constraints=constraints,
    )


def _valid_contract(**overrides) -> DatasetContract:
    columns = overrides.pop("columns", [_minimal_column()])
    required_features = overrides.pop("required_features", ["monthly_charges"])
    excluded_features = overrides.pop("excluded_features", [])
    target = overrides.pop("target", _minimal_target())
    primary_key = overrides.pop(
        "primary_key",
        PrimaryKey(
            columns=["monthly_charges"],
            constraints=PrimaryKeyConstraints(unique=UniqueConstraint(value=True, justification="unique by construction in this test")),
        ),
    )
    integrity = overrides.pop(
        "integrity",
        Integrity(
            clean_data_sha256="a" * 64,
            row_count=7043,
            column_count=2,
            column_order=["churn", "monthly_charges"],
        ),
    )
    kwargs = dict(
        contract_version="1.0.0",
        created_at="2026-09-14T12:00:00Z",
        created_by="test",
        run_id="run-1",
        dataset_name="telco_customer_churn",
        source_documentation_url="https://example.invalid/docs",
        target=target,
        required_features=required_features,
        excluded_features=excluded_features,
        primary_key=primary_key,
        columns=columns,
        integrity=integrity,
        assumptions=["one row per customer"],
        validation_policy=ValidationPolicy(),
    )
    kwargs.update(overrides)
    return DatasetContract(**kwargs)


def _expect_validation_error(fn) -> None:
    try:
        fn()
    except ValidationError:
        return
    raise AssertionError("expected pydantic.ValidationError, none was raised")


# --- baseline: a well-formed contract is accepted ---------------------------

def test_valid_contract_accepted() -> None:
    contract = _valid_contract()
    assert contract.target.name == "churn"
    assert len(contract.columns) == 1


# --- exclusion_type is a closed enum ----------------------------------------

def test_invalid_exclusion_type_rejected() -> None:
    _expect_validation_error(
        lambda: ExcludedFeature(
            name="x", exclusion_type="not_a_real_type", enforcement="hard", justification="x"
        )
    )


def test_all_plan_defined_exclusion_types_accepted() -> None:
    # PROJECT_PLAN.md §E.4 — exactly these five, nothing invented.
    for member in ("identifier", "target_leakage", "redundancy_collinearity", "modeling_simplicity", "ethical_sensitive"):
        ExcludedFeature(name="x", exclusion_type=member, enforcement="advisory", justification="x")


# --- target must be well-formed and defined exactly once -------------------

def test_malformed_target_rejected_missing_task_type() -> None:
    _expect_validation_error(
        lambda: TargetContract(
            name="churn",
            constraints=TargetConstraints(),
            observed=TargetObserved(positive_rate=0.26, class_counts={"0": 1, "1": 1}),
        )
    )


def test_target_cannot_also_appear_in_columns() -> None:
    dup_column = _minimal_column(name="churn")
    _expect_validation_error(lambda: _valid_contract(columns=[dup_column], required_features=[]))


def test_target_cannot_appear_in_required_features() -> None:
    _expect_validation_error(lambda: _valid_contract(required_features=["monthly_charges", "churn"]))


# --- coverage / cross-reference requirements --------------------------------

def test_required_features_must_reference_declared_columns() -> None:
    _expect_validation_error(lambda: _valid_contract(required_features=["not_a_declared_column"]))


def test_excluded_features_must_reference_declared_columns() -> None:
    bogus = ExcludedFeature(
        name="not_a_declared_column", exclusion_type=ExclusionType.IDENTIFIER,
        enforcement=EnforcementLevel.HARD, justification="x",
    )
    _expect_validation_error(lambda: _valid_contract(excluded_features=[bogus]))


def test_hard_excluded_column_cannot_also_be_required() -> None:
    excluded = ExcludedFeature(
        name="monthly_charges", exclusion_type=ExclusionType.IDENTIFIER,
        enforcement=EnforcementLevel.HARD, justification="x",
    )
    _expect_validation_error(
        lambda: _valid_contract(excluded_features=[excluded], required_features=["monthly_charges"])
    )


def test_advisory_excluded_column_may_also_be_required() -> None:
    # Advisory (WARN-only) exclusions are not a hard conflict (§E.4).
    excluded = ExcludedFeature(
        name="monthly_charges", exclusion_type=ExclusionType.REDUNDANCY_COLLINEARITY,
        enforcement=EnforcementLevel.ADVISORY, justification="x",
    )
    contract = _valid_contract(excluded_features=[excluded], required_features=["monthly_charges"])
    assert contract.excluded_features[0].enforcement == EnforcementLevel.ADVISORY


def test_primary_key_must_reference_declared_columns() -> None:
    bad_pk = PrimaryKey(
        columns=["not_a_declared_column"],
        constraints=PrimaryKeyConstraints(unique=UniqueConstraint(value=True, justification="x")),
    )
    _expect_validation_error(lambda: _valid_contract(primary_key=bad_pk))


def test_duplicate_column_names_rejected() -> None:
    dupes = [_minimal_column(name="monthly_charges"), _minimal_column(name="monthly_charges")]
    _expect_validation_error(lambda: _valid_contract(columns=dupes, required_features=[]))


def test_integrity_column_order_must_match_declared_columns() -> None:
    bad_integrity = Integrity(
        clean_data_sha256="a" * 64, row_count=1, column_count=3,
        column_order=["churn", "monthly_charges", "an_undeclared_column"],
    )
    _expect_validation_error(lambda: _valid_contract(integrity=bad_integrity))


# --- justification enforcement (§Phase 3 required semantic rules) ----------

def test_business_range_without_justification_rejected() -> None:
    _expect_validation_error(lambda: BusinessRangeConstraint(min=0, max=None))  # type: ignore[call-arg]


def test_business_range_with_empty_justification_rejected() -> None:
    _expect_validation_error(lambda: BusinessRangeConstraint(min=0, max=None, justification=""))


def test_business_range_with_whitespace_only_justification_rejected() -> None:
    _expect_validation_error(lambda: BusinessRangeConstraint(min=0, max=None, justification="   "))


def test_business_range_needs_at_least_one_bound() -> None:
    _expect_validation_error(lambda: BusinessRangeConstraint(min=None, max=None, justification="x"))


def test_unit_without_evidence_rejected() -> None:
    _expect_validation_error(lambda: UnitConstraint(value="months", evidence=""))  # type: ignore[call-arg]


def test_unit_currency_unspecified_is_a_legitimate_honest_state() -> None:
    # Phase 2 decision (data/README.md §6.2): no invented USD. This must
    # construct cleanly — the neutral state is not itself an error.
    unit = UnitConstraint(
        value="currency_unspecified",
        evidence="the source documentation does not state a currency",
    )
    assert unit.value == "currency_unspecified"


def test_closed_domain_without_justification_rejected() -> None:
    _expect_validation_error(lambda: ClosedDomainConstraint(values=["a", "b"], justification=""))


def test_closed_domain_empty_values_rejected() -> None:
    _expect_validation_error(lambda: ClosedDomainConstraint(values=[], justification="x"))


def test_scale_drift_without_justification_rejected() -> None:
    _expect_validation_error(lambda: ScaleDriftConstraint(median_rel_tolerance=0.25, justification=""))


def test_scale_drift_tolerance_must_be_in_zero_to_one_range() -> None:
    _expect_validation_error(lambda: ScaleDriftConstraint(median_rel_tolerance=0, justification="x"))
    _expect_validation_error(lambda: ScaleDriftConstraint(median_rel_tolerance=1.5, justification="x"))


def test_unique_constraint_without_justification_rejected() -> None:
    _expect_validation_error(lambda: UniqueConstraint(value=True, justification=""))


# --- "missing constraint means no enforcement" is representable -----------

def test_all_constraints_may_be_absent() -> None:
    bare = ColumnConstraints()
    assert bare.dtype is None
    assert bare.nullable is None
    assert bare.unit is None
    assert bare.business_range is None
    assert bare.closed_domain is None
    assert bare.scale_drift is None


# --- no invented measurement fields in a constraints/semantic context ------

def test_column_constraints_rejects_a_measured_looking_extra_field() -> None:
    _expect_validation_error(lambda: ColumnConstraints(min=18.25))  # type: ignore[call-arg]


def test_column_contract_rejects_unknown_top_level_field() -> None:
    _expect_validation_error(
        lambda: ColumnContract(
            name="x", semantic_type=SemanticType.NUMERIC,
            observed=ColumnObserved(dtype="float64", null_count=0, unique_count=1),
            constraints=ColumnConstraints(),
            row_count=100,  # not a per-column field — must be rejected
        )
    )


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
