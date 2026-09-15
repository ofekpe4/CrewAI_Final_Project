"""The production CrewAI Flow (PROJECT_PLAN.md §H, Phase 8).

`pipeline_flow.HarborValeFlow` orchestrates: load dataset -> Crew 1 -> optional
fault injection -> the deterministic Phase 4 validation gate -> a real
`@router` -> Crew 2 (only on a PASS) -> verification -> `run_summary.json`/
`run_metadata.json`. See `pipeline_flow.py`'s module docstring for the full
graph and the structural PASS/FAIL guarantee.

Importing this package has no side effects — no LLM/API-key access, no
filesystem writes.
"""

from harbor_vale.flow.pipeline_flow import HarborValeFlow, generate_flow_diagram
from harbor_vale.flow.state import PipelineState

__all__ = ["HarborValeFlow", "PipelineState", "generate_flow_diagram"]
