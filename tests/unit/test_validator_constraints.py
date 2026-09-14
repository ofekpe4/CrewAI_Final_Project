"""Unit tests — validation gate, check family D (justified constraints).

PROJECT_PLAN.md §F.1 / §Phase 4 core invariant: ONLY declared constraints are
enforced — `nullable:false` (zero nulls), `business_range` (only if
declared), `closed_domain` (only if declared), primary-key uniqueness (only
if declared unique). The single most important negative case: a value above
`observed.max` alone must NEVER fail (Phase 3's central rule, carried
forward — see `test_observed_not_enforced.py`).

Runnable two ways:
  * ``pytest tests/unit/test_validator_constraints.py``
  * ``python tests/unit/test_validator_constraints.py``
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd  # noqa: E402

from harbor_vale.contract.validator import run_validation_gate  # noqa: E402
from harbor_vale.demo import fault_injection as fi  # noqa: E402
from tests.fixtures.gate_fixtures import CONTRACT_JSON, EDA_REPORT_FIXTURE, FIXTURE_CSV, INSIGHTS_MD_FIXTURE  # noqa: E402


def _findings(report, check_id: str):
    return [f for f in report.findings if f.check_id == check_id]


# --- nullable:false --------------------------------------------------------------

def test_nulls_in_a_nullable_false_column_are_an_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.inject_nulls(FIXTURE_CSV, Path(tmp) / "n.csv", column="contract_type", count=3)
        report = run_validation_gate(out, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert report.passed is False
    hits = _findings(report, "CONSTRAINTS_NULLABLE")
    assert len(hits) == 1 and hits[0].column == "contract_type" and hits[0].observed == 3
    assert hits[0].contract_justification


# --- business_range ----------------------------------------------------------------

def test_business_range_min_violation_is_an_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        df = pd.read_csv(FIXTURE_CSV)
        df.loc[df.index[0], "monthly_charges"] = -5.0
        out = Path(tmp) / "neg.csv"
        df.to_csv(out, index=False)
        report = run_validation_gate(out, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert report.passed is False
    hits = _findings(report, "CONSTRAINTS_BUSINESS_RANGE")
    assert len(hits) == 1 and hits[0].column == "monthly_charges"


def test_business_range_with_no_declared_max_never_rejects_a_high_value() -> None:
    """`monthly_charges.business_range.max` is None in the fixture draft —
    the exact Phase 3 case. A value far above `observed.max` must pass."""
    with tempfile.TemporaryDirectory() as tmp:
        df = pd.read_csv(FIXTURE_CSV)
        future_value = float(df["monthly_charges"].max()) + 500.0
        df.loc[df.index[0], "monthly_charges"] = future_value
        out = Path(tmp) / "future.csv"
        df.to_csv(out, index=False)
        report = run_validation_gate(out, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert not _findings(report, "CONSTRAINTS_BUSINESS_RANGE")


def test_no_violation_from_observed_max_alone() -> None:
    """The literal Phase 3 -> Phase 4 continuity test: run the gate against
    the untouched fixture itself. Every value in it IS the observed max (by
    definition) and none of that triggers a business_range finding."""
    report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert not _findings(report, "CONSTRAINTS_BUSINESS_RANGE")
    assert report.passed is True


# --- closed_domain -------------------------------------------------------------------

def test_closed_domain_violation_on_a_declared_column_is_an_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.unknown_category(FIXTURE_CSV, Path(tmp) / "u.csv", column="internet_service", new_value="Satellite")
        report = run_validation_gate(out, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert report.passed is False
    hits = _findings(report, "CONSTRAINTS_CLOSED_DOMAIN")
    assert len(hits) == 1 and hits[0].column == "internet_service" and "Satellite" in hits[0].observed


# --- primary key uniqueness -----------------------------------------------------------

def test_duplicate_primary_key_values_are_an_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        df = pd.read_csv(FIXTURE_CSV)
        df.loc[df.index[1], "customer_id"] = df.loc[df.index[0], "customer_id"]
        out = Path(tmp) / "dup.csv"
        df.to_csv(out, index=False)
        report = run_validation_gate(out, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert report.passed is False
    hits = _findings(report, "CONSTRAINTS_PRIMARY_KEY_UNIQUE")
    assert len(hits) == 1 and hits[0].observed == 2  # both participating rows counted


def test_unique_primary_key_produces_no_finding() -> None:
    report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert not _findings(report, "CONSTRAINTS_PRIMARY_KEY_UNIQUE")


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
