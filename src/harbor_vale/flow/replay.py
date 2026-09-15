"""Deterministic replay of stored, guardrail-accepted agent plans
(PROJECT_PLAN.md §R.1 point 7/11, §H, Phase 8 Internal Gate 8.10).

**Makes ZERO LLM calls.** For each Crew 1/Crew 2 stage, loads the
guardrail-ACCEPTED structured output the corresponding live callback
already persists under `_internal/*.json`
(`crews/analyst_crew/callbacks.py`, `crews/scientist_crew/callbacks.py`),
re-validates it through the exact same `validate_*` function a live
guardrail calls, and re-executes the exact same deterministic Python layer
a live callback calls — `tools/cleaning_tools.execute_plan`,
`contract/builder.build_contract`, `tools/feature_tools.build_features`,
`ml/train.py`/`ml/evaluate.py`, `tools/report_tools.py`. The EDA figure-
selection helpers are imported directly from
`crews.analyst_crew.callbacks` rather than re-implemented — one figure-
selection policy, not two that could silently drift apart.

Writes into a dedicated run-scoped workspace (`io_paths.replay_workspace`)
— **never** into the real `artifacts/crew1/`/`artifacts/crew2/` trees, so a
replay run can never overwrite a genuine production run's committed output.

A degraded live run (no stored `insights_doc.json`/`model_card.json` — see
`callbacks.py`'s persistence docstrings) replays as DEGRADED too — replay
reloads what a live run actually produced, it never fabricates a document
that was never accepted in the first place.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import pandas as pd

from harbor_vale.contract.builder import build_contract
from harbor_vale.contract.schema import DatasetContract
from harbor_vale.crews.analyst_crew.callbacks import (
    _DISTRIBUTION_FIGURE_CANDIDATES,
    _MAX_TARGET_RATE_FIGURES,
    _TARGET_RATE_FIGURE_CANDIDATES,
    _fallback_distribution_column,
    _fallback_target_rate_columns,
    _resolve_column,
)
from harbor_vale.io_paths import CREW1_INTERNAL, CREW2_INTERNAL
from harbor_vale.logging_setup import get_logger
from harbor_vale.ml.evaluate import (
    build_experiments_artifact,
    evaluate_cv_results,
    final_test_evaluation,
    select_winner,
)
from harbor_vale.ml.train import split_train_test, train_all_variants
from harbor_vale.plans.cleaning_plan import validate_cleaning_plan
from harbor_vale.plans.contract_draft import validate_contract_draft
from harbor_vale.plans.experiment_plan import validate_experiment_plan
from harbor_vale.plans.feature_plan import validate_feature_plan
from harbor_vale.plans.insights_doc import validate_insights_doc
from harbor_vale.plans.model_card import validate_model_card
from harbor_vale.tools.cleaning_tools import execute_plan
from harbor_vale.tools.eda_tools import (
    compute_eda_stats,
    generate_numeric_distribution_figure,
    generate_target_rate_figure,
    render_eda_report_html,
    render_insights_markdown,
)
from harbor_vale.tools.feature_tools import build_features
from harbor_vale.tools.profiling_tools import profile_dataframe
from harbor_vale.tools.report_tools import render_evaluation_report_markdown, render_model_card_markdown

logger = get_logger(__name__)

_TARGET_COLUMN_RAW = "Churn"
_TARGET_COLUMN_CLEAN = "churn"
_DATASET_NAME = "telco_customer_churn"
_SOURCE_DOC_URL = "https://github.com/IBM/telco-customer-churn-on-icp4d"


class ReplayMissingArtifactError(RuntimeError):
    """Raised when a required stored, guardrail-accepted structured plan is
    not present on disk. Replay cannot fabricate one — a fresh live run is
    required to produce it first (§Internal Gate 8.10)."""


@dataclass
class ReplayCrew1Result:
    """Duck-types `Crew1Result`'s public attributes (Phase 6) — the Flow's
    `run_analyst_crew` node reads either kind through the same field names,
    never branching on which one it got."""

    completed: bool
    failure_message: str | None
    eda_degraded: bool
    clean_data_csv: Path
    dataset_contract_json: Path
    eda_report_html: Path
    insights_md: Path


@dataclass
class ReplayCrew2Result:
    """Duck-types `Crew2Result`'s public attributes (Phase 7)."""

    completed: bool
    failure_message: str | None
    model_card_degraded: bool
    features_csv: Path
    model_joblib: Path
    evaluation_report_md: Path
    model_card_md: Path
    winner_name: str | None
    primary_metric: str | None
    primary_metric_value: float | None


