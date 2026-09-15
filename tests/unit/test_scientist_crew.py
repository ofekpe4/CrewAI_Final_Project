"""Phase 7 — Crew 2 (Scientist Crew) mocked/offline tests (PROJECT_PLAN.md §T
Phase 7, Internal Gate 7.8). **No OPENAI_API_KEY required, no network call**
— same `crewai.llms.base_llm.BaseLLM` scripting technique
`tests/unit/test_analyst_crew.py` already proves against the real pinned
`crewai==1.15.20`. The *real* CrewAI `Agent`/`Task`/`Crew`/guardrail/
callback/retry machinery all run for real; only the LLM backend is fake.

Run directly: `python tests/unit/test_scientist_crew.py`
"""

import os
import shutil
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from crewai import Process  # noqa: E402
from crewai.llms.base_llm import BaseLLM  # noqa: E402

from harbor_vale.access.handoff import build_crew2_handoff  # noqa: E402
from harbor_vale.contract.builder import build_contract  # noqa: E402
from harbor_vale.contract.schema import (  # noqa: E402
    BusinessRangeConstraint,
    ClosedDomainConstraint,
    DtypeConstraint,
    EnforcementLevel,
    ExcludedFeature,
    ExclusionType,
    NullableConstraint,
    SemanticType,
    UnitConstraint,
    UniqueConstraint,
)
from harbor_vale.crews.scientist_crew.guardrails import GUARDRAIL_MAX_RETRIES  # noqa: E402
from harbor_vale.crews.scientist_crew.runtime import Crew2RunContext, crew2_run_context  # noqa: E402
from harbor_vale.crews.scientist_crew.scientist_crew import build_scientist_crew, run_scientist_crew  # noqa: E402
from harbor_vale.crews.scientist_crew.tools import read_experiment_results, read_feature_plan, read_handoff  # noqa: E402
from harbor_vale.ml.evaluate import build_experiments_artifact, evaluate_cv_results, final_test_evaluation, select_winner  # noqa: E402
from harbor_vale.ml.train import split_train_test, train_all_variants  # noqa: E402
from harbor_vale.plans.contract_draft import ColumnSemanticDraft, ContractDraft, PrimaryKeyDraft, TargetDraft  # noqa: E402
from harbor_vale.plans.experiment_plan import ExperimentPlan, ExperimentVariant, validate_experiment_plan  # noqa: E402
from harbor_vale.plans.feature_plan import (  # noqa: E402
    AdvisoryOverride,
    ContractAcknowledgment,
    EncoderSpec,
    FeaturePlan,
    TransformSpec,
    validate_feature_plan,
)
from harbor_vale.plans.model_card import MetricClaim, ModelCard, validate_model_card  # noqa: E402
from harbor_vale.tools.feature_tools import build_features  # noqa: E402

_PASS: list[str] = []
_FAIL: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        _PASS.append(name)
        print(f"PASS  {name}")
    else:
        _FAIL.append(name)
        print(f"FAIL  {name}  {detail}")


# ---------------------------------------------------------------------------
# A tiny, hand-controlled "clean Telco-shaped" fixture — a fully-built
# DatasetContract + clean_data.csv, exactly the two-file shape the REAL
# Crew 1 -> Crew 2 handoff produces. Small on purpose (fast tests), but a
# real, gate-buildable contract (via contract.builder.build_contract), not
# a hand-typed dict.
# ---------------------------------------------------------------------------

_N_ROWS = 80


def _tiny_clean_df() -> "pd.DataFrame":
    rng = np.random.default_rng(11)
    n = _N_ROWS
    contract_types = np.array(["Month-to-month", "One year", "Two year"])
    ct = contract_types[rng.integers(0, 3, size=n)]
    tenure = rng.integers(1, 72, size=n)
    monthly = rng.uniform(18, 120, size=n)
    total = monthly * tenure + rng.normal(0, 5, size=n)
    logits = -1.0 + (ct == "Month-to-month") * 1.8 - 0.02 * tenure + 0.01 * (monthly - 70)
    prob = 1 / (1 + np.exp(-logits))
    churn = (rng.uniform(size=n) < prob).astype(int)
    return pd.DataFrame(
        {
            "customer_id": [f"C{i:04d}" for i in range(n)],
            "contract_type": ct,
            "tenure_months": tenure,
            "monthly_charges": monthly,
            "total_charges": total,
            "churn": churn,
        }
    )


