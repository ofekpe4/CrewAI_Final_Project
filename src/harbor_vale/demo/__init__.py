"""Deterministic demo/test helpers (PROJECT_PLAN.md §O.3, §P.1).

``fault_injection`` — mutation helpers that build fault-injected *copies* of
a candidate CSV or contract JSON. `scale_change` (the §O.3 mandatory
scenario) is wired into the real Flow as of Phase 8
(`flow.pipeline_flow.HarborValeFlow.inject_fault_if_requested`) behind the
explicit `--inject-failure` CLI flag only — every other helper here remains
unwired, exercised only by `contract/validator.py`'s own test suite.

Importing this package has no side effects.
"""
