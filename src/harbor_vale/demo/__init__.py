"""Deterministic demo/test helpers (PROJECT_PLAN.md §O.3, §P.1).

``fault_injection`` — mutation helpers that build fault-injected *copies* of
a candidate CSV or contract JSON, for `contract/validator.py`'s test suite.
Not wired into any CLI flag or Flow injection point at this phase (that is
Phase 8/10 scope) — these are pure, deterministic functions only.

Importing this package has no side effects.
"""
