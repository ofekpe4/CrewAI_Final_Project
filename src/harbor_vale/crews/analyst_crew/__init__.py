"""Crew 1 — the Data Analyst Crew (PROJECT_PLAN.md §D, Phase 6).

Three real CrewAI agents (Data Quality Inspector, EDA & Insights Analyst,
Data Contract Architect) wired as one `Crew` (`Process.sequential`, Pattern
A — `docs/architecture.md`). See `analyst_crew.run_analyst_crew` for the one
production entry point.

Importing this package has no side effects (no LLM/API-key access at
import time — only at `run_analyst_crew` call time).
"""

from harbor_vale.crews.analyst_crew.analyst_crew import (
    Crew1Result,
    build_analyst_crew,
    run_analyst_crew,
)
from harbor_vale.crews.analyst_crew.runtime import Crew1RunContext

__all__ = ["Crew1Result", "Crew1RunContext", "build_analyst_crew", "run_analyst_crew"]