def _fixture_draft() -> ContractDraft:
    return ContractDraft(
        target=TargetDraft(
            name="churn",
            task_type="binary_classification",
            dtype=DtypeConstraint(expected="int64", justification="binary label by construction"),
            closed_domain=ClosedDomainConstraint(values=["0", "1"], justification="binary label by construction"),
            nullable=NullableConstraint(value=False, justification="a row without a label is unusable"),
        ),
        required_features=["contract_type", "tenure_months", "monthly_charges"],
        excluded_features=[
            ExcludedFeature(
                name="customer_id",
                exclusion_type=ExclusionType.IDENTIFIER,
                enforcement=EnforcementLevel.HARD,
                justification="a unique key carries no generalizable signal",
            ),
            ExcludedFeature(
                name="total_charges",
                exclusion_type=ExclusionType.REDUNDANCY_COLLINEARITY,
                enforcement=EnforcementLevel.ADVISORY,
                justification="collinear with tenure_months x monthly_charges but legitimately available at prediction time",
            ),
        ],
        primary_key=PrimaryKeyDraft(
            columns=["customer_id"], unique=UniqueConstraint(value=True, justification="one row per customer")
        ),
        columns=[
            ColumnSemanticDraft(
                name="customer_id",
                semantic_type=SemanticType.IDENTIFIER,
                nullable=NullableConstraint(value=False, justification="every row identifies a customer"),
            ),
            ColumnSemanticDraft(
                name="contract_type",
                semantic_type=SemanticType.CATEGORICAL,
                nullable=NullableConstraint(value=False, justification="every account has a contract type"),
                closed_domain=ClosedDomainConstraint(
                    values=["Month-to-month", "One year", "Two year"],
                    justification="the provider offers exactly these three contract terms",
                ),
            ),
            ColumnSemanticDraft(
                name="tenure_months",
                semantic_type=SemanticType.NUMERIC,
                dtype=DtypeConstraint(expected="int64", justification="whole months of tenure"),
                nullable=NullableConstraint(value=False, justification="every account has a tenure"),
            ),
            ColumnSemanticDraft(
                name="monthly_charges",
                semantic_type=SemanticType.MONETARY,
                dtype=DtypeConstraint(expected="float64", justification="continuous monetary amount"),
                unit=UnitConstraint(
                    value="currency_unspecified", evidence="the source documentation does not state a currency", confidence="low"
                ),
                nullable=NullableConstraint(value=False, justification="every account has a recurring charge"),
                business_range=BusinessRangeConstraint(min=0, max=None, justification="a charge cannot be negative"),
            ),
            ColumnSemanticDraft(
                name="total_charges",
                semantic_type=SemanticType.MONETARY,
                dtype=DtypeConstraint(expected="float64", justification="continuous monetary amount"),
                unit=UnitConstraint(
                    value="currency_unspecified", evidence="the source documentation does not state a currency", confidence="low"
                ),
                nullable=NullableConstraint(value=False, justification="every account has an accumulated charge"),
            ),
        ],
        assumptions=[
            "one row per customer; customer_id is unique",
            "total_charges is redundancy_collinearity, not target_leakage",
        ],
    )


def _build_fixture_handoff(tmp_path: Path):
    """Writes a real, built `DatasetContract` + `clean_data.csv` pair (the
    exact two-file shape of the approved handoff) and returns
    `(clean_csv_path, contract_json_path, contract, clean_df)`."""
    clean_df = _tiny_clean_df()
    crew1_dir = tmp_path / "crew1"
    crew1_dir.mkdir(parents=True, exist_ok=True)
    clean_csv_path = crew1_dir / "clean_data.csv"
    clean_df.to_csv(clean_csv_path, index=False)

    contract = build_contract(
        _fixture_draft(),
        clean_csv_path,
        contract_version="1.0.0",
        run_id="fixture-run",
        created_by="test_fixture",
        dataset_name="telco_test_fixture",
        source_documentation_url="https://example.invalid/telco",
    )
    contract_json_path = crew1_dir / "dataset_contract.json"
    contract_json_path.write_text(contract.model_dump_json(indent=2), encoding="utf-8")
    return clean_csv_path, contract_json_path, contract, clean_df


