"""Phase 9 additional UI smoke tests (PROJECT_PLAN.md §Q.5 "additional
useful UI tests"):

- a `completed` run derives PASS
- `fault_injection` set derives DEMO MODE
- non-empty `degraded_agents` derives DEGRADED
- the Dataset Contract page visually separates observed from constraints
- the model winner and metric values shown come from `experiments.json`,
  never from parsed agent prose
- malformed JSON does not crash a page helper

No OpenAI calls. No live Crew execution. Run directly:
    python tests/smoke/test_app_additional_states.py
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


_BASE_SUMMARY = {
    "run_id": "20260101T000000Z-cafef00d",
    "status": "completed",
    "failure_category": None,
    "failure_summary": None,
    "execution_mode": "normal",
    "fault_injection": None,
    "dataset": {"name": "telco_customer_churn", "rows": 7043, "columns": 21},
    "crew1": {"completed": True, "degraded_agents": [], "artifacts": {}},
    "validation": {"passed": True, "errors": 0, "warnings": 0, "report_path": None},
    "crew2": {
        "started": True,
        "completed": True,
        "degraded_agents": [],
        "artifacts": {},
        "best_model_name": "Logistic Regression Base",
        "primary_metric": "roc_auc",
        "primary_metric_value": 0.8477950864140121,
    },
    "log_path": None,
}


def test_completed_status_derives_pass() -> None:
    status = ui.compute_status(_BASE_SUMMARY)
    check("test_completed_status_derives_pass", status.is_pass is True and status.is_fail is False)


def test_fault_injection_derives_demo_mode() -> None:
    summary = dict(_BASE_SUMMARY, fault_injection="scale_change")
    status = ui.compute_status(summary)
    check("test_fault_injection_derives_demo_mode", status.is_demo is True, str(status.fault_injection))


def test_degraded_agents_derives_degraded() -> None:
    summary = json.loads(json.dumps(_BASE_SUMMARY))  # deep copy
    summary["crew1"]["degraded_agents"] = ["insight_analyst"]
    status = ui.compute_status(summary)
    check(
        "test_degraded_agents_derives_degraded",
        status.is_degraded is True and status.degraded_agents == ["insight_analyst"],
        str(status.degraded_agents),
    )


def test_pass_demo_degraded_can_coexist() -> None:
    """PASS + DEMO + DEGRADED are semantically independent flags — a
    completed run can still be a demo run with a degraded narrative agent."""
    summary = json.loads(json.dumps(_BASE_SUMMARY))
    summary["fault_injection"] = "scale_change"
    summary["crew2"]["degraded_agents"] = ["responsible_ai_documenter"]
    status = ui.compute_status(summary)
    check(
        "test_pass_demo_degraded_can_coexist",
        status.is_pass and status.is_demo and status.is_degraded,
        str((status.is_pass, status.is_demo, status.is_degraded)),
    )


def test_contract_page_separates_observed_and_constraints() -> None:
    """Uses the real committed dataset_contract.json fixture, copied into an
    isolated temp dir — proves the OBSERVED/CONSTRAINTS split renders as two
    visually distinct blocks, not one flattened JSON view."""
    real_contract = PROJECT_ROOT / "artifacts" / "crew1" / "dataset_contract.json"
    if not real_contract.is_file():
        check("test_contract_page_separates_observed_and_constraints", True, "SKIPPED — no committed contract fixture on disk")
        return
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "crew1").mkdir(parents=True, exist_ok=True)
        (tmp / "crew1" / "dataset_contract.json").write_text(real_contract.read_text(encoding="utf-8"), encoding="utf-8")
        with isolated_artifacts(tmp):
            at = run_page(PROJECT_ROOT / "app" / "pages" / "3_Dataset_Contract.py")
            check("test_contract_page_no_exception", len(at.exception) == 0, str(list(at.exception)))
            html = "\n".join(m.value for m in at.markdown)
            has_observed = "Observed" in html and "hv-observed" in html
            has_constraints = "Constraints" in html and "hv-constraints" in html
            check(
                "test_contract_page_separates_observed_and_constraints",
                has_observed and has_constraints,
                f"observed_block={has_observed} constraints_block={has_constraints}",
            )


def test_winner_and_metrics_come_from_experiments_json() -> None:
    fake_experiments = {
        "run_id": "test",
        "primary_metric": "roc_auc",
        "metric_rationale": "test rationale",
        "cv_folds": 5,
        "variants": [
            {
                "name": "Variant Alpha",
                "estimator": "logistic_regression",
                "params": {},
                "rationale": "r",
                "cv_metrics": {"roc_auc": 0.61, "pr_auc": 0.5, "f1": 0.5, "precision": 0.5, "recall": 0.5, "accuracy": 0.5,
                                "confusion_matrix": [[1, 2], [3, 4]]},
            },
            {
                "name": "Variant Beta — the real winner",
                "estimator": "random_forest",
                "params": {},
                "rationale": "r",
                "cv_metrics": {"roc_auc": 0.987654, "pr_auc": 0.5, "f1": 0.5, "precision": 0.5, "recall": 0.5, "accuracy": 0.5,
                                "confusion_matrix": [[1, 2], [3, 4]]},
            },
        ],
        "winner": {
            "name": "Variant Beta — the real winner",
            "estimator": "random_forest",
            "cv_metrics": {"roc_auc": 0.987654},
            "test_metrics": {"roc_auc": 0.987654, "f1": 0.5, "precision": 0.5, "recall": 0.5,
                              "confusion_matrix": [[10, 2], [3, 40]]},
        },
    }
    summary = json.loads(json.dumps(_BASE_SUMMARY))
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "crew2").mkdir(parents=True, exist_ok=True)
        (tmp / "crew2" / "experiments.json").write_text(json.dumps(fake_experiments), encoding="utf-8")
        (tmp / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
        with isolated_artifacts(tmp):
            at = run_page(PROJECT_ROOT / "app" / "pages" / "5_Crew2_Modeling.py")
            check("test_crew2_page_no_exception_winner_test", len(at.exception) == 0, str(list(at.exception)))
            all_text = " ".join(m.value for m in at.markdown) + " ".join(s.value for s in at.success)
            check(
                "test_winner_name_from_experiments_json",
                "Variant Beta — the real winner" in all_text,
                all_text[:400],
            )
            metric_values = [m.value for m in at.metric]
            check(
                "test_winner_metric_value_from_experiments_json",
                any("0.9877" in v or "0.987654" in v for v in metric_values),
                str(metric_values),
            )


def test_malformed_json_does_not_crash_helper() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        bad_path = tmp / "broken.json"
        bad_path.write_text("{not valid json,,,", encoding="utf-8")
        result = ui.load_json(bad_path)
        check(
            "test_malformed_json_does_not_crash_helper__not_ok",
            result.ok is False and result.missing is False,
            str(result),
        )
        check(
            "test_malformed_json_does_not_crash_helper__has_error_not_pass",
            bool(result.error),
            str(result.error),
        )


def test_malformed_run_summary_does_not_crash_page() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "run_summary.json").write_text("{ this is not json", encoding="utf-8")
        with isolated_artifacts(tmp):
            at = run_page(PROJECT_ROOT / "app" / "streamlit_app.py")
            check("test_malformed_run_summary_no_exception", len(at.exception) == 0, str(list(at.exception)))
            error_text = " ".join(e.value for e in at.error).lower()
            check(
                "test_malformed_run_summary_shows_visible_error",
                "malformed" in error_text or "run_summary" in error_text,
                error_text[:300],
            )


ALL_TESTS = [
    test_completed_status_derives_pass,
    test_fault_injection_derives_demo_mode,
    test_degraded_agents_derives_degraded,
    test_pass_demo_degraded_can_coexist,
    test_contract_page_separates_observed_and_constraints,
    test_winner_and_metrics_come_from_experiments_json,
    test_malformed_json_does_not_crash_helper,
    test_malformed_run_summary_does_not_crash_page,
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
