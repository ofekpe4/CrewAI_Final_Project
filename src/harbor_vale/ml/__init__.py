"""Deterministic ML execution (PROJECT_PLAN.md §G.2).

``features`` — sklearn `ColumnTransformer` mechanics behind
`tools/feature_tools.build_features()`. ``train`` — the approved evaluation
protocol (fixed split/CV seeds, `Pipeline`-contained preprocessing).
``evaluate`` — metrics, Python-only winner selection, the machine-readable
`experiments.json`-shaped artifact.

No CrewAI dependency; no Agent/Task/Crew/Flow constructed here. Importing
this package has no side effects.
"""
