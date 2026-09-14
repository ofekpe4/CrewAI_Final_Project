"""Unit tests — validation gate, aggregate behaviour (§F.2 decision rule).

`passed = (errors == 0)`. WARN findings never fail the gate. The gate runs
every applicable check and collects every finding — it does not stop at the
first ERROR. `errors`/`warnings`/`passed` are always derived deterministically
from `findings`, never set independently.

Runnable two ways:
  * ``pytest tests/unit/test_validator_aggregate.py``
  * ``python tests/unit/test_validator_aggregate.py``
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


def test_a_clean_candidate_passes_with_zero_errors_and_zero_warnings() -> None:
    report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert report.passed is True
    assert report.errors == 0
    assert report.warnings == 0
    assert report.findings == []
    assert report.checks_run > 0


def test_warnings_alone_never_fail_the_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.rename_column(FIXTURE_CSV, Path(tmp) / "r.csv", old_name="gender", new_name="sex")
        # `rename_column` also changes the file's bytes, which is an
        # unrelated integrity ERROR — isolate the WARN-only claim by
        # checking the *counts*, not overall `passed`, against a report
        # that has warnings but ALSO a schema-order WARN and NO errors from
        # the rename itself; use `contract_only_change` instead, which is
        # the Plan's own designed WARN-only scenario.
        from harbor_vale.contract.schema import DatasetContract  # noqa: F401

        contract_out = fi.contract_only_change(CONTRACT_JSON, Path(tmp) / "c.json", drop_column="gender")
        report = run_validation_gate(FIXTURE_CSV, contract_out, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert report.errors == 0
    assert report.warnings > 0
    assert report.passed is True


def test_any_single_error_fails_the_gate_even_with_zero_warnings() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.inject_nulls(FIXTURE_CSV, Path(tmp) / "n.csv", column="contract_type", count=1)
        report = run_validation_gate(out, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert report.errors >= 1
    assert report.passed is False


def test_multiple_independent_errors_are_all_collected_in_one_report() -> None:
    """Corrupt several unrelated things in one candidate CSV and confirm the
    gate reports ALL of them, not just the first one it happens to hit."""
    with tempfile.TemporaryDirectory() as tmp:
        df = pd.read_csv(FIXTURE_CSV)
        df.loc[df.index[0], "monthly_charges"] = -1.0  # business_range violation
        df.loc[df.index[1], "contract_type"] = None  # nullable violation
        df.loc[df.index[2], "internet_service"] = "Satellite"  # closed_domain violation
        out = Path(tmp) / "multi_broken.csv"
        df.to_csv(out, index=False)
        report = run_validation_gate(out, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")

    check_ids = {f.check_id for f in report.findings}
    assert "CONSTRAINTS_BUSINESS_RANGE" in check_ids
    assert "CONSTRAINTS_NULLABLE" in check_ids
    assert "CONSTRAINTS_CLOSED_DOMAIN" in check_ids
    assert "INTEGRITY_SHA256_MATCH" in check_ids
    assert report.passed is False
    assert report.errors == len(check_ids)  # every one of these four is an ERROR


def test_checks_run_and_finding_counts_agree_with_errors_and_warnings_fields() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.rename_column(FIXTURE_CSV, Path(tmp) / "r.csv", old_name="gender", new_name="sex")
        report = run_validation_gate(out, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    actual_errors = sum(1 for f in report.findings if f.severity == "ERROR")
    actual_warnings = sum(1 for f in report.findings if f.severity == "WARN")
    assert report.errors == actual_errors
    assert report.warnings == actual_warnings
    assert report.passed == (report.errors == 0)
    assert report.checks_run >= len(report.findings)


def test_run_id_and_contract_version_are_stamped_on_the_report() -> None:
    report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="my-custom-run-id")
    assert report.run_id == "my-custom-run-id"
    assert report.contract_version == "1.0.0"


def test_fault_injection_defaults_to_none_on_a_real_run() -> None:
    report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert report.fault_injection is None


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
