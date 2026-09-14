"""Unit tests — validation gate, check family B (schema).

PROJECT_PLAN.md §F.1: every contract-declared column exists in the CSV ·
dtype compatible (with safe conversions) · unexpected column → WARN ·
column-order mismatch → WARN · hard-excluded feature missing → ERROR,
advisory-excluded → WARN. Uses `demo/fault_injection.py` to build the
candidate CSVs — the same helpers the Phase 4 acceptance review expects to
be test-exercised, never the checked-in fixture itself.

Runnable two ways:
  * ``pytest tests/unit/test_validator_schema.py``
  * ``python tests/unit/test_validator_schema.py``
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale.contract.validator import run_validation_gate  # noqa: E402
from harbor_vale.demo import fault_injection as fi  # noqa: E402
from tests.fixtures.gate_fixtures import CONTRACT_JSON, FIXTURE_CSV  # noqa: E402


def _findings(report, check_id: str):
    return [f for f in report.findings if f.check_id == check_id]


# --- missing declared column: default policy is ERROR --------------------------

def test_missing_declared_column_is_an_error_by_default() -> None:
    """`monthly_charges` is required and not excluded — its absence must ERROR."""
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.drop_required_column(FIXTURE_CSV, Path(tmp) / "d.csv", column="monthly_charges")
        report = run_validation_gate(out, CONTRACT_JSON, run_id="t")
    assert report.passed is False
    hits = _findings(report, "SCHEMA_MISSING_COLUMN")
    assert any(f.column == "monthly_charges" and f.severity == "ERROR" for f in hits)


def test_missing_required_feature_is_an_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.drop_required_column(FIXTURE_CSV, Path(tmp) / "d.csv", column="internet_service")
        report = run_validation_gate(out, CONTRACT_JSON, run_id="t")
    assert report.passed is False
    assert any(f.column == "internet_service" for f in _findings(report, "SCHEMA_MISSING_COLUMN"))


# --- hard vs advisory excluded feature ------------------------------------------

def test_missing_hard_excluded_feature_is_still_an_error() -> None:
    """`customer_id` is hard-excluded — hard means "must not be *used*", not
    "may be *absent*"; its own absence is still a genuine missing-column ERROR."""
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.drop_required_column(FIXTURE_CSV, Path(tmp) / "d.csv", column="customer_id")
        report = run_validation_gate(out, CONTRACT_JSON, run_id="t")
    assert report.passed is False
    hits = _findings(report, "SCHEMA_MISSING_COLUMN")
    assert any(f.column == "customer_id" and f.severity == "ERROR" for f in hits)


def test_missing_advisory_excluded_feature_is_only_a_warning() -> None:
    """`total_charges` is advisory-excluded (redundancy_collinearity) — its
    absence must downgrade to WARN, not block the gate."""
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.drop_required_column(FIXTURE_CSV, Path(tmp) / "d.csv", column="total_charges")
        report = run_validation_gate(out, CONTRACT_JSON, run_id="t")
    hits = _findings(report, "SCHEMA_MISSING_COLUMN")
    assert any(f.column == "total_charges" and f.severity == "WARN" for f in hits)
    assert not any(f.column == "total_charges" and f.severity == "ERROR" for f in hits)
    # NOTE: `report.passed` is still False here — dropping a column changes
    # the file's bytes, which is a genuine, unrelated INTEGRITY_SHA256_MATCH
    # ERROR. The claim under test is narrower: THIS schema finding, on its
    # own, is a WARN, not an ERROR — proven directly on `hits` above.


# --- unexpected / unknown column -------------------------------------------------

def test_unexpected_column_is_a_warning_by_default_policy() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.rename_column(FIXTURE_CSV, Path(tmp) / "r.csv", old_name="gender", new_name="sex")
        report = run_validation_gate(out, CONTRACT_JSON, run_id="t")
    hits = _findings(report, "SCHEMA_UNKNOWN_COLUMN")
    assert any(f.column == "sex" and f.severity == "WARN" for f in hits)


# --- column order ----------------------------------------------------------------

def test_column_order_mismatch_is_a_warning_and_does_not_fail_the_gate() -> None:
    import pandas as pd

    with tempfile.TemporaryDirectory() as tmp:
        df = pd.read_csv(FIXTURE_CSV)
        reordered = df[list(reversed(df.columns))]
        out = Path(tmp) / "reordered.csv"
        reordered.to_csv(out, index=False)
        report = run_validation_gate(out, CONTRACT_JSON, run_id="t")
    hits = _findings(report, "SCHEMA_COLUMN_ORDER")
    assert len(hits) == 1 and hits[0].severity == "WARN"
    assert not any(f.severity == "ERROR" for f in report.findings if f.check_id == "SCHEMA_COLUMN_ORDER")


def test_matching_column_order_produces_no_finding() -> None:
    report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, run_id="t")
    assert not _findings(report, "SCHEMA_COLUMN_ORDER")


# --- dtype compatibility ----------------------------------------------------------

def test_incompatible_dtype_change_is_a_schema_error() -> None:
    """`monthly_charges` is declared float64; casting it to int64 changes its
    *logical family* (floating -> integer), which must ERROR."""
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.change_dtype(FIXTURE_CSV, Path(tmp) / "c.csv", column="monthly_charges", dtype="int64")
        report = run_validation_gate(out, CONTRACT_JSON, run_id="t")
    assert report.passed is False
    hits = _findings(report, "SCHEMA_DTYPE_COMPATIBLE")
    assert any(f.column == "monthly_charges" and f.severity == "ERROR" for f in hits)


def test_equivalent_text_dtype_family_is_not_flagged() -> None:
    """pandas 3.0.5 may report a text column as `str`, not the historical
    `object` (docs/architecture.md §Known Issues). `gender` is declared
    dtype-less in the fixture draft, but this test proves the *family*
    comparison directly: `object` and `str` must compare equal."""
    from harbor_vale.contract.validator import _dtype_family

    assert _dtype_family("object") == _dtype_family("str")
    assert _dtype_family("object") == _dtype_family("string")


def test_undeclared_dtype_constraint_is_never_checked() -> None:
    """`gender` has no `constraints.dtype` in the fixture draft — no dtype
    check should run for it at all, regardless of its actual measured dtype."""
    report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, run_id="t")
    assert not any(f.column == "gender" for f in _findings(report, "SCHEMA_DTYPE_COMPATIBLE"))


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
