"""Pytest bootstrap: make the project importable without an install step.

Adds the repo root (for the ``config`` package) and ``src/`` (for the
``harbor_vale`` package) to ``sys.path``. This mirrors the src-layout the Plan
describes (PROJECT_PLAN.md §L) until packaging is configured in a later task.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
for _entry in (_ROOT, _ROOT / "src"):
    _s = str(_entry)
    if _s not in sys.path:
        sys.path.insert(0, _s)
