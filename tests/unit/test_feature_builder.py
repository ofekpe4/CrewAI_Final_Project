"""Unit tests — `plans/feature_plan.py` guardrail + `tools/feature_tools.build_features`
(PROJECT_PLAN.md §G.1).

Proves: a valid plan builds features, hard exclusions are mechanically
blocked, an advisory override requires justification, required features
are enforced, the target is never admitted as a feature, feature ordering
is stable, an invalid transform/encoder is rejected, and the whole feature
layer never needs Crew 1 internal data (only clean_data + contract +
Crew 2's own plan).

Runnable two ways:
  * ``pytest tests/unit/test_feature_builder.py``
  * ``python tests/unit/test_feature_builder.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from harbor_vale.contract.builder import build_contract  # noqa: E402
from harbor_vale.ml.features import FeatureBuildError  # noqa: E402
from harbor_vale.plans.contract_draft import validate_contract_draft  # noqa: E402
from harbor_vale.plans.feature_plan import (  # noqa: E402
    AdvisoryOverride,
    ContractAcknowledgment,
    DerivedFeatureSpec,
    EncoderSpec,
    FeaturePlan,
    TransformSpec,
    validate_feature_plan,
)
from harbor_vale.tools.feature_tools import build_features  # noqa: E402
from tests.fixtures.build_example_contract import build_draft  # noqa: E402
from tests.fixtures.gate_fixtures import FIXTURE_CSV  # noqa: E402


def _contract():
    ok, draft = validate_contract_draft(build_draft())
    assert ok, draft
    return build_contract(
        draft, FIXTURE_CSV, contract_version="1.0.0", run_id="t", created_by="test",
        dataset_name="telco_customer_churn", source_documentation_url="https://example.invalid",
    )


def _ack(contract, **overrides):
    defaults = dict(
        contract_version=contract.contract_version, target_confirmed=True,
        required_features_confirmed=True, excluded_features_respected=["customer_id"],
    )
    defaults.update(overrides)
    return ContractAcknowledgment(**defaults)


# --- valid plan builds features -----------------------------------------------

def test_valid_plan_builds_features() -> None:
    contract = _contract()
    df = pd.read_csv(FIXTURE_CSV)
    plan = FeaturePlan(
        contract_acknowledgment=_ack(contract),
        use_features=list(contract.required_features) + ["senior_citizen"],
        transforms=[TransformSpec(column="monthly_charges", kind="log1p")],
        encoders=[EncoderSpec(column="contract_type", kind="onehot"), EncoderSpec(column="internet_service", kind="onehot")],
    )
    ok, validated = validate_feature_plan(plan, contract=contract)
    assert ok, validated
    result = build_features(df, contract, validated)
    assert result.X.shape[0] == len(df)
    assert set(result.feature_names) == set(plan.use_features)
    transformed = result.preprocessor.fit_transform(result.X)
    assert transformed.shape[0] == len(df)


def test_numeric_column_with_real_nulls_is_imputed_not_crashed() -> None:
    """Phase 7 live-run finding (Session 27): a real cleaned dataset can
    legitimately still carry a null in a numeric column the Feature
    Engineer chooses under an advisory override (e.g. `total_charges`) —
    `StandardScaler` silently passes a NaN through, and no estimator this
    project trains accepts one. `build_preprocessor` must impute (median)
    inside the SAME leakage-safe `Pipeline`, never crash, and never leave
    a NaN in the transformed output — for both a passthrough-numeric
    column and a `transforms`-declared one."""
    contract = _contract()
    df = pd.read_csv(FIXTURE_CSV).copy()
    df.loc[df.index[:3], "total_charges"] = float("nan")  # a genuine, measured null

    plan = FeaturePlan(
        contract_acknowledgment=_ack(contract),
        use_features=list(contract.required_features) + ["total_charges"],
        transforms=[TransformSpec(column="total_charges", kind="log1p")],
        encoders=[EncoderSpec(column="contract_type", kind="onehot"), EncoderSpec(column="internet_service", kind="onehot")],
        advisory_overrides=[AdvisoryOverride(column="total_charges", justification="legitimate redundant signal, not leakage")],
    )
    ok, validated = validate_feature_plan(plan, contract=contract)
    assert ok, validated
    result = build_features(df, contract, validated)
    assert result.X["total_charges"].isnull().sum() == 3  # the raw feature column still carries the real nulls

    import numpy as np

    transformed = result.preprocessor.fit_transform(result.X)
    dense = transformed.toarray() if hasattr(transformed, "toarray") else np.asarray(transformed)
    assert not np.isnan(dense).any(), "no NaN may reach the fitted/transformed output an estimator will train on"


def test_passthrough_numeric_column_with_real_nulls_is_imputed() -> None:
    """Same guarantee as above, for a numeric feature with NO declared
    transform/encoder — the default `StandardScaler` passthrough branch."""
    contract = _contract()
    df = pd.read_csv(FIXTURE_CSV).copy()
    df.loc[df.index[:3], "total_charges"] = float("nan")

    plan = FeaturePlan(
        contract_acknowledgment=_ack(contract),
        use_features=list(contract.required_features) + ["total_charges"],
        encoders=[EncoderSpec(column="contract_type", kind="onehot"), EncoderSpec(column="internet_service", kind="onehot")],
        advisory_overrides=[AdvisoryOverride(column="total_charges", justification="legitimate redundant signal, not leakage")],
    )
    ok, validated = validate_feature_plan(plan, contract=contract)
    assert ok, validated
    result = build_features(df, contract, validated)

    import numpy as np

    transformed = result.preprocessor.fit_transform(result.X)
    dense = transformed.toarray() if hasattr(transformed, "toarray") else np.asarray(transformed)
    assert not np.isnan(dense).any(), "no NaN may reach the fitted/transformed output an estimator will train on"


# --- hard exclusions mechanically blocked --------------------------------------

def test_hard_excluded_feature_is_rejected_by_the_guardrail() -> None:
    contract = _contract()
    plan = FeaturePlan(
        contract_acknowledgment=_ack(contract),
        use_features=list(contract.required_features) + ["customer_id"],  # hard-excluded
    )
    ok, msg = validate_feature_plan(plan, contract=contract)
    assert ok is False
    assert "hard-excluded" in msg


def test_hard_excluded_feature_is_also_mechanically_blocked_at_build_time() -> None:
    """Defense in depth: even a plan that somehow bypassed the guardrail
    (e.g. constructed directly, not through validate_feature_plan) must
    still be mechanically blocked by build_features itself."""
    contract = _contract()
    df = pd.read_csv(FIXTURE_CSV)
    bypassed_plan = FeaturePlan(
        contract_acknowledgment=_ack(contract),
        use_features=list(contract.required_features) + ["customer_id"],
    )
    try:
        build_features(df, contract, bypassed_plan)
    except FeatureBuildError as exc:
        assert "hard-excluded" in str(exc)
    else:
        raise AssertionError("expected FeatureBuildError for a hard-excluded feature")


# --- advisory override requires justification -----------------------------------

def test_advisory_excluded_feature_without_override_is_rejected() -> None:
    contract = _contract()
    plan = FeaturePlan(
        contract_acknowledgment=_ack(contract),
        use_features=list(contract.required_features) + ["total_charges"],  # advisory-excluded
    )
    ok, msg = validate_feature_plan(plan, contract=contract)
    assert ok is False
    assert "advisory-excluded" in msg


def test_advisory_excluded_feature_with_override_is_accepted() -> None:
    contract = _contract()
    plan = FeaturePlan(
        contract_acknowledgment=_ack(contract),
        use_features=list(contract.required_features) + ["total_charges"],
        advisory_overrides=[AdvisoryOverride(column="total_charges", justification="legitimate redundant signal, not leakage")],
    )
    ok, result = validate_feature_plan(plan, contract=contract)
    assert ok, result


def test_advisory_override_referencing_a_non_advisory_column_is_rejected() -> None:
    contract = _contract()
    plan = FeaturePlan(
        contract_acknowledgment=_ack(contract),
        use_features=list(contract.required_features),
        advisory_overrides=[AdvisoryOverride(column="senior_citizen", justification="not actually advisory-excluded")],
    )
    ok, msg = validate_feature_plan(plan, contract=contract)
    assert ok is False
    assert "not an advisory-excluded feature" in msg


# --- required features enforced --------------------------------------------------

def test_missing_required_feature_is_rejected() -> None:
    contract = _contract()
    incomplete = [f for f in contract.required_features if f != "monthly_charges"]
    plan = FeaturePlan(contract_acknowledgment=_ack(contract), use_features=incomplete)
    ok, msg = validate_feature_plan(plan, contract=contract)
    assert ok is False
    assert "monthly_charges" in msg


# --- target never admitted as a feature -----------------------------------------

def test_target_in_use_features_is_rejected() -> None:
    contract = _contract()
    plan = FeaturePlan(
        contract_acknowledgment=_ack(contract),
        use_features=list(contract.required_features) + [contract.target.name],
    )
    ok, msg = validate_feature_plan(plan, contract=contract)
    assert ok is False
    assert "target" in msg.lower()


def test_target_in_use_features_is_also_mechanically_blocked_at_build_time() -> None:
    contract = _contract()
    df = pd.read_csv(FIXTURE_CSV)
    bypassed_plan = FeaturePlan(
        contract_acknowledgment=_ack(contract),
        use_features=list(contract.required_features) + [contract.target.name],
    )
    try:
        build_features(df, contract, bypassed_plan)
    except FeatureBuildError as exc:
        assert "target" in str(exc).lower()
    else:
        raise AssertionError("expected FeatureBuildError for target-as-feature")


# --- stable feature ordering ------------------------------------------------------

def test_feature_ordering_is_stable_across_repeated_builds() -> None:
    contract = _contract()
    df = pd.read_csv(FIXTURE_CSV)
    plan = FeaturePlan(
        contract_acknowledgment=_ack(contract),
        use_features=list(contract.required_features) + ["senior_citizen"],
        encoders=[EncoderSpec(column="contract_type", kind="onehot"), EncoderSpec(column="internet_service", kind="onehot")],
    )
    ok, validated = validate_feature_plan(plan, contract=contract)
    assert ok
    result1 = build_features(df, contract, validated)
    result2 = build_features(df, contract, validated)
    assert result1.feature_names == result2.feature_names
    assert list(result1.X.columns) == list(result2.X.columns)


# --- invalid transform/encoder rejected ------------------------------------------

def test_unsupported_encoder_kind_is_a_structural_rejection() -> None:
    try:
        EncoderSpec(column="contract_type", kind="target_encoding")  # not in EncoderKind
    except ValidationError:
        pass
    else:
        raise AssertionError("expected ValidationError for an unsupported encoder kind")


def test_unsupported_transform_kind_is_a_structural_rejection() -> None:
    try:
        TransformSpec(column="monthly_charges", kind="zscore_but_wrong_name")
    except ValidationError:
        pass
    else:
        raise AssertionError("expected ValidationError for an unsupported transform kind")


def test_categorical_feature_with_no_encoder_is_a_build_error() -> None:
    """A categorical use_feature that the plan never assigns an encoder to
    is a defensible FeatureBuildError, not a silent numeric-coercion guess."""
    contract = _contract()
    df = pd.read_csv(FIXTURE_CSV)
    plan = FeaturePlan(
        contract_acknowledgment=_ack(contract),
        use_features=list(contract.required_features),  # contract_type/internet_service have no encoders
    )
    ok, validated = validate_feature_plan(plan, contract=contract)
    assert ok  # structurally/contractually fine
    try:
        build_features(df, contract, validated)
    except FeatureBuildError as exc:
        assert "not numeric" in str(exc)
    else:
        raise AssertionError("expected FeatureBuildError for an unencoded categorical feature")


# --- derived features -------------------------------------------------------------

def test_derived_ratio_feature_is_computed() -> None:
    contract = _contract()
    df = pd.read_csv(FIXTURE_CSV)
    plan = FeaturePlan(
        contract_acknowledgment=_ack(contract),
        use_features=list(contract.required_features),
        derived=[DerivedFeatureSpec(name="avg_spend", kind="ratio", numerator="total_charges", denominator="tenure_months", description="billing rate proxy")],
        encoders=[EncoderSpec(column="contract_type", kind="onehot"), EncoderSpec(column="internet_service", kind="onehot")],
        advisory_overrides=[AdvisoryOverride(column="total_charges", justification="only used to derive avg_spend, not directly")],
    )
    # total_charges itself is not in use_features, only referenced by `derived` — no override needed there,
    # but the derived feature computation must still work using the raw column.
    ok, validated = validate_feature_plan(plan, contract=contract)
    assert ok, validated
    result = build_features(df, contract, validated)
    assert "avg_spend" in result.X.columns
    # tenure_months == 0 rows must not divide by zero
    assert result.X["avg_spend"].isnull().sum() == 0


# --- no Crew 1 internal data required -------------------------------------------

def test_feature_building_needs_only_clean_data_and_contract_and_plan() -> None:
    """No parameter here is a path into data/raw/ or artifacts/crew1/_internal/ —
    build_features's signature itself proves this (clean_df, contract, plan)."""
    import inspect

    sig = inspect.signature(build_features)
    assert list(sig.parameters) == ["clean_df", "contract", "plan"]


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
