"""Crew 2's `Task.callback` functions (PROJECT_PLAN.md §G.1/§G.2/§G.3 point 8,
Phase 7 Internal Gates 7.3-7.5).

**Every function here is a plain, module-level, synchronous function** —
required by `Task.callback`'s `SerializableCallable` typing, same reasoning
as `crews.analyst_crew.callbacks`. Each calls `runtime.get_active_context()`
first, then performs ONLY deterministic Python work — no LLM call, no
judgement. By the time any of these runs, its Task's guardrail has already
returned success (or, for Task 3 only, a forced-accept degraded state) —
same ordering guarantee `crews.analyst_crew.callbacks` documents in full.

**"Agent plans, Python executes" — the whole point of this module.** No
function here lets an agent write `features.csv`, train a model, pick a
winner, or write `model.joblib`/`experiments.json`/`evaluation_report.md`
directly; every one of those artifacts is produced by calling the already-
tested Phase 5 deterministic layer (`tools/feature_tools.py`, `ml/train.py`,
`ml/evaluate.py`, `tools/report_tools.py`) with the guardrail-validated plan
as input.
"""

import json

import joblib
import pandas as pd

from harbor_vale.crews.scientist_crew.runtime import get_active_context
from harbor_vale.crews.scientist_crew.tools import ensure_clean_df_loaded, ensure_contract_loaded
from harbor_vale.ml.evaluate import (
    build_experiments_artifact,
    evaluate_cv_results,
    final_test_evaluation,
    select_winner,
)
from harbor_vale.ml.train import split_train_test, train_all_variants
from harbor_vale.tools.feature_tools import build_features
from harbor_vale.tools.report_tools import render_evaluation_report_markdown, render_model_card_markdown


def persist_feature_plan_and_build_features(task_output) -> None:  # noqa: ARG001
    """Task 1 (Feature Engineer) callback — CRITICAL (§G.1 point 8).

    1. Persists the accepted `FeaturePlan` under `_internal/` (debug trail
       + Crew 2's own `read_feature_plan()` tool source).
    2. Executes it via the already-tested `tools/feature_tools.build_features`
       -> an UNFITTED `ColumnTransformer` + raw `X`/`y` (leakage-safe design
       preserved: nothing here fits a preprocessor on the full dataset).
    3. Writes `features.csv` — the raw (pre-`ColumnTransformer`) feature
       matrix plus the target column, for inspection; the actual fitted
       preprocessing happens only inside `ml/train.py`'s `Pipeline`, only on
       training/fold data (Task 2's callback).
    """
    ctx = get_active_context()
    if ctx.feature_plan is None:  # pragma: no cover — guarded by guardrail-then-callback ordering
        raise RuntimeError(
            "persist_feature_plan_and_build_features: ctx.feature_plan is None — guardrail did not run first"
        )

    ctx.internal_dir.mkdir(parents=True, exist_ok=True)
    (ctx.internal_dir / "feature_plan.json").write_text(
        ctx.feature_plan.model_dump_json(indent=2), encoding="utf-8"
    )

    contract = ensure_contract_loaded(ctx)
    clean_df = ensure_clean_df_loaded(ctx)

    result = build_features(clean_df, contract, ctx.feature_plan)
    ctx.feature_X = result.X
    ctx.feature_y = result.y
    ctx.feature_preprocessor = result.preprocessor
    ctx.feature_names = result.feature_names

    ctx.features_csv.parent.mkdir(parents=True, exist_ok=True)
    features_with_target: "pd.DataFrame" = pd.concat([result.X, result.y], axis=1)
    features_with_target.to_csv(ctx.features_csv, index=False)


def train_and_evaluate(task_output) -> None:  # noqa: ARG001
    """Task 2 (Modeling & Experimentation Specialist) callback — CRITICAL
    (§G.2 point 8).

    The agent's validated `ExperimentPlan` is EXECUTED here, entirely by
    Python: the exact split/CV protocol (`ml/train.py`), evaluation and
    Python-only winner selection (`ml/evaluate.py`), `experiments.json`,
    `model.joblib`, and the deterministic `evaluation_report.md` render
    (`tools/report_tools.py`) — the agent never trains, never sees the test
    set, and never chooses the winner.
    """
    ctx = get_active_context()
    if ctx.experiment_plan is None:  # pragma: no cover — guarded by guardrail-then-callback ordering
        raise RuntimeError("train_and_evaluate: ctx.experiment_plan is None — guardrail did not run first")
    if ctx.feature_X is None or ctx.feature_y is None or ctx.feature_preprocessor is None:
        raise RuntimeError("train_and_evaluate: features not built — Task 1's callback did not run first")

    plan = ctx.experiment_plan
    split = split_train_test(ctx.feature_X, ctx.feature_y)
    trained_variants = train_all_variants(ctx.feature_preprocessor, plan, split)
    cv_metrics = evaluate_cv_results(trained_variants, split.y_train)
    winner_name = select_winner(cv_metrics, plan.primary_metric, [v.name for v in plan.variants])
    winner = next(t for t in trained_variants if t.variant_name == winner_name)
    test_metrics = final_test_evaluation(winner, split.X_test, split.y_test)

    experiments_artifact = build_experiments_artifact(
        run_id=ctx.run_id,
        plan=plan,
        trained_variants=trained_variants,
        cv_metrics=cv_metrics,
        winner_name=winner_name,
        test_metrics=test_metrics,
    )

    ctx.trained_variants = trained_variants
    ctx.cv_metrics = cv_metrics
    ctx.winner_name = winner_name
    ctx.test_metrics = test_metrics
    ctx.experiments_artifact = experiments_artifact

    ctx.experiments_json.parent.mkdir(parents=True, exist_ok=True)
    ctx.experiments_json.write_text(json.dumps(experiments_artifact, indent=2), encoding="utf-8")

    ctx.model_joblib.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(winner.fitted_pipeline, ctx.model_joblib)

    render_evaluation_report_markdown(
        run_id=ctx.run_id, plan=plan, experiments=experiments_artifact, out_path=ctx.evaluation_report_md
    )


def render_model_card(task_output) -> None:  # noqa: ARG001
    """Task 3 (Responsible AI Documenter) callback — NARRATIVE, visible
    fallback (§G.3 point 8/9). Renders from `ctx`, never from `task_output`
    — see `guardrails.guardrail_model_card`'s docstring for why."""
    ctx = get_active_context()
    if ctx.experiments_artifact is None:  # pragma: no cover — guarded by Task ordering
        raise RuntimeError("render_model_card: ctx.experiments_artifact is None — Task 2's callback did not run first")

    contract = ensure_contract_loaded(ctx)
    degraded_reason = ctx.model_card_degraded_reason if ctx.model_card_degraded else None
    card = None if ctx.model_card_degraded else ctx.model_card

    render_model_card_markdown(
        card=card,
        degraded=ctx.model_card_degraded,
        degraded_reason=degraded_reason,
        experiments=ctx.experiments_artifact,
        contract_assumptions=list(contract.assumptions),
        dataset_name=contract.dataset_name,
        out_path=ctx.model_card_md,
    )
