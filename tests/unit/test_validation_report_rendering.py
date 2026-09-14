"""Unit tests — `render_validation_report_markdown` (§F.3, Internal Gate 4E).

Runnable two ways:
  * ``pytest tests/unit/test_validation_report_rendering.py``
  * ``python tests/unit/test_validation_report_rendering.py``
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale.contract.validator import render_validation_report_markdown, run_validation_gate  # noqa: E402
from harbor_vale.demo import fault_injection as fi  # noqa: E402
from tests.fixtures.gate_fixtures import CONTRACT_JSON, FIXTURE_CSV  # noqa: E402


def test_passing_report_renders_pass_and_no_findings_note() -> None:
    report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, run_id="render-pass")
    text = render_validation_report_markdown(report)
    assert "VALIDATION PASSED" in text
    assert "render-pass" in text
    assert "0 error(s)" in text
    assert "No findings" in text


def test_failing_report_renders_every_required_element() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        mutated = fi.scale_change(FIXTURE_CSV, Path(tmp) / "m.csv", column="monthly_charges", factor=100.0)
        report = run_validation_gate(mutated, CONTRACT_JSON, run_id="render-fail", fault_injection="scale_change")
    text = render_validation_report_markdown(report)

    assert "VALIDATION FAILED" in text
    assert "render-fail" in text
    assert "contract v1.0.0" in text
    assert "fault_injection: scale_change" in text
    assert "SUSPECTED SCALE CHANGE" in text
    assert "SCALE_DRIFT_MEDIAN" in text
    assert "INTEGRITY_SHA256_MATCH" in text
    assert "monthly_charges" in text
    assert "expected:" in text and "observed:" in text
    assert "Contract justification" in text
    assert "scale-sensitive" in text  # the actual declared justification text
    assert f"{report.errors} error(s)" in text
    assert f"{report.warnings} warning(s)" in text

    # §Phase 4 staged-interpretation boundary: the renderer must NOT claim a
    # downstream crew was or was not started — that is a future Flow fact.
    assert "Data Scientist Crew was NOT started" not in text
    assert "crew2_started" not in text

    # §E.3: never overclaim the currency.
    assert "USD" not in text and "cents" not in text.lower()


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
