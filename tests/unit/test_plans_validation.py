"""Unit tests — the guardrail PARSER contract, uniformly across every
`plans/*.py` validator built in Phase 5 (PROJECT_PLAN.md §D.1/§D.2/§G.1/§G.2
point 7, and the accelerated-workflow instruction: "No uncaught Pydantic
structural failure should escape from a future guardrail-validation path").

Each `validate_*` function must accept, in order of preference: a CrewAI
`TaskOutput`-shaped object (anything exposing `.raw`), a raw JSON `str`, a
`dict`, or an already-constructed model — and must NEVER raise, for any
input, structurally invalid or not. This file tests exactly that contract,
uniformly, for `validate_cleaning_plan`, `validate_insights_doc`,
`validate_feature_plan`, `validate_experiment_plan` — the semantic
(cross-context) rules each one ALSO enforces are covered in their own
dedicated test files (`test_cleaning_executor.py`, `test_eda_tools.py`,
`test_feature_builder.py`, `test_model_selection.py`).

Also re-confirms `plans/contract_draft.py.validate_contract_draft` (Phase
3) follows the identical contract, for a complete cross-module picture in
one place.

Runnable two ways:
  * ``pytest tests/unit/test_plans_validation.py``
  * ``python tests/unit/test_plans_validation.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale.contract.builder import build_contract  # noqa: E402
from harbor_vale.plans.cleaning_plan import CleaningPlan, DropColumnOp, validate_cleaning_plan  # noqa: E402
from harbor_vale.plans.contract_draft import validate_contract_draft  # noqa: E402
from harbor_vale.plans.experiment_plan import (  # noqa: E402
    ExperimentPlan,
    ExperimentVariant,
    validate_experiment_plan,
)
from harbor_vale.plans.feature_plan import ContractAcknowledgment, FeaturePlan, validate_feature_plan  # noqa: E402
from harbor_vale.plans.insights_doc import Insight, InsightsDoc, validate_insights_doc  # noqa: E402
from harbor_vale.tools.profiling_tools import profile_dataframe  # noqa: E402
from tests.fixtures.build_example_contract import build_draft  # noqa: E402
from tests.fixtures.gate_fixtures import FIXTURE_CSV  # noqa: E402


class _FakeTaskOutput:
    """Stands in for a CrewAI `TaskOutput` — the guardrail contract only
    ever needs `.raw`."""

    def __init__(self, raw) -> None:  # noqa: ANN001
        self.raw = raw


def _contract():
    ok, draft = validate_contract_draft(build_draft())
    assert ok
    return build_contract(
        draft, FIXTURE_CSV, contract_version="1.0.0", run_id="t", created_by="test",
        dataset_name="telco_customer_churn", source_documentation_url="https://example.invalid",
    )


def _profile():
    import pandas as pd

    return profile_dataframe(pd.read_csv(FIXTURE_CSV))


# ---------------------------------------------------------------------------
# CleaningPlan
# ---------------------------------------------------------------------------

def test_cleaning_plan_accepts_an_already_constructed_model() -> None:
    plan = CleaningPlan(operations=[DropColumnOp(column="customer_id", reason="identifier, not a feature")])
    ok, result = validate_cleaning_plan(plan, profile=_profile())
    assert ok and isinstance(result, CleaningPlan)


def test_cleaning_plan_accepts_raw_json_string() -> None:
    raw = '{"operations": [{"op": "drop_column", "column": "customer_id", "reason": "identifier"}]}'
    ok, result = validate_cleaning_plan(raw, profile=_profile())
    assert ok and isinstance(result, CleaningPlan)


def test_cleaning_plan_accepts_a_task_output_shaped_object() -> None:
    raw = '{"operations": [{"op": "drop_column", "column": "customer_id", "reason": "identifier"}]}'
    ok, result = validate_cleaning_plan(_FakeTaskOutput(raw), profile=_profile())
    assert ok and isinstance(result, CleaningPlan)


def test_cleaning_plan_rejects_malformed_json_without_raising() -> None:
    ok, msg = validate_cleaning_plan("{not valid json", profile=_profile())
    assert ok is False
    assert isinstance(msg, str)


def test_cleaning_plan_rejects_structurally_invalid_payload_without_raising() -> None:
    ok, msg = validate_cleaning_plan({"this_is_not_a_cleaning_plan": True}, profile=_profile())
    assert ok is False
    assert isinstance(msg, str)


def test_cleaning_plan_rejects_unsupported_input_type_without_raising() -> None:
    ok, msg = validate_cleaning_plan(12345, profile=_profile())
    assert ok is False
    assert "unsupported guardrail input type" in msg


def test_cleaning_plan_never_raises_even_with_no_profile() -> None:
    """The `profile=None` default (needed for CrewAI's Task.guardrail
    "exactly one required parameter" rule) never raises — it returns a
    clean (False, message)."""
    plan = CleaningPlan(operations=[DropColumnOp(column="customer_id", reason="x")])
    ok, msg = validate_cleaning_plan(plan)
    assert ok is False
    assert "no profile supplied" in msg


# ---------------------------------------------------------------------------
# InsightsDoc
# ---------------------------------------------------------------------------

def _valid_insights_doc() -> InsightsDoc:
    return InsightsDoc(
        headline="h",
        insights=[Insight(title="t", observation="o", business_implication="b", recommended_action="r", evidence_stat_key="x.mean")],
    )


def test_insights_doc_accepts_an_already_constructed_model() -> None:
    ok, result = validate_insights_doc(_valid_insights_doc(), eda_stats={"x.mean": 1.0})
    assert ok and isinstance(result, InsightsDoc)


def test_insights_doc_accepts_raw_json_string() -> None:
    raw = _valid_insights_doc().model_dump_json()
    ok, result = validate_insights_doc(raw, eda_stats={"x.mean": 1.0})
    assert ok and isinstance(result, InsightsDoc)


def test_insights_doc_accepts_a_task_output_shaped_object() -> None:
    raw = _valid_insights_doc().model_dump_json()
    ok, result = validate_insights_doc(_FakeTaskOutput(raw), eda_stats={"x.mean": 1.0})
    assert ok


def test_insights_doc_rejects_malformed_json_without_raising() -> None:
    ok, msg = validate_insights_doc("{not valid json", eda_stats={})
    assert ok is False and isinstance(msg, str)


def test_insights_doc_rejects_structurally_invalid_payload_without_raising() -> None:
    ok, msg = validate_insights_doc({"headline": "h"}, eda_stats={})  # missing required 'insights'
    assert ok is False and isinstance(msg, str)


def test_insights_doc_rejects_empty_insights_list() -> None:
    ok, msg = validate_insights_doc({"headline": "h", "insights": []}, eda_stats={})
    assert ok is False


def test_insights_doc_never_raises_even_with_no_eda_stats() -> None:
    ok, msg = validate_insights_doc(_valid_insights_doc())
    assert ok is False
    assert "no eda_stats supplied" in msg


# ---------------------------------------------------------------------------
# FeaturePlan
# ---------------------------------------------------------------------------

def _valid_feature_plan(contract) -> FeaturePlan:  # noqa: ANN001
    return FeaturePlan(
        contract_acknowledgment=ContractAcknowledgment(
            contract_version=contract.contract_version, target_confirmed=True,
            required_features_confirmed=True, excluded_features_respected=["customer_id"],
        ),
        use_features=list(contract.required_features),
    )


def test_feature_plan_accepts_an_already_constructed_model() -> None:
    contract = _contract()
    ok, result = validate_feature_plan(_valid_feature_plan(contract), contract=contract)
    assert ok and isinstance(result, FeaturePlan)


def test_feature_plan_accepts_raw_json_string() -> None:
    contract = _contract()
    raw = _valid_feature_plan(contract).model_dump_json()
    ok, result = validate_feature_plan(raw, contract=contract)
    assert ok and isinstance(result, FeaturePlan)


def test_feature_plan_accepts_a_task_output_shaped_object() -> None:
    contract = _contract()
    raw = _valid_feature_plan(contract).model_dump_json()
    ok, result = validate_feature_plan(_FakeTaskOutput(raw), contract=contract)
    assert ok


def test_feature_plan_rejects_malformed_json_without_raising() -> None:
    ok, msg = validate_feature_plan("{not valid json", contract=_contract())
    assert ok is False and isinstance(msg, str)


def test_feature_plan_rejects_structurally_invalid_payload_without_raising() -> None:
    ok, msg = validate_feature_plan({"use_features": "not_a_list"}, contract=_contract())
    assert ok is False and isinstance(msg, str)


def test_feature_plan_never_raises_even_with_no_contract() -> None:
    contract = _contract()
    ok, msg = validate_feature_plan(_valid_feature_plan(contract))
    assert ok is False
    assert "no contract supplied" in msg


# ---------------------------------------------------------------------------
# ExperimentPlan
# ---------------------------------------------------------------------------

def _valid_experiment_plan() -> ExperimentPlan:
    return ExperimentPlan(
        primary_metric="roc_auc", metric_rationale="r", cv_folds=5,
        variants=[
            ExperimentVariant(name="a", estimator="logistic_regression", params={}, rationale="r"),
            ExperimentVariant(name="b", estimator="random_forest", params={}, rationale="r"),
        ],
    )


def test_experiment_plan_accepts_an_already_constructed_model() -> None:
    ok, result = validate_experiment_plan(_valid_experiment_plan())
    assert ok and isinstance(result, ExperimentPlan)


def test_experiment_plan_accepts_raw_json_string() -> None:
    raw = _valid_experiment_plan().model_dump_json()
    ok, result = validate_experiment_plan(raw)
    assert ok and isinstance(result, ExperimentPlan)


def test_experiment_plan_accepts_a_task_output_shaped_object() -> None:
    raw = _valid_experiment_plan().model_dump_json()
    ok, result = validate_experiment_plan(_FakeTaskOutput(raw))
    assert ok


def test_experiment_plan_rejects_malformed_json_without_raising() -> None:
    ok, msg = validate_experiment_plan("{not valid json")
    assert ok is False and isinstance(msg, str)


def test_experiment_plan_rejects_structurally_invalid_payload_without_raising() -> None:
    ok, msg = validate_experiment_plan({"primary_metric": "not_a_real_metric"})
    assert ok is False and isinstance(msg, str)


def test_experiment_plan_rejects_unsupported_input_type_without_raising() -> None:
    ok, msg = validate_experiment_plan(3.14159)
    assert ok is False
    assert "unsupported guardrail input type" in msg


# ---------------------------------------------------------------------------
# ContractDraft (Phase 3) — same contract, re-confirmed alongside the rest
# ---------------------------------------------------------------------------

def test_contract_draft_rejects_malformed_json_without_raising() -> None:
    ok, msg = validate_contract_draft("{not valid json")
    assert ok is False and isinstance(msg, str)


def test_contract_draft_rejects_unsupported_input_type_without_raising() -> None:
    ok, msg = validate_contract_draft(object())
    assert ok is False
    assert "unsupported guardrail input type" in msg


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