def _valid_feature_plan(contract) -> FeaturePlan:
    return FeaturePlan(
        contract_acknowledgment=ContractAcknowledgment(
            contract_version=contract.contract_version,
            target_confirmed=True,
            required_features_confirmed=True,
            excluded_features_respected=["customer_id"],
            constraints_relied_upon=[],
        ),
        use_features=["contract_type", "tenure_months", "monthly_charges", "total_charges"],
        transforms=[TransformSpec(column="monthly_charges", kind="log1p")],
        encoders=[EncoderSpec(column="contract_type", kind="onehot")],
        advisory_overrides=[
            AdvisoryOverride(
                column="total_charges",
                justification="collinear with tenure_months x monthly_charges but legitimately available at prediction time",
            )
        ],
    )


def _feature_plan_missing_required_feature_json(contract) -> str:
    """Structurally valid FeaturePlan JSON, semantically rejected: drops
    `tenure_months`, a `required_features` entry."""
    return FeaturePlan(
        contract_acknowledgment=ContractAcknowledgment(
            contract_version=contract.contract_version,
            target_confirmed=True,
            required_features_confirmed=True,
            excluded_features_respected=["customer_id"],
        ),
        use_features=["contract_type", "monthly_charges"],
        encoders=[EncoderSpec(column="contract_type", kind="onehot")],
    ).model_dump_json()


def _feature_plan_hard_excluded_json(contract) -> str:
    """Structurally valid FeaturePlan JSON, semantically rejected: uses the
    hard-excluded `customer_id`."""
    return FeaturePlan(
        contract_acknowledgment=ContractAcknowledgment(
            contract_version=contract.contract_version,
            target_confirmed=True,
            required_features_confirmed=True,
            excluded_features_respected=[],
        ),
        use_features=["contract_type", "tenure_months", "monthly_charges", "customer_id"],
        encoders=[EncoderSpec(column="contract_type", kind="onehot")],
    ).model_dump_json()


def _valid_experiment_plan() -> ExperimentPlan:
    return ExperimentPlan(
        primary_metric="roc_auc",
        metric_rationale="churn is imbalanced; ROC-AUC ranks independent of threshold",
        cv_folds=3,
        variants=[
            ExperimentVariant(
                name="logreg_baseline", estimator="logistic_regression",
                params={"C": 1.0, "class_weight": "balanced", "max_iter": 1000}, rationale="interpretable baseline",
            ),
            ExperimentVariant(
                name="rf_default", estimator="random_forest",
                params={"n_estimators": 50, "max_depth": 5}, rationale="captures non-linear interactions",
            ),
        ],
    )


def _experiment_plan_single_variant_json() -> str:
    """Structurally valid ExperimentPlan JSON, semantically rejected: only
    one variant (< 2 required)."""
    return ExperimentPlan(
        primary_metric="roc_auc",
        metric_rationale="fabricated: only one variant",
        cv_folds=3,
        variants=[
            ExperimentVariant(
                name="only_one", estimator="logistic_regression", params={"C": 1.0}, rationale="the only variant"
            )
        ],
    ).model_dump_json()


class ScriptedLLM(BaseLLM):
    """Returns one canned string per call, in order; raises if exhausted."""

    responses: list = []
    calls: list = []

    def __init__(self, responses: list, **kwargs: Any) -> None:
        super().__init__(model="scripted/fake", temperature=0.0, **kwargs)
        self.responses = list(responses)
        self.calls = []

    def call(self, messages, tools=None, callbacks=None, available_functions=None,
              from_task=None, from_agent=None, response_model=None, **kwargs):
        idx = len(self.calls)
        if idx >= len(self.responses):
            raise AssertionError(f"ScriptedLLM exhausted after {idx} calls — test under-supplied canned responses")
        resp = self.responses[idx]
        self.calls.append(resp)
        return resp

    def supports_function_calling(self) -> bool:
        return False

    def supports_stop_words(self) -> bool:
        return False


def run_with_scripts(clean_csv, contract_json, responses: list[str], *, workspace: Path):
    llm = ScriptedLLM(responses)
    result = run_scientist_crew(
        clean_data_csv=clean_csv,
        dataset_contract_json=contract_json,
        run_id="test-run",
        contract_version="1.0.0",
        workspace=workspace,
        llm=llm,
    )
    return result, llm


