"""Thin plain-Python helpers around `ml/train.py` / `ml/evaluate.py` for the
Modeling & Experimentation Specialist agent's own artifacts (PROJECT_PLAN.md
§G.2 point 3: `read_feature_plan()`, `get_experiment_results()`).

Both read Crew 2's OWN artifacts — never Crew 1 internals, never the raw
dataset. `read_feature_plan` loads `FeaturePlan` from a JSON file Crew 2's
Feature Engineer already wrote (its own tool output, not something read
through the Crew 1 handoff allowlist); `get_experiment_results` loads the
`experiments.json`-shaped artifact `ml/evaluate.build_experiments_artifact`
already wrote, strictly AFTER training (§G.2 point 3: "אחרי האימון").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harbor_vale.plans.feature_plan import FeaturePlan


def read_feature_plan(path: Path | str) -> FeaturePlan:
    """Load a `FeaturePlan` from a JSON file already written by Crew 2's
    own Feature Engineer step. Raises `pydantic.ValidationError` if the
    file does not parse as a `FeaturePlan` — this is a plain reader, not a
    guardrail (the guardrail, `plans.feature_plan.validate_feature_plan`,
    already ran when the plan was first produced)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return FeaturePlan.model_validate(data)


def get_experiment_results(path: Path | str) -> dict[str, Any]:
    """Load the `experiments.json`-shaped artifact
    `ml.evaluate.build_experiments_artifact` wrote. Raises
    `FileNotFoundError`/`json.JSONDecodeError` for a missing/malformed
    file — callers needing a guardrail-style `(bool, ...)` result should
    catch those explicitly; this function itself always either returns a
    dict or raises."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
