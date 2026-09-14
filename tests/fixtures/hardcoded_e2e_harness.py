"""The Phase 5 hardcoded, no-LLM, deterministic end-to-end harness
(PROJECT_PLAN.md §T Phase 5 acceptance).

Runs the full conceptual flow — raw Telco data -> profile -> cleaning ->
clean data -> profile -> EDA stats/figures -> insights -> contract ->
Phase 4 gate -> Crew 2 handoff -> features -> train -> evaluate -> winner
-> `experiments.json` -> `model.joblib` — using ONLY hardcoded, already-
validated plans (`tests/fixtures/hardcoded_plans.py`). **Zero LLM. Zero
Agent. Zero Crew. Zero Flow.**

Not a test file itself — imported by `tests/unit/test_hardcoded_e2e.py`,
which calls `run_hardcoded_e2e` twice (into two separate workspaces) and
compares the results for reproducibility.

Every artifact is written into the caller-supplied `workspace` directory —
never into the repo's real `artifacts/` tree (that would falsely present
this harness's output as a real Crew 1/Crew 2 production run).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import joblib  # noqa: E402
import pandas as pd  # noqa: E402

from harbor_vale.access.handoff import Crew2Handoff, build_crew2_handoff  # noqa: E402
from harbor_vale.contract.builder import build_contract  # noqa: E402
from harbor_vale.contract.schema import DatasetContract  # noqa: E402
from harbor_vale.contract.validator import render_validation_report_markdown, run_validation_gate  # noqa: E402
from harbor_vale.io_paths import RAW_TELCO_CHURN_CSV  # noqa: E402
from harbor_vale.ml.evaluate import (  # noqa: E402
    build_experiments_artifact,
    evaluate_cv_results,
    final_test_evaluation,
    select_winner,
)
from harbor_vale.ml.train import split_train_test, train_all_variants  # noqa: E402
from harbor_vale.plans.cleaning_plan import validate_cleaning_plan  # noqa: E402
from harbor_vale.plans.contract_draft import validate_contract_draft  # noqa: E402
from harbor_vale.plans.experiment_plan import validate_experiment_plan  # noqa: E402
from harbor_vale.plans.feature_plan import validate_feature_plan  # noqa: E402
from harbor_vale.plans.insights_doc import validate_insights_doc  # noqa: E402
from harbor_vale.tools.cleaning_tools import execute_plan  # noqa: E402
from harbor_vale.tools.eda_tools import (  # noqa: E402
    compute_eda_stats,
    generate_numeric_distribution_figure,
    generate_target_rate_figure,
    render_eda_report_html,
    render_insights_markdown,
)
from harbor_vale.tools.feature_tools import build_features  # noqa: E402
from harbor_vale.tools.profiling_tools import profile_dataframe  # noqa: E402
from tests.fixtures.build_example_contract import build_draft  # noqa: E402
from tests.fixtures.hardcoded_plans import (  # noqa: E402
    build_hardcoded_cleaning_plan,
    build_hardcoded_experiment_plan,
    build_hardcoded_feature_plan,
    build_hardcoded_insights_doc,
)

FIXED_CREATED_AT = "2026-01-01T00:00:00Z"
"""A fixed, non-"now"-derived timestamp used everywhere this harness
controls one — so re-running it does not introduce a spurious difference
purely from wall-clock time. The ONE timestamp this harness does NOT
control is `ValidationReport.validated_at` (`contract/validator.py` always
stamps real wall-clock time, by design — a report should honestly record
when validation ran); the double-run reproducibility test explicitly
excludes that one field, never silently ignores an unexplained difference."""


class HardcodedE2EError(RuntimeError):
    """Raised if any stage of the hardcoded pipeline fails — a hardcoded,
    already-validated plan failing here is a genuine bug in this harness or
    the deterministic layer, never an expected "agent failure" (there is no
    agent)."""


@dataclass(frozen=True)
class HardcodedE2EResult:
    workspace: Path
    raw_csv: Path
    clean_data_csv: Path
    dataset_contract_json: Path
    eda_report_html: Path
    insights_md: Path
    validation_report_json: Path
    validation_report_md: Path
    features_csv: Path
    experiments_json: Path
    model_joblib: Path
    gate_passed: bool
    winner_name: str
    winner_estimator: str
    winner_test_roc_auc: float


def run_hardcoded_e2e(workspace: Path, *, run_id: str) -> HardcodedE2EResult:
    """Run the entire deterministic pipeline once, writing every artifact
    under `workspace`. Raises `HardcodedE2EError` (with the real underlying
    failure) if any stage — which should never happen, since every plan
    here is hardcoded and pre-validated — fails.
    """
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    figures_dir = workspace / "figures"

    if not RAW_TELCO_CHURN_CSV.is_file():
        raise HardcodedE2EError(
            f"real raw dataset not found at {RAW_TELCO_CHURN_CSV} — run "
            "`python scripts/download_data.py` first (Phase 2 acquisition)."
        )

    # --- 1. raw profile -----------------------------------------------------
    raw_df = pd.read_csv(RAW_TELCO_CHURN_CSV)
    raw_profile = profile_dataframe(raw_df, target_column="Churn")

    # --- 2. hardcoded CleaningPlan, validated against the raw profile -------
    cleaning_plan = build_hardcoded_cleaning_plan()
    ok, validated_cleaning_plan = validate_cleaning_plan(cleaning_plan, profile=raw_profile)
    if not ok:
        raise HardcodedE2EError(f"hardcoded CleaningPlan failed validation: {validated_cleaning_plan}")

    # --- 3. execute cleaning -> clean_data.csv ------------------------------
    clean_df = execute_plan(raw_df, validated_cleaning_plan)
    clean_data_csv = workspace / "clean_data.csv"
    clean_df.to_csv(clean_data_csv, index=False)

    # --- 4. clean profile + EDA stats/figures -------------------------------
    profile_dataframe(clean_df, target_column="churn")  # clean-data profile, measured but not persisted here
    eda_stats = compute_eda_stats(clean_df, target_column="churn")

    fig1 = generate_target_rate_figure(clean_df, column="contract_type", target_column="churn", out_dir=figures_dir)
    fig2 = generate_target_rate_figure(clean_df, column="payment_method", target_column="churn", out_dir=figures_dir)
    fig3 = generate_numeric_distribution_figure(clean_df, column="monthly_charges", out_dir=figures_dir)
    figure_relpaths = [f"figures/{p.name}" for p in (fig1, fig2, fig3)]

    # --- 5. hardcoded InsightsDoc, validated against the real eda_stats -----
    insights_doc = build_hardcoded_insights_doc(eda_stats)
    ok, validated_insights = validate_insights_doc(insights_doc, eda_stats=eda_stats)
    if not ok:
        raise HardcodedE2EError(f"hardcoded InsightsDoc failed validation: {validated_insights}")

    eda_report_html = render_eda_report_html(
        dataset_name="telco_customer_churn", stats=eda_stats, figures=figure_relpaths,
        insights=validated_insights, out_path=workspace / "eda_report.html",
    )
    insights_md = render_insights_markdown(
        dataset_name="telco_customer_churn", insights=validated_insights, out_path=workspace / "insights.md",
    )

    # --- 6. hardcoded ContractDraft (reuses the already-tested Phase 3 draft) -
    ok, validated_draft = validate_contract_draft(build_draft())
    if not ok:
        raise HardcodedE2EError(f"hardcoded ContractDraft failed validation: {validated_draft}")

    contract = build_contract(
        validated_draft, clean_data_csv,
        contract_version="1.0.0", run_id=run_id, created_by="hardcoded_e2e_harness",
        dataset_name="telco_customer_churn",
        source_documentation_url="https://github.com/IBM/telco-customer-churn-on-icp4d",
        created_at=FIXED_CREATED_AT,
    )
    dataset_contract_json = workspace / "dataset_contract.json"
    dataset_contract_json.write_text(contract.model_dump_json(indent=2), encoding="utf-8")

    # --- 7. Phase 4 validation gate — all FOUR artifacts, must PASS ---------
    report = run_validation_gate(
        clean_data_csv, dataset_contract_json, eda_report_html, insights_md, run_id=run_id,
    )
    (workspace / "validation_report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (workspace / "validation_report.md").write_text(render_validation_report_markdown(report), encoding="utf-8")
    if not report.passed:
        raise HardcodedE2EError(
            f"validation gate FAILED (this should never happen for the hardcoded plans): "
            f"{[f.message for f in report.findings if f.severity == 'ERROR']}"
        )

    # --- 8. Crew 2 handoff — exactly the two approved files -----------------
    handoff = Crew2Handoff(build_crew2_handoff(clean_data_csv, dataset_contract_json))
    crew2_clean_text = handoff.read_handoff("clean_data")
    crew2_contract_text = handoff.read_handoff("dataset_contract")
    import io

    crew2_clean_df = pd.read_csv(io.StringIO(crew2_clean_text))
    crew2_contract = DatasetContract.model_validate_json(crew2_contract_text)

    # --- 9. hardcoded FeaturePlan, validated against the ACTUAL contract ----
    feature_plan = build_hardcoded_feature_plan(crew2_contract)
    ok, validated_feature_plan = validate_feature_plan(feature_plan, contract=crew2_contract)
    if not ok:
        raise HardcodedE2EError(f"hardcoded FeaturePlan failed validation: {validated_feature_plan}")

    feature_result = build_features(crew2_clean_df, crew2_contract, validated_feature_plan)
    features_csv = workspace / "features.csv"
    features_snapshot = feature_result.X.copy()
    features_snapshot[crew2_contract.target.name] = feature_result.y
    features_snapshot.to_csv(features_csv, index=False)

    # --- 10. hardcoded ExperimentPlan; train + evaluate ---------------------
    experiment_plan = build_hardcoded_experiment_plan()
    ok, validated_experiment_plan = validate_experiment_plan(experiment_plan)
    if not ok:
        raise HardcodedE2EError(f"hardcoded ExperimentPlan failed validation: {validated_experiment_plan}")

    split = split_train_test(feature_result.X, feature_result.y)
    trained_variants = train_all_variants(feature_result.preprocessor, validated_experiment_plan, split)
    cv_metrics = evaluate_cv_results(trained_variants, split.y_train)
    variant_order = [v.name for v in validated_experiment_plan.variants]
    winner_name = select_winner(cv_metrics, validated_experiment_plan.primary_metric, variant_order)
    winner = next(t for t in trained_variants if t.variant_name == winner_name)
    test_metrics = final_test_evaluation(winner, split.X_test, split.y_test)

    experiments_artifact = build_experiments_artifact(
        run_id=run_id, plan=validated_experiment_plan, trained_variants=trained_variants,
        cv_metrics=cv_metrics, winner_name=winner_name, test_metrics=test_metrics,
        created_at=FIXED_CREATED_AT,
    )
    experiments_json = workspace / "experiments.json"
    experiments_json.write_text(json.dumps(experiments_artifact, indent=2), encoding="utf-8")

    # --- 11. save the winning pipeline ---------------------------------------
    model_joblib = workspace / "model.joblib"
    joblib.dump(winner.fitted_pipeline, model_joblib)

    return HardcodedE2EResult(
        workspace=workspace,
        raw_csv=RAW_TELCO_CHURN_CSV,
        clean_data_csv=clean_data_csv,
        dataset_contract_json=dataset_contract_json,
        eda_report_html=eda_report_html,
        insights_md=insights_md,
        validation_report_json=workspace / "validation_report.json",
        validation_report_md=workspace / "validation_report.md",
        features_csv=features_csv,
        experiments_json=experiments_json,
        model_joblib=model_joblib,
        gate_passed=report.passed,
        winner_name=winner_name,
        winner_estimator=winner.estimator,
        winner_test_roc_auc=test_metrics["roc_auc"],
    )