def _precompute_experiments(contract, clean_df, feature_plan, experiment_plan) -> dict:
    """Independently runs the SAME deterministic pipeline the real Task 2
    callback runs, so a test can build a `ModelCard` fixture that cites a
    real, exactly-matching measured metric value (training is fully
    deterministic given fixed seeds/data/params)."""
    result = build_features(clean_df, contract, feature_plan)
    split = split_train_test(result.X, result.y)
    trained = train_all_variants(result.preprocessor, experiment_plan, split)
    cv_metrics = evaluate_cv_results(trained, split.y_train)
    winner_name = select_winner(cv_metrics, experiment_plan.primary_metric, [v.name for v in experiment_plan.variants])
    winner = next(t for t in trained if t.variant_name == winner_name)
    test_metrics = final_test_evaluation(winner, split.X_test, split.y_test)
    return build_experiments_artifact(
        run_id="precompute", plan=experiment_plan, trained_variants=trained,
        cv_metrics=cv_metrics, winner_name=winner_name, test_metrics=test_metrics,
    )


# ---------------------------------------------------------------------------
# Structural tests — no crew.kickoff() needed.
# ---------------------------------------------------------------------------


def test_pattern_a_structure(tmp_path: Path) -> None:
    clean_csv, contract_json, _contract, _df = _build_fixture_handoff(tmp_path)
    handoff = build_crew2_handoff(clean_csv, contract_json, actor="crew2")
    from harbor_vale.access.handoff import Crew2Handoff

    ctx = Crew2RunContext(
        run_id="struct-test", handoff=Crew2Handoff(handoff), handoff_status="gate_passed",
        contract_version="1.0.0", validation_warnings=0,
        features_csv=tmp_path / "features.csv", model_joblib=tmp_path / "model.joblib",
        experiments_json=tmp_path / "experiments.json", evaluation_report_md=tmp_path / "evaluation_report.md",
        model_card_md=tmp_path / "model_card.md", internal_dir=tmp_path / "_internal",
    )
    with crew2_run_context(ctx):
        crew = build_scientist_crew(ctx, llm=ScriptedLLM([]))

    check("test_pattern_a_structure: exactly 3 agents", len(crew.agents) == 3)
    check("test_pattern_a_structure: exactly 3 tasks", len(crew.tasks) == 3)
    check("test_pattern_a_structure: Process.sequential", crew.process == Process.sequential)
    t1, t2, t3 = crew.tasks
    check("test_pattern_a_structure: task1 output_pydantic == FeaturePlan", t1.output_pydantic is FeaturePlan)
    check("test_pattern_a_structure: task2 output_pydantic == ExperimentPlan", t2.output_pydantic is ExperimentPlan)
    check("test_pattern_a_structure: task3 output_pydantic == ModelCard", t3.output_pydantic is ModelCard)
    check("test_pattern_a_structure: task1 context == []", t1.context == [])
    check("test_pattern_a_structure: task2 context == [task1]", t2.context == [t1])
    check("test_pattern_a_structure: task3 context == [task1, task2]", t3.context == [t1, t2])
    for t in (t1, t2, t3):
        check(
            f"test_pattern_a_structure: {t.agent.role[:20]!r} guardrail_max_retries == {GUARDRAIL_MAX_RETRIES}",
            t.guardrail_max_retries == GUARDRAIL_MAX_RETRIES,
        )
        check(f"test_pattern_a_structure: {t.agent.role[:20]!r} guardrail is set", t.guardrail is not None)
        check(f"test_pattern_a_structure: {t.agent.role[:20]!r} callback is set", t.callback is not None)


def test_crew2_tool_surface_no_free_path_parameter() -> None:
    """Internal Gate 7.1 — no Crew 2 tool accepts a free path parameter."""
    import inspect

    for tool_fn, expected_params in (
        (read_handoff, ["name"]),
        (read_feature_plan, []),
        (read_experiment_results, []),
    ):
        sig = inspect.signature(tool_fn.func if hasattr(tool_fn, "func") else tool_fn)
        params = [p for p in sig.parameters]
        check(
            f"test_crew2_tool_surface_no_free_path_parameter: {tool_fn.name} params == {expected_params}",
            params == expected_params,
            f"got {params}",
        )
    import typing

    sig = inspect.signature(read_handoff.func if hasattr(read_handoff, "func") else read_handoff)
    annotation = sig.parameters["name"].annotation
    check(
        "test_crew2_tool_surface_no_free_path_parameter: read_handoff.name is a closed 2-value Literal",
        set(typing.get_args(annotation)) == {"clean_data", "dataset_contract"},
    )


