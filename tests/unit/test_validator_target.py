"""Unit tests — validation gate, check family C (target).

PROJECT_PLAN.md §F.1: target exists · ⊆ closed_domain · no nulls · ≥2 classes
· positive_rate within `drift.tolerance` — and explicitly NOT `observed.*`
alone (§Phase 4 "NO AUTOMATIC ENFORCEMENT OF OBSERVED VALUES").

Runnable two ways:
  * ``pytest tests/unit/test_validator_target.py``
  * ``python tests/unit/test_validator_target.py``
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
from tests.fixtures.gate_fixtures import CONTRACT_JSON, FIXTURE_CSV, build_contract_json  # noqa: E402


def _findings(report, check_id: str):
    return [f for f in report.findings if f.check_id == check_id]


def test_missing_target_column_is_an_error_and_skips_further_target_checks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.drop_required_column(FIXTURE_CSV, Path(tmp) / "d.csv", column="churn")
        report = run_validation_gate(out, CONTRACT_JSON, run_id="t")
    assert report.passed is False
    hits = _findings(report, "TARGET_COLUMN_PRESENT")
    assert len(hits) == 1 and hits[0].severity == "ERROR"
    # nothing downstream of "the column doesn't exist" should be attempted
    for dependent in ("TARGET_NO_NULLS", "TARGET_CLOSED_DOMAIN", "TARGET_AT_LEAST_TWO_CLASSES"):
        assert not _findings(report, dependent)


def test_unknown_target_label_violates_closed_domain() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.unknown_category(FIXTURE_CSV, Path(tmp) / "u.csv", column="churn", new_value="Maybe")
        report = run_validation_gate(out, CONTRACT_JSON, run_id="t")
    assert report.passed is False
    hits = _findings(report, "TARGET_CLOSED_DOMAIN")
    assert len(hits) == 1 and hits[0].severity == "ERROR"
    assert "Maybe" in hits[0].observed


def test_null_target_violates_nullable_false() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.inject_nulls(FIXTURE_CSV, Path(tmp) / "n.csv", column="churn", count=2)
        report = run_validation_gate(out, CONTRACT_JSON, run_id="t")
    assert report.passed is False
    hits = _findings(report, "TARGET_NO_NULLS")
    assert len(hits) == 1 and hits[0].severity == "ERROR" and hits[0].observed == 2


def test_one_class_target_fails_at_least_two_classes() -> None:
    import pandas as pd

    with tempfile.TemporaryDirectory() as tmp:
        df = pd.read_csv(FIXTURE_CSV)
        df["churn"] = 0
        out = Path(tmp) / "one_class.csv"
        df.to_csv(out, index=False)
        report = run_validation_gate(out, CONTRACT_JSON, run_id="t")
    assert report.passed is False
    hits = _findings(report, "TARGET_AT_LEAST_TWO_CLASSES")
    assert len(hits) == 1 and hits[0].observed == 1


# --- positive-rate drift: only enforced if target.drift is declared ------------

def test_flipped_target_encoding_triggers_drift_when_drift_policy_declared() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        contract = build_contract_json(tmp_path, with_target_drift=True)
        out = fi.flip_target_encoding(FIXTURE_CSV, tmp_path / "flipped.csv", target_column="churn")
        report = run_validation_gate(out, contract, run_id="t")
    assert report.passed is False
    hits = _findings(report, "TARGET_POSITIVE_RATE_DRIFT")
    assert len(hits) == 1 and hits[0].severity == "ERROR"
    assert hits[0].contract_justification


def test_flipped_target_encoding_is_silent_without_a_declared_drift_policy() -> None:
    """The checked-in `contract_example.json` declares no `target.drift` —
    §Phase 4: only the EXPLICIT drift policy is enforceable, never
    `observed.positive_rate` by itself."""
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.flip_target_encoding(FIXTURE_CSV, Path(tmp) / "flipped.csv", target_column="churn")
        report = run_validation_gate(out, CONTRACT_JSON, run_id="t")
    assert not _findings(report, "TARGET_POSITIVE_RATE_DRIFT")


def test_in_tolerance_drift_passes_when_drift_policy_declared() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        contract = build_contract_json(tmp_path, with_target_drift=True)
        report = run_validation_gate(FIXTURE_CSV, contract, run_id="t")
    assert report.passed is True
    assert not _findings(report, "TARGET_POSITIVE_RATE_DRIFT")


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
