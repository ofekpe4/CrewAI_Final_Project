"""Shared Streamlit-app support code (PROJECT_PLAN.md §Q.5, Phase 9).

Everything in `app/lib/` is presentation plumbing only: it reads already
-written pipeline artifacts and renders them, or maps a UI control onto the
existing `scripts/run_pipeline.py` CLI. It never re-implements validation,
contract checking, feature engineering, model training, winner selection,
or fault injection — those stay the exclusive responsibility of
`src/harbor_vale/*`, which this package only reads from.
"""