# ---------------------------------------------------------------------------
# End-to-end (scripted LLM) — happy path.
# ---------------------------------------------------------------------------


def test_crew2_produces_artifacts(tmp_path: Path) -> None:
    clean_csv, contract_json, contract, df = _build_fixture_handoff(tmp_path)
    workspace = tmp_path / "crew2"
    feature_plan = _valid_feature_plan(contract)
    experiment_plan = _valid_experiment_plan()
    expected_experiments = _precompute_experiments(contract, df, feature_plan, experiment_plan)
    winner = expected_experiments["winner"]

    model_card = ModelCard(
        purpose="Predict customer churn to prioritize retention outreach.",
        intended_use="Score current customers monthly for churn risk.",
        training_data_summary=f"{len(df)}-row fixture derived from the approved Crew 1 handoff.",
        metrics_summary=[
            MetricClaim(metric="roc_auc", split="test", variant_name=winner["name"], value=winner["test_metrics"]["roc_auc"])
        ],
        contract_dependencies=["one row per customer; customer_id is unique"],
        limitations=["Evaluated on a small synthetic fixture, not production-scale data."],
    )

    responses = [
        feature_plan.model_dump_json(),
        experiment_plan.model_dump_json(),
        model_card.model_dump_json(),
    ]
    result, llm = run_with_scripts(clean_csv, contract_json, responses, workspace=workspace)

    check("test_crew2_produces_artifacts: status == completed", result.status == "completed", result.failure_message or "")
    check("test_crew2_produces_artifacts: exactly 3 LLM calls (no retries needed)", len(llm.calls) == 3)
    check("test_crew2_produces_artifacts: features.csv exists+non-empty", result.features_csv.is_file() and result.features_csv.stat().st_size > 0)
    check("test_crew2_produces_artifacts: model.joblib exists+non-empty", result.model_joblib.is_file() and result.model_joblib.stat().st_size > 0)
    check("test_crew2_produces_artifacts: experiments.json exists+non-empty", result.experiments_json.is_file() and result.experiments_json.stat().st_size > 0)
    check("test_crew2_produces_artifacts: evaluation_report.md exists+non-empty", result.evaluation_report_md.is_file() and result.evaluation_report_md.stat().st_size > 0)
    check("test_crew2_produces_artifacts: model_card.md exists+non-empty", result.model_card_md.is_file() and result.model_card_md.stat().st_size > 0)
    check("test_crew2_produces_artifacts: not degraded on the happy path", result.model_card_degraded is False)
    check("test_crew2_produces_artifacts: winner matches the deterministic Python selection", result.winner_name == winner["name"])

    # Metric truth: evaluation_report.md's numbers come straight from experiments.json.
    report_text = result.evaluation_report_md.read_text(encoding="utf-8")
    import json

    actual_experiments = json.loads(result.experiments_json.read_text(encoding="utf-8"))
    check(
        "test_crew2_produces_artifacts: evaluation_report.md cites the real winner name",
        actual_experiments["winner"]["name"] in report_text,
    )
    check(
        "test_crew2_produces_artifacts: evaluation_report.md cites the real winner roc_auc value",
        f"{actual_experiments['winner']['test_metrics']['roc_auc']:.4f}" in report_text,
    )
    check(
        "test_crew2_produces_artifacts: model_card.md cites the real verified metric value",
        f"{winner['test_metrics']['roc_auc']:.4f}" in result.model_card_md.read_text(encoding="utf-8"),
    )
    shutil.rmtree(workspace, ignore_errors=True)


# ---------------------------------------------------------------------------
# Critical-agent failure — Agent 4 (Feature Engineer).
# ---------------------------------------------------------------------------