def _require(path: Path, label: str) -> Path:
    if not path.is_file():
        raise ReplayMissingArtifactError(
            f"replay requires a stored {label} at {path} — run the live crew at least once "
            "first (Internal Gate 8.10: replay reloads guardrail-accepted plans, it never "
            "fabricates one)."
        )
    return path


def replay_crew1(raw_df: "pd.DataFrame", *, run_id: str, workspace: Path) -> ReplayCrew1Result:
    """Deterministically rebuild `clean_data.csv`, `dataset_contract.json`,
    `eda_report.html`, and `insights.md` from stored, re-validated plans —
    zero LLM calls."""
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    figures_dir = workspace / "figures"
    clean_data_csv = workspace / "clean_data.csv"
    dataset_contract_json = workspace / "dataset_contract.json"
    eda_report_html = workspace / "eda_report.html"
    insights_md = workspace / "insights.md"

    cleaning_plan_path = _require(CREW1_INTERNAL / "cleaning_plan.json", "CleaningPlan (_internal/cleaning_plan.json)")
    contract_draft_path = _require(CREW1_INTERNAL / "contract_draft.json", "ContractDraft (_internal/contract_draft.json)")

    raw_profile = profile_dataframe(raw_df, target_column=_TARGET_COLUMN_RAW)
    ok, cleaning_plan = validate_cleaning_plan(cleaning_plan_path.read_text(encoding="utf-8"), profile=raw_profile)
    if not ok:
        return ReplayCrew1Result(
            False, f"stored CleaningPlan failed replay re-validation: {cleaning_plan}", False,
            clean_data_csv, dataset_contract_json, eda_report_html, insights_md,
        )

    clean_df = execute_plan(raw_df, cleaning_plan)
    clean_df.to_csv(clean_data_csv, index=False)

    eda_stats = compute_eda_stats(clean_df, target_column=_TARGET_COLUMN_CLEAN)
    figure_paths = []
    if _TARGET_COLUMN_CLEAN in clean_df.columns:
        clean_profile = profile_dataframe(clean_df, target_column=_TARGET_COLUMN_CLEAN)
        target_rate_columns = [
            col for col in (_resolve_column(clean_df.columns, *slot) for slot in _TARGET_RATE_FIGURE_CANDIDATES)
            if col is not None
        ]
        if not target_rate_columns:
            target_rate_columns = _fallback_target_rate_columns(
                clean_profile, _TARGET_COLUMN_CLEAN, set(), _MAX_TARGET_RATE_FIGURES
            )
        for column in target_rate_columns[:_MAX_TARGET_RATE_FIGURES]:
            figure_paths.append(
                generate_target_rate_figure(clean_df, column=column, target_column=_TARGET_COLUMN_CLEAN, out_dir=figures_dir)
            )
        distribution_column = _resolve_column(clean_df.columns, *_DISTRIBUTION_FIGURE_CANDIDATES)
        if distribution_column is None:
            distribution_column = _fallback_distribution_column(clean_profile, _TARGET_COLUMN_CLEAN)
        if distribution_column is not None:
            figure_paths.append(generate_numeric_distribution_figure(clean_df, column=distribution_column, out_dir=figures_dir))
    figure_relpaths = [f"figures/{p.name}" for p in figure_paths]

    insights_json_path = CREW1_INTERNAL / "insights_doc.json"
    insights_doc = None
    eda_degraded = True
    if insights_json_path.is_file():
        ok, parsed = validate_insights_doc(insights_json_path.read_text(encoding="utf-8"), eda_stats=eda_stats)
        if ok:
            insights_doc = parsed
            eda_degraded = False
        else:
            logger.warning("replay: stored InsightsDoc failed re-validation against freshly measured eda_stats: %s", parsed)
    else:
        logger.warning("replay: no stored insights_doc.json — eda_report.html/insights.md rendered DEGRADED")

    degraded_reason = None if not eda_degraded else "replay: no valid stored InsightsDoc available"
    render_eda_report_html(
        dataset_name=_DATASET_NAME, stats=eda_stats, figures=figure_relpaths,
        insights=insights_doc, out_path=eda_report_html, degraded_reason=degraded_reason,
    )
    render_insights_markdown(
        dataset_name=_DATASET_NAME, insights=insights_doc, out_path=insights_md, degraded_reason=degraded_reason,
    )

    ok, contract_draft = validate_contract_draft(contract_draft_path.read_text(encoding="utf-8"), clean_columns=set(clean_df.columns))
    if not ok:
        return ReplayCrew1Result(
            False, f"stored ContractDraft failed replay re-validation: {contract_draft}", eda_degraded,
            clean_data_csv, dataset_contract_json, eda_report_html, insights_md,
        )

    # "rebuild the contract from actual clean bytes" (Gate 8.10) — sha256/
    # observed stats are re-measured from THIS replay's freshly written
    # clean_data.csv, never copied from the original run's contract.
    contract = build_contract(
        contract_draft, clean_data_csv, contract_version="1.0.0", run_id=run_id, created_by="flow.replay.crew1",
        dataset_name=_DATASET_NAME, source_documentation_url=_SOURCE_DOC_URL,
    )
    dataset_contract_json.write_text(contract.model_dump_json(indent=2), encoding="utf-8")

    return ReplayCrew1Result(True, None, eda_degraded, clean_data_csv, dataset_contract_json, eda_report_html, insights_md)


