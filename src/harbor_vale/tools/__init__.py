"""Deterministic tool functions (PROJECT_PLAN.md §T Phase 5).

Plain Python functions with explicit typed signatures — never CrewAI
`@tool`/`BaseTool` wrappers (that wrapping is Phase 6–7 scope, after the
Phase 1 spike decided the orchestration pattern). Every function here is
directly callable and directly testable without any CrewAI dependency.

``profiling_tools`` — deterministic dataset measurement.
``cleaning_tools`` — executes a validated `CleaningPlan`.
``eda_tools`` — deterministic EDA statistics, figures, and report rendering.
``feature_tools`` — builds model-ready features from a validated `FeaturePlan`.
``modeling_tools`` — thin plain-Python helpers around `ml/train.py` / `ml/evaluate.py`.

Importing this package has no side effects.
"""