def test_feature_engineer_missing_required_feature_halts(tmp_path: Path) -> None:
    clean_csv, contract_json, contract, _df = _build_fixture_handoff(tmp_path)
    workspace = tmp_path / "crew2"
    responses = [_feature_plan_missing_required_feature_json(contract)] * (GUARDRAIL_MAX_RETRIES + 1)
    result, llm = run_with_scripts(clean_csv, contract_json, responses, workspace=workspace)

    check("test_feature_engineer_missing_required_feature_halts: status == halted_agent_failure", result.status == "halted_agent_failure")
    check("test_feature_engineer_missing_required_feature_halts: features.csv NOT created", not result.features_csv.is_file())
    check("test_feature_engineer_missing_required_feature_halts: model.joblib NOT created", not result.model_joblib.is_file())
    check("test_feature_engineer_missing_required_feature_halts: exactly guardrail_max_retries+1 LLM calls", len(llm.calls) == GUARDRAIL_MAX_RETRIES + 1)
    rejected_path = workspace / "_internal" / "rejected_feature_plan.json"
    check("test_feature_engineer_missing_required_feature_halts: rejected plan preserved under _internal/", rejected_path.is_file())
    shutil.rmtree(workspace, ignore_errors=True)


def test_feature_engineer_hard_exclusion_blocked(tmp_path: Path) -> None:
    """customerID-shaped hard exclusion is mechanically blocked."""
    clean_csv, contract_json, contract, _df = _build_fixture_handoff(tmp_path)
    workspace = tmp_path / "crew2"
    responses = [_feature_plan_hard_excluded_json(contract)] * (GUARDRAIL_MAX_RETRIES + 1)
    result, _llm = run_with_scripts(clean_csv, contract_json, responses, workspace=workspace)

    check("test_feature_engineer_hard_exclusion_blocked: status == halted_agent_failure", result.status == "halted_agent_failure")
    check("test_feature_engineer_hard_exclusion_blocked: customer_id (identifier) never used as a feature", not result.features_csv.is_file())
    shutil.rmtree(workspace, ignore_errors=True)


def test_feature_plan_direct_guardrail_edge_cases(tmp_path: Path) -> None:  # noqa: ARG001
    """Fast, no-LLM coverage of every FeaturePlan semantic rule §G.1 point 7 lists."""
    _clean_csv, _contract_json, contract, _df = _build_fixture_handoff(tmp_path)
    base = _valid_feature_plan(contract)

    # target as a feature
    bad = base.model_copy(update={"use_features": base.use_features + ["churn"]})
    ok, msg = validate_feature_plan(bad, contract=contract)
    check("test_feature_plan_direct_guardrail_edge_cases: target as feature rejected", ok is False and "churn" in msg)

    # unknown/guessed column spelling
    bad = base.model_copy(update={"use_features": base.use_features + ["monthly_charges_usd"]})
    ok, msg = validate_feature_plan(bad, contract=contract)
    check("test_feature_plan_direct_guardrail_edge_cases: unknown column rejected", ok is False)

    # advisory override without justification entry
    bad = base.model_copy(update={"advisory_overrides": []})
    ok, msg = validate_feature_plan(bad, contract=contract)
    check("test_feature_plan_direct_guardrail_edge_cases: advisory use without override rejected", ok is False and "advisory" in msg)

    # valid advisory override accepted
    ok, plan = validate_feature_plan(base, contract=contract)
    check("test_feature_plan_direct_guardrail_edge_cases: valid advisory override accepted", ok is True)

    # missing required feature
    bad = base.model_copy(update={"use_features": ["contract_type"]})
    ok, msg = validate_feature_plan(bad, contract=contract)
    check("test_feature_plan_direct_guardrail_edge_cases: missing required_features rejected", ok is False)

    # contract-version mismatch
    bad_ack = base.contract_acknowledgment.model_copy(update={"contract_version": "9.9.9"})
    bad = base.model_copy(update={"contract_acknowledgment": bad_ack})
    ok, msg = validate_feature_plan(bad, contract=contract)
    check("test_feature_plan_direct_guardrail_edge_cases: contract-version mismatch rejected", ok is False)


# ---------------------------------------------------------------------------
# Critical-agent failure — Agent 5 (Modeling Specialist).
# ---------------------------------------------------------------------------


