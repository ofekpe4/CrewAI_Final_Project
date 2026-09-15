"""Unit tests — `plans/model_card.py` (PROJECT_PLAN.md §G.3).

Proves: a valid `ModelCard` passes; malformed JSON / structurally invalid
payloads are rejected through `(False, feedback)`, never a raw exception;
empty `contract_dependencies` is rejected (structurally); a card that cites
no real contract assumption is rejected; an invented/mismatched numeric
metric is rejected; a metric genuinely backed by `experiments.json` is
accepted; the guardrail constructs cleanly as a real
`Task(guardrail=validate_model_card)` against the pinned `crewai==1.15.20`;
and the whole thing needs zero LLM calls / no API key.

Runnable two ways:
  * ``pytest tests/unit/test_plans_model_card.py``
  * ``python tests/unit/test_plans_model_card.py``
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale.contract.schema import DatasetContract  # noqa: E402
from harbor_vale.plans.model_card import MetricClaim, ModelCard, validate_model_card  # noqa: E402
from tests.fixtures.hardcoded_e2e_harness import run_hardcoded_e2e  # noqa: E402
from harbor_vale.io_paths import RAW_TELCO_CHURN_CSV  # noqa: E402

_SKIP_REASON = (
    f"real raw dataset not found at {RAW_TELCO_CHURN_CSV} — run "
    "`python scripts/download_data.py` first (Phase 2 acquisition)."
)


class _FakeTaskOutput:
    def __init__(self, raw) -> None:  # noqa: ANN001
        self.raw = raw


def _real_experiments_and_contract_and_winner(workspace: Path):
    result = run_hardcoded_e2e(workspace, run_id="model-card-test")
    experiments = json.loads(result.experiments_json.read_text(encoding="utf-8"))
    contract = DatasetContract.model_validate_json(result.dataset_contract_json.read_text(encoding="utf-8"))
    return experiments, contract, result.winner_name, result.winner_test_roc_auc


def _valid_card(contract: DatasetContract, winner_name: str, winner_roc_auc: float) -> ModelCard:
    return ModelCard(
        purpose="Predict which Telco customers are likely to churn.",
        intended_use="Prioritizing retention outreach for at-risk customers.",
        out_of_scope_use=["Automated account termination decisions."],
        training_data_summary=f"Trained on {contract.integrity.row_count} customer records.",
        metrics_summary=[
            MetricClaim(metric="roc_auc", split="test", variant_name=winner_name, value=winner_roc_auc)
        ],
        limitations=["Currency of monetary columns is not documented in the source data."],
        ethical_considerations=["No fairness/bias audit across protected attributes was performed."],
        contract_dependencies=[contract.assumptions[0], "target.closed_domain"],
        monitoring_recommendations=["Re-validate the contract if monthly_charges median drifts substantially."],
    )


# --- structural schema rules (no experiments/contract needed) -----------------

def test_empty_contract_dependencies_is_a_structural_rejection() -> None:
    from pydantic import ValidationError

    try:
        ModelCard(
            purpose="p", intended_use="i", training_data_summary="t",
            metrics_summary=[MetricClaim(metric="roc_auc", split="test", variant_name="v", value=0.8)],
            contract_dependencies=[],
        )
    except ValidationError as exc:
        assert "contract_dependencies" in str(exc)
    else:
        raise AssertionError("expected ValidationError for empty contract_dependencies")


def test_empty_metrics_summary_is_a_structural_rejection() -> None:
    from pydantic import ValidationError

    try:
        ModelCard(
            purpose="p", intended_use="i", training_data_summary="t",
            metrics_summary=[], contract_dependencies=["some assumption"],
        )
    except ValidationError as exc:
        assert "metrics_summary" in str(exc)
    else:
        raise AssertionError("expected ValidationError for empty metrics_summary")


def test_metric_outside_the_closed_vocabulary_is_a_structural_rejection() -> None:
    """The mechanical anti-fairness-fabrication proof: a metric named
    'fairness' (or anything else outside the six measured metrics) cannot
    even be constructed — the Literal makes it inexpressible, not merely
    rejected by a semantic rule that could be bypassed."""
    from pydantic import ValidationError

    try:
        MetricClaim(metric="fairness", split="test", variant_name="v", value=0.95)
    except ValidationError:
        pass
    else:
        raise AssertionError("expected ValidationError: 'fairness' is not in the closed MetricName Literal")


def test_extra_field_is_rejected() -> None:
    from pydantic import ValidationError

    try:
        ModelCard.model_validate(
            {
                "purpose": "p", "intended_use": "i", "training_data_summary": "t",
                "metrics_summary": [{"metric": "roc_auc", "split": "test", "variant_name": "v", "value": 0.8}],
                "contract_dependencies": ["a"],
                "unexpected_field": "should not be allowed",
            }
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("expected ValidationError for an unrecognised extra field")


# --- guardrail parser contract --------------------------------------------------

def test_malformed_json_is_rejected_without_raising() -> None:
    # experiments/contract just need to be non-None — parsing fails before
    # semantic validation would ever touch them.
    ok, msg = validate_model_card("{not valid json", experiments={}, contract=object())
    assert ok is False
    assert "failed schema validation" in msg


def test_structurally_invalid_payload_is_rejected_without_raising() -> None:
    ok, msg = validate_model_card({"this_is_not_a_model_card": True}, experiments={}, contract=object())
    assert ok is False
    assert "failed schema validation" in msg


def test_unsupported_input_type_is_rejected_without_raising() -> None:
    # experiments/contract just need to be non-None here — the raw-input-type
    # check runs before any real semantic validation would touch them.
    ok, msg = validate_model_card(12345, experiments={}, contract=object())
    assert ok is False
    assert "unsupported guardrail input type" in msg


def test_never_raises_with_no_experiments_or_contract() -> None:
    """The `= None` defaults exist only for CrewAI's Task.guardrail
    'exactly one required parameter' rule — calling without real context
    must return a clear wiring-error message, never raise."""
    ok, msg = validate_model_card({"purpose": "p"})
    assert ok is False
    assert "no experiments supplied" in msg or "no contract supplied" in msg


def test_accepts_a_task_output_shaped_object() -> None:
    if not RAW_TELCO_CHURN_CSV.is_file():
        print(f"SKIP: {_SKIP_REASON}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        experiments, contract, winner_name, winner_roc_auc = _real_experiments_and_contract_and_winner(Path(tmp))
        raw = _valid_card(contract, winner_name, winner_roc_auc).model_dump_json()
        ok, result = validate_model_card(_FakeTaskOutput(raw), experiments=experiments, contract=contract)
    assert ok and isinstance(result, ModelCard)


def test_accepts_raw_json_string() -> None:
    if not RAW_TELCO_CHURN_CSV.is_file():
        print(f"SKIP: {_SKIP_REASON}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        experiments, contract, winner_name, winner_roc_auc = _real_experiments_and_contract_and_winner(Path(tmp))
        raw = _valid_card(contract, winner_name, winner_roc_auc).model_dump_json()
        ok, result = validate_model_card(raw, experiments=experiments, contract=contract)
    assert ok and isinstance(result, ModelCard)


# --- semantic validation against REAL experiments.json + DatasetContract ------

def test_valid_model_card_passes_against_real_hardcoded_e2e_output() -> None:
    if not RAW_TELCO_CHURN_CSV.is_file():
        print(f"SKIP: {_SKIP_REASON}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        experiments, contract, winner_name, winner_roc_auc = _real_experiments_and_contract_and_winner(Path(tmp))
        card = _valid_card(contract, winner_name, winner_roc_auc)
        ok, result = validate_model_card(card, experiments=experiments, contract=contract)
    assert ok, result
    assert isinstance(result, ModelCard)


def test_metric_value_backed_by_experiments_json_is_accepted() -> None:
    if not RAW_TELCO_CHURN_CSV.is_file():
        print(f"SKIP: {_SKIP_REASON}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        experiments, contract, winner_name, winner_roc_auc = _real_experiments_and_contract_and_winner(Path(tmp))
        # a cv-split claim for a non-winner variant, looked up directly from the real artifact
        other_variant = next(v["name"] for v in experiments["variants"] if v["name"] != winner_name)
        real_cv_value = experiments["variants"][
            [v["name"] for v in experiments["variants"]].index(other_variant)
        ]["cv_metrics"]["roc_auc"]
        card = _valid_card(contract, winner_name, winner_roc_auc).model_copy(
            update={"metrics_summary": [
                MetricClaim(metric="roc_auc", split="test", variant_name=winner_name, value=winner_roc_auc),
                MetricClaim(metric="roc_auc", split="cv", variant_name=other_variant, value=real_cv_value),
            ]}
        )
        ok, result = validate_model_card(card, experiments=experiments, contract=contract)
    assert ok, result


def test_invented_metric_value_is_rejected() -> None:
    if not RAW_TELCO_CHURN_CSV.is_file():
        print(f"SKIP: {_SKIP_REASON}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        experiments, contract, winner_name, winner_roc_auc = _real_experiments_and_contract_and_winner(Path(tmp))
        fabricated_value = min(0.999999, winner_roc_auc + 0.05)
        card = _valid_card(contract, winner_name, winner_roc_auc).model_copy(
            update={"metrics_summary": [
                MetricClaim(metric="roc_auc", split="test", variant_name=winner_name, value=fabricated_value)
            ]}
        )
        ok, msg = validate_model_card(card, experiments=experiments, contract=contract)
    assert ok is False
    assert "does not match the real measured value" in msg


def test_metric_for_a_nonexistent_variant_is_rejected() -> None:
    if not RAW_TELCO_CHURN_CSV.is_file():
        print(f"SKIP: {_SKIP_REASON}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        experiments, contract, winner_name, winner_roc_auc = _real_experiments_and_contract_and_winner(Path(tmp))
        card = _valid_card(contract, winner_name, winner_roc_auc).model_copy(
            update={"metrics_summary": [
                MetricClaim(metric="roc_auc", split="cv", variant_name="not_a_real_variant", value=0.8)
            ]}
        )
        ok, msg = validate_model_card(card, experiments=experiments, contract=contract)
    assert ok is False
    assert "does not exist in experiments.json" in msg


def test_test_split_metric_for_a_non_winner_variant_is_rejected() -> None:
    """`verify_metric_in_experiments`'s own rule, exercised through the
    ModelCard guardrail: test-set metrics exist only for the winner."""
    if not RAW_TELCO_CHURN_CSV.is_file():
        print(f"SKIP: {_SKIP_REASON}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        experiments, contract, winner_name, winner_roc_auc = _real_experiments_and_contract_and_winner(Path(tmp))
        loser = next(v["name"] for v in experiments["variants"] if v["name"] != winner_name)
        card = _valid_card(contract, winner_name, winner_roc_auc).model_copy(
            update={"metrics_summary": [
                MetricClaim(metric="roc_auc", split="test", variant_name=loser, value=0.8)
            ]}
        )
        ok, msg = validate_model_card(card, experiments=experiments, contract=contract)
    assert ok is False
    assert "does not exist in experiments.json" in msg


def test_contract_dependencies_with_no_real_assumption_is_rejected() -> None:
    if not RAW_TELCO_CHURN_CSV.is_file():
        print(f"SKIP: {_SKIP_REASON}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        experiments, contract, winner_name, winner_roc_auc = _real_experiments_and_contract_and_winner(Path(tmp))
        card = _valid_card(contract, winner_name, winner_roc_auc).model_copy(
            update={"contract_dependencies": ["this is not a real contract assumption", "target.closed_domain"]}
        )
        ok, msg = validate_model_card(card, experiments=experiments, contract=contract)
    assert ok is False
    assert "must include at least one entry that exactly matches" in msg


def test_contract_dependencies_with_a_real_assumption_is_accepted() -> None:
    if not RAW_TELCO_CHURN_CSV.is_file():
        print(f"SKIP: {_SKIP_REASON}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        experiments, contract, winner_name, winner_roc_auc = _real_experiments_and_contract_and_winner(Path(tmp))
        card = _valid_card(contract, winner_name, winner_roc_auc).model_copy(
            update={"contract_dependencies": [contract.assumptions[-1]]}
        )
        ok, result = validate_model_card(card, experiments=experiments, contract=contract)
    assert ok, result


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
