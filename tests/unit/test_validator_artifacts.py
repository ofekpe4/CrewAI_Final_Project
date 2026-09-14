"""Unit tests — validation gate, check family A (artifacts).

PROJECT_PLAN.md §F.1: "4 הארטיפקטים קיימים ולא ריקים · החוזה JSON תקין ·
תואם ל-Pydantic · ה-CSV נטען". This file proves every one of those, plus the
"prerequisite gating" behaviour documented in `contract/validator.py`'s
module docstring: families B–G do not run at all when the contract or the
CSV never became usable, but family A itself always finishes.

Runnable two ways:
  * ``pytest tests/unit/test_validator_artifacts.py``
  * ``python tests/unit/test_validator_artifacts.py``
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
from tests.fixtures.gate_fixtures import CONTRACT_JSON, FIXTURE_CSV  # noqa: E402


def _findings_by_id(report, check_id: str):
    return [f for f in report.findings if f.check_id == check_id]


# --- missing files -----------------------------------------------------------

def test_missing_csv_file_is_an_artifact_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = run_validation_gate(Path(tmp) / "does_not_exist.csv", CONTRACT_JSON, run_id="t")
    assert report.passed is False
    hits = _findings_by_id(report, "ARTIFACTS_CSV_FILE_EXISTS")
    assert len(hits) == 1 and hits[0].severity == "ERROR"


def test_missing_contract_file_is_an_artifact_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = run_validation_gate(FIXTURE_CSV, Path(tmp) / "does_not_exist.json", run_id="t")
    assert report.passed is False
    hits = _findings_by_id(report, "ARTIFACTS_CONTRACT_FILE_EXISTS")
    assert len(hits) == 1 and hits[0].severity == "ERROR"


def test_missing_csv_and_missing_contract_are_both_reported_in_one_run() -> None:
    """Family A does not stop at the first missing artifact."""
    with tempfile.TemporaryDirectory() as tmp:
        report = run_validation_gate(
            Path(tmp) / "no.csv", Path(tmp) / "no.json", run_id="t"
        )
    assert report.passed is False
    assert _findings_by_id(report, "ARTIFACTS_CSV_FILE_EXISTS")
    assert _findings_by_id(report, "ARTIFACTS_CONTRACT_FILE_EXISTS")


# --- empty files ---------------------------------------------------------------

def test_empty_csv_file_is_an_artifact_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "empty.csv"
        empty.write_bytes(b"")
        report = run_validation_gate(empty, CONTRACT_JSON, run_id="t")
    assert report.passed is False
    hits = _findings_by_id(report, "ARTIFACTS_CSV_FILE_NOT_EMPTY")
    assert len(hits) == 1 and hits[0].severity == "ERROR"


def test_empty_contract_file_is_an_artifact_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "empty.json"
        empty.write_bytes(b"")
        report = run_validation_gate(FIXTURE_CSV, empty, run_id="t")
    assert report.passed is False
    hits = _findings_by_id(report, "ARTIFACTS_CONTRACT_FILE_NOT_EMPTY")
    assert len(hits) == 1 and hits[0].severity == "ERROR"


# --- malformed / invalid contract JSON ------------------------------------------

def test_malformed_contract_json_fails_to_parse() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        report = run_validation_gate(FIXTURE_CSV, bad, run_id="t")
    assert report.passed is False
    hits = _findings_by_id(report, "ARTIFACTS_CONTRACT_JSON_PARSES")
    assert len(hits) == 1 and hits[0].severity == "ERROR"


def test_contract_json_that_parses_but_violates_the_schema_fails_schema_validation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad_schema.json"
        bad.write_text('{"this_is": "not a DatasetContract"}', encoding="utf-8")
        report = run_validation_gate(FIXTURE_CSV, bad, run_id="t")
    assert report.passed is False
    hits = _findings_by_id(report, "ARTIFACTS_CONTRACT_SCHEMA_VALID")
    assert len(hits) == 1 and hits[0].severity == "ERROR"


# --- unreadable CSV -------------------------------------------------------------

def test_unloadable_csv_fails_to_load() -> None:
    """A file pandas genuinely cannot parse as tabular data."""
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.csv"
        # A single unterminated quoted field is enough to break the C parser.
        bad.write_text('a,b,c\n"unterminated,1,2\n', encoding="utf-8")
        report = run_validation_gate(bad, CONTRACT_JSON, run_id="t")
    assert report.passed is False
    assert _findings_by_id(report, "ARTIFACTS_CSV_LOADS")


# --- the happy path --------------------------------------------------------------

def test_a_real_valid_pair_passes_every_artifact_check() -> None:
    report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, run_id="t")
    for check_id in (
        "ARTIFACTS_CSV_FILE_EXISTS", "ARTIFACTS_CSV_FILE_NOT_EMPTY", "ARTIFACTS_CSV_LOADS",
        "ARTIFACTS_CONTRACT_FILE_EXISTS", "ARTIFACTS_CONTRACT_FILE_NOT_EMPTY",
        "ARTIFACTS_CONTRACT_JSON_PARSES", "ARTIFACTS_CONTRACT_SCHEMA_VALID",
    ):
        assert not _findings_by_id(report, check_id), f"{check_id} should not have failed"


# --- prerequisite gating: B-G do not run without a usable contract + CSV --------

def test_families_b_through_g_do_not_run_when_the_contract_fails_to_parse() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        report = run_validation_gate(FIXTURE_CSV, bad, run_id="t")
    families = {f.check_family for f in report.findings}
    assert families == {"artifacts"}


def test_families_b_through_g_do_not_run_when_the_csv_fails_to_load() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.csv"
        bad.write_text('a,b,c\n"unterminated,1,2\n', encoding="utf-8")
        report = run_validation_gate(bad, CONTRACT_JSON, run_id="t")
    families = {f.check_family for f in report.findings}
    assert families <= {"artifacts", "integrity"}
    assert "schema" not in families and "target" not in families and "modeling" not in families


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