def test_modeling_specialist_single_variant_halts(tmp_path: Path) -> None:
    clean_csv, contract_json, contract, _df = _build_fixture_handoff(tmp_path)
    workspace = tmp_path / "crew2"
    feature_plan = _valid_feature_plan(contract)
    responses = (
        [feature_plan.model_dump_json()]
        + [_experiment_plan_single_variant_json()] * (GUARDRAIL_MAX_RETRIES + 1)
    )
    result, _llm = run_with_scripts(clean_csv, contract_json, responses, workspace=workspace)

    check("test_modeling_specialist_single_variant_halts: status == halted_agent_failure", result.status == "halted_agent_failure")
    check("test_modeling_specialist_single_variant_halts: features.csv WAS created (Task 1 succeeded)", result.features_csv.is_file())
    check("test_modeling_specialist_single_variant_halts: model.joblib NOT created", not result.model_joblib.is_file())
    check("test_modeling_specialist_single_variant_halts: experiments.json NOT created", not result.experiments_json.is_file())
    check("test_modeling_specialist_single_variant_halts: evaluation_report.md NOT created", not result.evaluation_report_md.is_file())
    rejected_path = workspace / "_internal" / "rejected_experiment_plan.json"
    check("test_modeling_specialist_single_variant_halts: rejected plan preserved under _internal/", rejected_path.is_file())
    shutil.rmtree(workspace, ignore_errors=True)


def test_experiment_plan_frozen_variant_set_enforced() -> None:
    ok, msg = validate_experiment_plan(
        {
            "primary_metric": "roc_auc", "metric_rationale": "r", "cv_folds": 3,
            "variants": [
                {"name": "a", "estimator": "xgboost", "params": {}, "rationale": "r"},
                {"name": "b", "estimator": "logistic_regression", "params": {}, "rationale": "r"},
            ],
        }
    )
    check("test_experiment_plan_frozen_variant_set_enforced: xgboost rejected (not in frozen set)", ok is False)


# ---------------------------------------------------------------------------
# Narrative fallback — Agent 6 (Responsible AI Documenter).
# ---------------------------------------------------------------------------


def test_responsible_ai_documenter_fabricated_metric_falls_back(tmp_path: Path) -> None:
    clean_csv, contract_json, contract, df = _build_fixture_handoff(tmp_path)
    workspace = tmp_path / "crew2"
    feature_plan = _valid_feature_plan(contract)
    experiment_plan = _valid_experiment_plan()

    fabricated_card_json = ModelCard(
        purpose="p", intended_use="i", training_data_summary="t",
        metrics_summary=[MetricClaim(metric="roc_auc", split="test", variant_name="does_not_exist", value=0.9999)],
        contract_dependencies=["one row per customer; customer_id is unique"],
    ).model_dump_json()

    responses = (
        [feature_plan.model_dump_json()]
        + [experiment_plan.model_dump_json()]
        + [fabricated_card_json] * (GUARDRAIL_MAX_RETRIES + 1)
    )
    result, llm = run_with_scripts(clean_csv, contract_json, responses, workspace=workspace)

    check("test_responsible_ai_documenter_fabricated_metric_falls_back: status == completed (NOT halted)", result.status == "completed", result.failure_message or "")
    check("test_responsible_ai_documenter_fabricated_metric_falls_back: model_card_degraded == True", result.model_card_degraded is True)
    check("test_responsible_ai_documenter_fabricated_metric_falls_back: degraded_reason is set", bool(result.model_card_degraded_reason))

    card_text = result.model_card_md.read_text(encoding="utf-8")
    check("test_responsible_ai_documenter_fabricated_metric_falls_back: visible banner present", "auto-generated after agent output failed validation" in card_text)
    check("test_responsible_ai_documenter_fabricated_metric_falls_back: fabricated 0.9999 value NOT rendered", "0.9999" not in card_text)
    check(
        "test_responsible_ai_documenter_fabricated_metric_falls_back: exactly 2 + (guardrail_max_retries+1) LLM calls",
        len(llm.calls) == 2 + (GUARDRAIL_MAX_RETRIES + 1),
    )
    shutil.rmtree(workspace, ignore_errors=True)


def test_model_card_direct_guardrail_fairness_metric_unsupported() -> None:
    """A 'fairness' metric is structurally inexpressible — MetricName is a
    closed Literal drawn only from what ml/evaluate.py actually computes."""
    try:
        MetricClaim(metric="fairness", split="test", variant_name="x", value=0.5)
    except Exception:  # noqa: BLE001 — pydantic ValidationError, closed Literal rejects it
        check("test_model_card_direct_guardrail_fairness_metric_unsupported: fairness metric structurally rejected", True)
    else:
        check("test_model_card_direct_guardrail_fairness_metric_unsupported: fairness metric structurally rejected", False)


