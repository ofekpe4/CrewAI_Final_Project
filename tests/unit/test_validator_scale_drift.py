"""Unit tests — validation gate, check family E (scale drift, §E.3).

PROJECT_PLAN.md §O.1: **`test_detects_hundredfold_scale_change` is the
central test of the whole Phase 4 gate** — the deterministic reproduction of
the Harbor & Vale incident this entire project simulates. This is also
Internal Gate 4C's mandatory failure demonstration.

Runnable two ways:
  * ``pytest tests/unit/test_validator_scale_drift.py``
  * ``python tests/unit/test_validator_scale_drift.py``
"""

from __future__ import annotations

import shutil
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


# --- the mandatory test (§O.1, Internal Gate 4C) --------------------------------

def test_detects_hundredfold_scale_change() -> None:
    """`monthly_charges *= 100`, dtype unchanged. Must: fail the gate, emit a
    scale_drift ERROR containing "SUSPECTED SCALE CHANGE" with an
    approximately-100x ratio, ALSO emit an integrity ERROR (the bytes
    changed), keep running every other check rather than stopping at the
    first failure, and leave the committed baseline fixture byte-identical.
    """
    original_bytes_before = FIXTURE_CSV.read_bytes()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Operate on a COPY — never the committed fixture itself.
        source_copy = tmp_path / "source_copy.csv"
        shutil.copyfile(FIXTURE_CSV, source_copy)

        mutated = fi.scale_change(source_copy, tmp_path / "mutated.csv", column="monthly_charges", factor=100.0)

        mutated_df = pd.read_csv(mutated)
        assert str(mutated_df["monthly_charges"].dtype) == "float64", "dtype must be preserved by the mutation"

        report = run_validation_gate(mutated, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t", fault_injection="scale_change")

    # 1. the baseline fixture on disk was never touched
    assert FIXTURE_CSV.read_bytes() == original_bytes_before

    # 2. the gate fails
    assert report.passed is False

    # 3. scale_drift ERROR with the exact required phrase and a ~100x ratio
    scale_hits = _findings(report, "SCALE_DRIFT_MEDIAN")
    assert len(scale_hits) == 1
    finding = scale_hits[0]
    assert finding.severity == "ERROR"
    assert finding.column == "monthly_charges"
    assert "SUSPECTED SCALE CHANGE" in finding.message
    ratio = finding.observed / finding.expected
    assert abs(ratio - 100.0) / 100.0 < 0.05

    # 4. integrity ERROR also present (bytes changed)
    integrity_hits = _findings(report, "INTEGRITY_SHA256_MATCH")
    assert len(integrity_hits) == 1 and integrity_hits[0].severity == "ERROR"

    # 5. the gate did not stop after the first failure — other passing
    #    checks were still evaluated (checks_run reflects the full run, not
    #    just the two families that failed).
    assert report.checks_run >= 60
    families_with_findings = {f.check_family for f in report.findings}
    assert families_with_findings == {"scale_drift", "integrity"}

    # 6. the message stays epistemically honest — no currency claim.
    assert "USD" not in finding.message and "cents" not in finding.message.lower()
    assert "currency_unspecified" in finding.message  # the contract's actual unit declaration, quoted


def test_fault_injection_marker_is_carried_onto_the_report() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        mutated = fi.scale_change(FIXTURE_CSV, tmp_path / "mutated.csv", column="monthly_charges", factor=100.0)
        report = run_validation_gate(mutated, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t", fault_injection="scale_change")
    assert report.fault_injection == "scale_change"


def test_normal_baseline_passes_with_no_scale_drift_finding() -> None:
    report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert report.passed is True
    assert not _findings(report, "SCALE_DRIFT_MEDIAN")


def test_ordinary_in_tolerance_drift_passes() -> None:
    """`monthly_charges.scale_drift.median_rel_tolerance` is 0.25 — a modest
    +10% shift across the whole column must stay within tolerance."""
    with tempfile.TemporaryDirectory() as tmp:
        df = pd.read_csv(FIXTURE_CSV)
        df["monthly_charges"] = df["monthly_charges"] * 1.10
        out = Path(tmp) / "mild_drift.csv"
        df.to_csv(out, index=False)
        report = run_validation_gate(out, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert not _findings(report, "SCALE_DRIFT_MEDIAN")


def test_out_of_tolerance_but_not_a_recognized_hint_ratio_still_errors_generically() -> None:
    """A ×3 shift is well beyond the 25% tolerance but not close to any of
    the contract's `scale_change_ratio_hints` — must still ERROR, with the
    generic "SCALE DRIFT" wording rather than a false "SUSPECTED SCALE
    CHANGE ≈Nx" claim it cannot support."""
    with tempfile.TemporaryDirectory() as tmp:
        df = pd.read_csv(FIXTURE_CSV)
        df["monthly_charges"] = df["monthly_charges"] * 3.0
        out = Path(tmp) / "triple.csv"
        df.to_csv(out, index=False)
        report = run_validation_gate(out, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    hits = _findings(report, "SCALE_DRIFT_MEDIAN")
    assert len(hits) == 1 and hits[0].severity == "ERROR"
    assert "SUSPECTED SCALE CHANGE" not in hits[0].message
    assert "SCALE DRIFT" in hits[0].message


def test_column_with_no_declared_scale_drift_policy_is_never_checked() -> None:
    """`total_charges` has real observed spread but no declared scale_drift
    policy (fixture draft) — no scale-drift check should run for it even if
    its values shift dramatically."""
    with tempfile.TemporaryDirectory() as tmp:
        df = pd.read_csv(FIXTURE_CSV)
        df["total_charges"] = df["total_charges"] * 1000.0
        out = Path(tmp) / "shifted.csv"
        df.to_csv(out, index=False)
        report = run_validation_gate(out, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert not any(f.column == "total_charges" for f in _findings(report, "SCALE_DRIFT_MEDIAN"))


def test_zero_snapshot_median_is_handled_without_dividing_by_zero() -> None:
    """A column whose contracted snapshot median is exactly 0 must be
    skipped safely (§E.3's own pseudocode guard), never raise
    ZeroDivisionError, regardless of what the candidate data now looks like."""
    import json

    from harbor_vale.contract.schema import DatasetContract

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        contract_dict = json.loads(CONTRACT_JSON.read_text(encoding="utf-8"))
        for col in contract_dict["columns"]:
            if col["name"] == "monthly_charges":
                col["observed"]["median"] = 0.0
        # still a structurally valid DatasetContract
        DatasetContract.model_validate(contract_dict)
        zeroed = tmp_path / "zero_median_contract.json"
        zeroed.write_text(__import__("json").dumps(contract_dict), encoding="utf-8")

        # Should not raise, and should not report a scale_drift finding for
        # monthly_charges (the ratio is undefined when the snapshot is 0).
        report = run_validation_gate(FIXTURE_CSV, zeroed, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert not any(f.column == "monthly_charges" for f in _findings(report, "SCALE_DRIFT_MEDIAN"))


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
