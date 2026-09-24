"""Phase 9 smoke test — `test_app_renders_failure_state` (PROJECT_PLAN.md
§O.4).

Uses a synthetic `run_summary.json` shaped exactly like
`flow/run_summary.py` would write for a real `halted_validation` run
(contract_validation failure, `crew2.started=false`) and verifies the UI:

1. derives FAIL (never PASS, never a blank/neutral state)
2. shows the failure reason
3. shows Crew 2 as **NOT STARTED**, not simply "missing"/absent

No OpenAI calls. No live Crew execution. Run directly:
    python tests/smoke/test_app_renders_failure_state.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import PROJECT_ROOT, isolated_artifacts, run_page  # noqa: E402
from lib import ui_helpers as ui  # noqa: E402

_PASS: list[str] = []
_FAIL: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        _PASS.append(name)
        print(f"PASS  {name}")
    else:
        _FAIL.append(name)
        print(f"FAIL  {name}  {detail}")


FAILURE_SUMMARY = {
    "run_id": "20260101T000000Z-deadbeef",
    "status": "halted_validation",
    "failure_category": "contract_validation",
    "failure_summary": "validation gate failed: 2 error(s), 0 warning(s)",
    "execution_mode": "normal",
    "fault_injection": None,
    "dataset": {"name": "telco_customer_churn", "rows": 7043, "columns": 21},
    "crew1": {
        "completed": True,
        "degraded_agents": [],
        "artifacts": {
            "clean_data_csv": "artifacts/crew1/clean_data.csv",
            "dataset_contract_json": "artifacts/crew1/dataset_contract.json",
            "eda_report_html": "artifacts/crew1/eda_report.html",
            "insights_md": "artifacts/crew1/insights.md",
        },
    },
    "validation": {
        "passed": False,
        "errors": 2,
        "warnings": 0,
        "report_path": "artifacts/validation/validation_report.json",
    },
    "crew2": {"started": False, "reason": "validation gate failed"},
    "log_path": "logs/pipeline_20260101T000000Z-deadbeef.log",
}


def test_compute_status_derives_fail() -> None:
    status = ui.compute_status(FAILURE_SUMMARY)
    check("test_compute_status_derives_fail__is_fail", status.is_fail is True, str(status))
    check("test_compute_status_derives_fail__not_pass", status.is_pass is False)
    check("test_compute_status_derives_fail__crew2_not_started", status.crew2_started is False)
    check(
        "test_compute_status_derives_fail__reason_is_gate_not_missing",
        status.crew2_not_started_reason == "validation gate failed",
        status.crew2_not_started_reason,
    )


def _write_fixture(tmp_path: Path) -> None:
    (tmp_path / "run_summary.json").write_text(json.dumps(FAILURE_SUMMARY, indent=2), encoding="utf-8")


def test_main_app_shows_fail_banner() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write_fixture(tmp)
        with isolated_artifacts(tmp):
            at = run_page(PROJECT_ROOT / "app" / "streamlit_app.py")
            check("test_main_app_no_exception", len(at.exception) == 0, str(list(at.exception)))
            markdown_text = " ".join(m.value for m in at.markdown).lower()
            check("test_main_app_shows_fail_banner", "fail" in markdown_text, markdown_text[:400])


def test_pipeline_run_page_shows_crew2_not_started() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write_fixture(tmp)
        with isolated_artifacts(tmp):
            at = run_page(PROJECT_ROOT / "app" / "pages" / "1_Pipeline_Run.py")
            check("test_run_page_no_exception", len(at.exception) == 0, str(list(at.exception)))
            captions = " ".join(c.value for c in at.caption)
            check(
                "test_run_page_shows_not_started_with_reason",
                "NOT STARTED" in captions and "validation gate failed" in captions,
                captions,
            )


def test_crew2_page_shows_not_started_not_missing() -> None:
    """Crew 2 not having run is a distinct, meaningful state — the page
    must say NOT STARTED, never treat it the same as a corrupt/absent
    artifact."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write_fixture(tmp)
        with isolated_artifacts(tmp):
            at = run_page(PROJECT_ROOT / "app" / "pages" / "5_Crew2_Modeling.py")
            check("test_crew2_page_no_exception", len(at.exception) == 0, str(list(at.exception)))
            markdown_text = " ".join(m.value for m in at.markdown)
            check(
                "test_crew2_page_says_not_started",
                "NOT STARTED" in markdown_text,
                markdown_text[:400],
            )


def test_validation_page_shows_fail_and_errors() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write_fixture(tmp)
        validation_report = {
            "run_id": FAILURE_SUMMARY["run_id"],
            "passed": False,
            "checks_run": 42,
            "errors": 2,
            "warnings": 0,
            "findings": [
                {
                    "check_id": "SCALE_DRIFT_MEDIAN",
                    "check_family": "scale_drift",
                    "severity": "ERROR",
                    "column": "MonthlyCharges",
                    "message": "SUSPECTED SCALE CHANGE — observed median ~100x the contract snapshot",
                    "expected": None,
                    "observed": None,
                    "contract_justification": "declared scale_drift policy on MonthlyCharges",
                },
                {
                    "check_id": "INTEGRITY_SHA256_MATCH",
                    "check_family": "integrity",
                    "severity": "ERROR",
                    "column": None,
                    "message": "clean_data.csv changed since the contract was written",
                    "expected": None,
                    "observed": None,
                    "contract_justification": None,
                },
            ],
            "contract_version": "1.0.0",
            "fault_injection": None,
            "validated_at": "2026-01-01T00:00:00Z",
        }
        (tmp / "validation").mkdir(parents=True, exist_ok=True)
        (tmp / "validation" / "validation_report.json").write_text(
            json.dumps(validation_report, indent=2), encoding="utf-8"
        )
        with isolated_artifacts(tmp):
            at = run_page(PROJECT_ROOT / "app" / "pages" / "4_Validation_Gate.py")
            check("test_validation_page_no_exception", len(at.exception) == 0, str(list(at.exception)))
            markdown_text = " ".join(m.value for m in at.markdown).lower()
            error_text = " ".join(e.value for e in at.error).lower()
            check(
                "test_validation_page_shows_fail",
                "fail" in markdown_text,
                markdown_text[:400],
            )
            check(
                "test_validation_page_shows_scale_drift_prominently",
                "scale drift" in error_text.lower(),
                error_text[:400],
            )


ALL_TESTS = [
    test_compute_status_derives_fail,
    test_main_app_shows_fail_banner,
    test_pipeline_run_page_shows_crew2_not_started,
    test_crew2_page_shows_not_started_not_missing,
    test_validation_page_shows_fail_and_errors,
]


def main() -> int:
    for fn in ALL_TESTS:
        fn()
    print(f"\n{len(_PASS)} passed, {len(_FAIL)} failed")
    if _FAIL:
        print("all failed:", _FAIL)
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