def test_model_card_direct_guardrail_real_metric_accepted(tmp_path: Path) -> None:
    clean_csv, contract_json, contract, df = _build_fixture_handoff(tmp_path)
    feature_plan = _valid_feature_plan(contract)
    experiment_plan = _valid_experiment_plan()
    experiments = _precompute_experiments(contract, df, feature_plan, experiment_plan)
    winner = experiments["winner"]

    card = ModelCard(
        purpose="p", intended_use="i", training_data_summary="t",
        metrics_summary=[MetricClaim(metric="roc_auc", split="test", variant_name=winner["name"], value=winner["test_metrics"]["roc_auc"])],
        contract_dependencies=["one row per customer; customer_id is unique"],
    )
    ok, _ = validate_model_card(card, experiments=experiments, contract=contract)
    check("test_model_card_direct_guardrail_real_metric_accepted: real measured metric accepted", ok is True)

    bad_card = card.model_copy(
        update={"metrics_summary": [MetricClaim(metric="roc_auc", split="test", variant_name=winner["name"], value=0.123456)]}
    )
    ok, msg = validate_model_card(bad_card, experiments=experiments, contract=contract)
    check("test_model_card_direct_guardrail_real_metric_accepted: fabricated numeric value rejected", ok is False and "invent" in msg)

    no_dep_card = card.model_copy(update={"contract_dependencies": ["a made up assumption never in the contract"]})
    ok, msg = validate_model_card(no_dep_card, experiments=experiments, contract=contract)
    check("test_model_card_direct_guardrail_real_metric_accepted: non-real contract_dependencies rejected", ok is False)


# ---------------------------------------------------------------------------
# Boundary — Crew 2 tools/guardrails reach ONLY the two-file handoff.
# ---------------------------------------------------------------------------


def test_deterministic_winner_selection_reproducible(tmp_path: Path) -> None:
    clean_csv, contract_json, contract, df = _build_fixture_handoff(tmp_path)
    feature_plan = _valid_feature_plan(contract)
    experiment_plan = _valid_experiment_plan()
    exp1 = _precompute_experiments(contract, df, feature_plan, experiment_plan)
    exp2 = _precompute_experiments(contract, df, feature_plan, experiment_plan)
    check(
        "test_deterministic_winner_selection_reproducible: same inputs => same winner",
        exp1["winner"]["name"] == exp2["winner"]["name"],
    )
    check(
        "test_deterministic_winner_selection_reproducible: same inputs => identical measured metrics",
        exp1["winner"]["test_metrics"] == exp2["winner"]["test_metrics"],
    )


ALL_TESTS_WITH_TMPDIR = [
    test_pattern_a_structure,
    test_crew2_produces_artifacts,
    test_feature_engineer_missing_required_feature_halts,
    test_feature_engineer_hard_exclusion_blocked,
    test_feature_plan_direct_guardrail_edge_cases,
    test_modeling_specialist_single_variant_halts,
    test_responsible_ai_documenter_fabricated_metric_falls_back,
    test_model_card_direct_guardrail_real_metric_accepted,
    test_deterministic_winner_selection_reproducible,
]

ALL_TESTS_NO_ARGS = [
    test_crew2_tool_surface_no_free_path_parameter,
    test_experiment_plan_frozen_variant_set_enforced,
    test_model_card_direct_guardrail_fairness_metric_unsupported,
]


def main() -> int:
    import tempfile

    for fn in ALL_TESTS_WITH_TMPDIR:
        with tempfile.TemporaryDirectory() as td:
            try:
                fn(Path(td))
            except Exception as exc:  # noqa: BLE001
                _FAIL.append(fn.__name__)
                print(f"FAIL  {fn.__name__}  raised {type(exc).__name__}: {exc}")

    for fn in ALL_TESTS_NO_ARGS:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            _FAIL.append(fn.__name__)
            print(f"FAIL  {fn.__name__}  raised {type(exc).__name__}: {exc}")

    print(f"\n{len(_PASS)} passed, {len(_FAIL)} failed")
    if _FAIL:
        print("all failed:", _FAIL)
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
