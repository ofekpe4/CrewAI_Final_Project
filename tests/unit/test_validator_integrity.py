"""Unit tests — validation gate, check family F (integrity).

PROJECT_PLAN.md §F.1: `sha256(clean_data.csv) == integrity.clean_data_sha256`.
Must hash the ACTUAL candidate file's bytes on disk — never an in-memory
DataFrame re-serialization (§Phase 4 explicit instruction).

Runnable two ways:
  * ``pytest tests/unit/test_validator_integrity.py``
  * ``python tests/unit/test_validator_integrity.py``
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

from harbor_vale.contract.validator import run_validation_gate  # noqa: E402
from tests.fixtures.gate_fixtures import CONTRACT_JSON, FIXTURE_CSV  # noqa: E402


def _findings(report, check_id: str):
    return [f for f in report.findings if f.check_id == check_id]


def test_matching_bytes_pass_integrity() -> None:
    report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, run_id="t")
    assert not _findings(report, "INTEGRITY_SHA256_MATCH")


def test_matching_bytes_in_a_different_file_still_pass() -> None:
    """Integrity checks the BYTES, not the path — a byte-identical copy at
    a different location must pass exactly like the original."""
    with tempfile.TemporaryDirectory() as tmp:
        copy_path = Path(tmp) / "copy.csv"
        shutil.copyfile(FIXTURE_CSV, copy_path)
        report = run_validation_gate(copy_path, CONTRACT_JSON, run_id="t")
    assert not _findings(report, "INTEGRITY_SHA256_MATCH")


def test_a_single_changed_byte_fails_integrity() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        mutated_path = Path(tmp) / "mutated.csv"
        shutil.copyfile(FIXTURE_CSV, mutated_path)
        with mutated_path.open("a", encoding="utf-8") as fh:
            fh.write("\n")  # a single trailing byte is enough
        report = run_validation_gate(mutated_path, CONTRACT_JSON, run_id="t")
    assert report.passed is False
    hits = _findings(report, "INTEGRITY_SHA256_MATCH")
    assert len(hits) == 1 and hits[0].severity == "ERROR"


def test_integrity_hashes_the_actual_file_bytes_not_a_reserialized_dataframe() -> None:
    """A CSV that is logically identical once loaded by pandas, but has
    different raw bytes (e.g. different line endings), must FAIL — proving
    the check hashes the file, not `df.to_csv()`'s own re-serialization."""
    with tempfile.TemporaryDirectory() as tmp:
        original_bytes = FIXTURE_CSV.read_bytes()
        crlf_path = Path(tmp) / "crlf.csv"
        crlf_path.write_bytes(original_bytes.replace(b"\n", b"\r\n"))
        report = run_validation_gate(crlf_path, CONTRACT_JSON, run_id="t")
        expected_hash = hashlib.sha256(crlf_path.read_bytes()).hexdigest()
    hits = _findings(report, "INTEGRITY_SHA256_MATCH")
    assert len(hits) == 1
    assert hits[0].observed == expected_hash


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