def replay_crew2(*, clean_data_csv: Path, dataset_contract_json: Path, run_id: str, workspace: Path) -> ReplayCrew2Result:
    """Deterministically rebuild `features.csv`, `model.joblib`,
    `evaluation_report.md`, and `model_card.md` from stored, re-validated
    plans — zero LLM calls."""
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    features_csv = workspace / "features.csv"
    model_joblib = workspace / "model.joblib"
    evaluation_report_md = workspace / "evaluation_report.md"
    model_card_md = workspace / "model_card.md"

    feature_plan_path = _require(CREW2_INTERNAL / "feature_plan.json", "FeaturePlan (_internal/feature_plan.json)")
    experiment_plan_path = _require(CREW2_INTERNAL / "experiment_plan.json", "ExperimentPlan (_internal/experiment_plan.json)")

    contract = DatasetContract.model_validate_json(Path(dataset_contract_json).read_text(encoding="utf-8"))
    clean_df = pd.read_csv(clean_data_csv)

    ok, feature_plan = validate_feature_plan(feature_plan_path.read_text(encoding="utf-8"), contract=contract)
    if not ok:
        return ReplayCrew2Result(
            False, f"stored FeaturePlan failed replay re-validation: {feature_plan}", False,
            features_csv, model_joblib, evaluation_report_md, model_card_md, None, None, None,
        )

    feature_result = build_features(clean_df, contract, feature_plan)
    features_snapshot = feature_result.X.copy()
    features_snapshot[contract.target.name] = feature_result.y
    features_snapshot.to_csv(features_csv, index=False)

    ok, experiment_plan = validate_experiment_plan(experiment_plan_path.read_text(encoding="utf-8"))
    if not ok:
        return ReplayCrew2Result(
            False, f"stored ExperimentPlan failed replay re-validation: {experiment_plan}", False,
            features_csv, model_joblib, evaluation_report_md, model_card_md, None, None, None,
        )

    split = split_train_test(feature_result.X, feature_result.y)
    trained_variants = train_all_variants(feature_result.preprocessor, experiment_plan, split)
    cv_metrics = evaluate_cv_results(trained_variants, split.y_train)
    winner_name = select_winner(cv_metrics, experiment_plan.primary_metric, [v.name for v in experiment_plan.variants])
    winner = next(t for t in trained_variants if t.variant_name == winner_name)
    test_metrics = final_test_evaluation(winner, split.X_test, split.y_test)

    experiments_artifact = build_experiments_artifact(
        run_id=run_id, plan=experiment_plan, trained_variants=trained_variants,
        cv_metrics=cv_metrics, winner_name=winner_name, test_metrics=test_metrics,
    )
    (workspace / "experiments.json").write_text(json.dumps(experiments_artifact, indent=2), encoding="utf-8")
    joblib.dump(winner.fitted_pipeline, model_joblib)
    render_evaluation_report_markdown(run_id=run_id, plan=experiment_plan, experiments=experiments_artifact, out_path=evaluation_report_md)

    model_card_json_path = CREW2_INTERNAL / "model_card.json"
    model_card = None
    model_card_degraded = True
    if model_card_json_path.is_file():
        ok, parsed = validate_model_card(
            model_card_json_path.read_text(encoding="utf-8"), experiments=experiments_artifact, contract=contract
        )
        if ok:
            model_card = parsed
            model_card_degraded = False
        else:
            logger.warning("replay: stored ModelCard failed re-validation against replayed experiments: %s", parsed)
    else:
        logger.warning("replay: no stored model_card.json — model_card.md rendered DEGRADED")

    degraded_reason = None if not model_card_degraded else "replay: no valid stored ModelCard available"
    render_model_card_markdown(
        card=model_card, degraded=model_card_degraded, degraded_reason=degraded_reason,
        experiments=experiments_artifact, contract_assumptions=list(contract.assumptions),
        dataset_name=contract.dataset_name, out_path=model_card_md,
    )

    return ReplayCrew2Result(
        True, None, model_card_degraded, features_csv, model_joblib, evaluation_report_md, model_card_md,
        winner_name, experiment_plan.primary_metric, float(test_metrics[experiment_plan.primary_metric]),
    )
