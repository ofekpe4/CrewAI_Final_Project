"""Unit tests for `harbor_vale.contract.builder` (PROJECT_PLAN.md §D.3 point 8).

Focus: the builder is genuinely exercised against a **real CSV file on
disk** (`tests/fixtures/telco_contract_fixture.csv` — see
`tests/fixtures/README.md`; NOT the production `clean_data.csv`, which does
not exist until Phase 5+/6+). SHA256 is deterministic and bytes-based;
row/column counts, column order, and per-column observed statistics all come
from the actual file; the semantic `constraints` in the output are exactly
what the (already-validated) `ContractDraft` declared, never something the
builder invented; and column coverage between the draft and the real CSV is
enforced.

Runnable two ways:
  * ``pytest tests/unit/test_contract_builder.py``   (once pytest is installed)
  * ``python tests/unit/test_contract_builder.py``   (no test dependency required)
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd  # noqa: E402

from harbor_vale.contract.builder import ContractBuildError, build_contract  # noqa: E402
from harbor_vale.plans.contract_draft import validate_contract_draft  # noqa: E402
from tests.fixtures.build_example_contract import build_draft  # noqa: E402

FIXTURE_CSV = _ROOT / "tests" / "fixtures" / "telco_contract_fixture.csv"


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_draft():
    ok, draft = validate_contract_draft(build_draft())
    assert ok, f"fixture draft should be valid: {draft}"
    return draft


def _build(csv_path: Path = FIXTURE_CSV, **overrides):
    kwargs = dict(
        contract_version="1.0.0",
        run_id="test-run",
        created_by="tests.unit.test_contract_builder",
        dataset_name="telco_customer_churn",
        source_documentation_url="https://github.com/IBM/telco-customer-churn-on-icp4d",
    )
    kwargs.update(overrides)
    return build_contract(_validated_draft(), csv_path, **kwargs)


# --- builds from a real file -------------------------------------------------

def test_builder_builds_from_a_real_csv_file() -> None:
    assert FIXTURE_CSV.is_file(), "fixture CSV must exist on disk for this test to be real"
    contract = _build()
    assert contract.dataset_name == "telco_customer_churn"


def test_row_and_column_counts_are_measured_correctly() -> None:
    df = pd.read_csv(FIXTURE_CSV)
    contract = _build()
    assert contract.integrity.row_count == df.shape[0] == 30
    assert contract.integrity.column_count == df.shape[1] == 21


def test_column_order_matches_the_csv_header() -> None:
    df = pd.read_csv(FIXTURE_CSV)
    contract = _build()
    assert contract.integrity.column_order == list(df.columns)


# --- SHA256 --------------------------------------------------------------

def test_sha256_matches_an_independently_computed_hash() -> None:
    expected = _sha256_of(FIXTURE_CSV)
    contract = _build()
    assert contract.integrity.clean_data_sha256 == expected


def test_sha256_is_stable_across_repeated_builds() -> None:
    first = _build().integrity.clean_data_sha256
    second = _build().integrity.clean_data_sha256
    assert first == second


def test_sha256_changes_when_the_bytes_change() -> None:
    original_hash = _build().integrity.clean_data_sha256
    with tempfile.TemporaryDirectory() as tmp:
        mutated_path = Path(tmp) / "mutated.csv"
        shutil.copyfile(FIXTURE_CSV, mutated_path)
        with mutated_path.open("a", encoding="utf-8") as fh:
            fh.write("\n")  # a single trailing byte is enough to change the hash
        mutated_hash = _build(csv_path=mutated_path).integrity.clean_data_sha256
    assert mutated_hash != original_hash


def test_identical_bytes_in_a_different_file_produce_the_same_hash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        copy_path = Path(tmp) / "copy.csv"
        shutil.copyfile(FIXTURE_CSV, copy_path)
        copy_hash = _build(csv_path=copy_path).integrity.clean_data_sha256
    original_hash = _build().integrity.clean_data_sha256
    assert copy_hash == original_hash


# --- observed stats come from the actual data -------------------------------

def test_observed_stats_match_direct_pandas_measurement() -> None:
    df = pd.read_csv(FIXTURE_CSV)
    contract = _build()
    monthly = next(c for c in contract.columns if c.name == "monthly_charges")
    assert monthly.observed.min == float(df["monthly_charges"].min())
    assert monthly.observed.max == float(df["monthly_charges"].max())
    assert monthly.observed.null_count == int(df["monthly_charges"].isnull().sum())
    assert monthly.observed.unique_count == int(df["monthly_charges"].nunique())


def test_target_observed_matches_direct_pandas_measurement() -> None:
    df = pd.read_csv(FIXTURE_CSV)
    contract = _build()
    expected_rate = float((df["churn"] == df["churn"].max()).mean())
    assert contract.target.observed.positive_rate == expected_rate
    assert contract.target.observed.class_counts["1"] == int((df["churn"] == 1).sum())
    assert contract.target.observed.class_counts["0"] == int((df["churn"] == 0).sum())


def test_categorical_observed_value_distribution_matches_pandas() -> None:
    df = pd.read_csv(FIXTURE_CSV)
    contract = _build()
    contract_type = next(c for c in contract.columns if c.name == "contract_type")
    expected = df["contract_type"].value_counts(normalize=True).to_dict()
    assert contract_type.observed.value_distribution == {str(k): v for k, v in expected.items()}


# --- semantic constraints are preserved, not derived ------------------------

def test_semantic_constraints_are_carried_through_unchanged_from_the_draft() -> None:
    draft = _validated_draft()
    contract = _build()
    draft_monthly = next(c for c in draft.columns if c.name == "monthly_charges")
    built_monthly = next(c for c in contract.columns if c.name == "monthly_charges")
    assert built_monthly.constraints.business_range == draft_monthly.business_range
    assert built_monthly.constraints.unit == draft_monthly.unit
    assert built_monthly.constraints.scale_drift == draft_monthly.scale_drift
    assert built_monthly.constraints.nullable == draft_monthly.nullable


def test_required_excluded_and_assumptions_are_carried_through() -> None:
    draft = _validated_draft()
    contract = _build()
    assert contract.required_features == list(draft.required_features)
    assert [f.name for f in contract.excluded_features] == [f.name for f in draft.excluded_features]
    assert contract.assumptions == list(draft.assumptions)


# --- ContractDraft structurally cannot carry measured values ----------------

def test_contract_draft_has_no_measurement_fields_to_override_with() -> None:
    draft = _validated_draft()
    column = draft.columns[0]
    for forbidden in ("min", "max", "median", "row_count", "sha256", "observed"):
        assert not hasattr(column, forbidden), (
            f"ContractDraft column model must never carry a {forbidden!r} field"
        )
    assert not hasattr(draft, "row_count")
    assert not hasattr(draft, "sha256")


# --- coverage enforcement ----------------------------------------------------

def test_all_csv_columns_are_covered_in_the_built_contract() -> None:
    df = pd.read_csv(FIXTURE_CSV)
    contract = _build()
    covered = {c.name for c in contract.columns} | {contract.target.name}
    assert covered == set(df.columns)


def test_missing_column_declaration_raises_contract_build_error() -> None:
    draft = _validated_draft()
    # Simulate a draft that never declared `payment_method`.
    truncated = draft.model_copy(
        update={"columns": [c for c in draft.columns if c.name != "payment_method"]}
    )
    try:
        build_contract(
            truncated, FIXTURE_CSV,
            contract_version="1.0.0", run_id="t", created_by="test",
            dataset_name="telco_customer_churn", source_documentation_url="https://example.invalid",
        )
    except ContractBuildError as exc:
        assert "payment_method" in str(exc)
    else:
        raise AssertionError("expected ContractBuildError for an undeclared CSV column")


def test_target_missing_from_csv_raises_contract_build_error() -> None:
    draft = _validated_draft()
    bad_target = draft.target.model_copy(update={"name": "not_a_real_column"})
    bad_draft = draft.model_copy(update={"target": bad_target})
    try:
        build_contract(
            bad_draft, FIXTURE_CSV,
            contract_version="1.0.0", run_id="t", created_by="test",
            dataset_name="telco_customer_churn", source_documentation_url="https://example.invalid",
        )
    except ContractBuildError as exc:
        assert "not_a_real_column" in str(exc)
    else:
        raise AssertionError("expected ContractBuildError for a target absent from the CSV")


def test_missing_csv_file_raises_contract_build_error() -> None:
    try:
        build_contract(
            _validated_draft(), _ROOT / "tests" / "fixtures" / "does_not_exist.csv",
            contract_version="1.0.0", run_id="t", created_by="test",
            dataset_name="telco_customer_churn", source_documentation_url="https://example.invalid",
        )
    except ContractBuildError:
        pass
    else:
        raise AssertionError("expected ContractBuildError for a missing CSV file")


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
