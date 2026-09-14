"""Unit tests — validation gate, check family G (modeling readiness).

PROJECT_PLAN.md §F.1: sufficient rows · ≥2 features · a required-list column
with a single observed value → WARN. Deliberately does NOT train a model or
build any Phase 5+ feature engineering — every check here is a structural or
distributional fact computed directly on the candidate CSV.

Runnable two ways:
  * ``pytest tests/unit/test_validator_modeling.py``
  * ``python tests/unit/test_validator_modeling.py``
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

from harbor_vale.contract.validator import _MIN_ROWS_FOR_MODELING, run_validation_gate  # noqa: E402
from harbor_vale.demo import fault_injection as fi  # noqa: E402
from tests.fixtures.gate_fixtures import CONTRACT_JSON, FIXTURE_CSV  # noqa: E402


def _findings(report, check_id: str):
    return [f for f in report.findings if f.check_id == check_id]


def test_too_few_rows_is_an_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        keep = _MIN_ROWS_FOR_MODELING - 5
        out = fi.truncate_dataset(FIXTURE_CSV, Path(tmp) / "short.csv", keep_rows=keep)
        report = run_validation_gate(out, CONTRACT_JSON, run_id="t")
    assert report.passed is False
    hits = _findings(report, "MODELING_MIN_ROWS")
    assert len(hits) == 1 and hits[0].severity == "ERROR" and hits[0].observed == keep


def test_sufficient_rows_produces_no_finding() -> None:
    report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, run_id="t")
    assert not _findings(report, "MODELING_MIN_ROWS")


def test_constant_required_feature_is_a_warning() -> None:
    """`internet_service` is in `required_features` — force it constant."""
    with tempfile.TemporaryDirectory() as tmp:
        df = pd.read_csv(FIXTURE_CSV)
        df["internet_service"] = "DSL"
        out = Path(tmp) / "constant.csv"
        df.to_csv(out, index=False)
        report = run_validation_gate(out, CONTRACT_JSON, run_id="t")
    hits = _findings(report, "MODELING_CONSTANT_REQUIRED_FEATURE")
    assert len(hits) == 1 and hits[0].column == "internet_service" and hits[0].severity == "WARN"
    assert not any(f.severity == "ERROR" for f in hits)


def test_non_constant_required_features_produce_no_finding() -> None:
    report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, run_id="t")
    assert not _findings(report, "MODELING_CONSTANT_REQUIRED_FEATURE")


def test_truncated_dataset_below_the_row_floor_still_reports_every_other_family() -> None:
    """The `truncate_dataset` §O.3 scenario — verifies the modeling family
    catches it (as the Plan's O.3 table specifies) alongside whatever else
    that particular truncation happens to also disturb (row-count WARN,
    integrity ERROR from the changed bytes)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.truncate_dataset(FIXTURE_CSV, Path(tmp) / "short.csv", keep_rows=5)
        report = run_validation_gate(out, CONTRACT_JSON, run_id="t")
    assert report.passed is False
    assert _findings(report, "MODELING_MIN_ROWS")
    assert _findings(report, "INTEGRITY_SHA256_MATCH")


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
