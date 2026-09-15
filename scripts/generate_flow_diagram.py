"""Regenerate `docs/flow_diagram.html` (+ its sibling `_style.css`/
`_script.js`) via the real pinned `flow.plot()` API
(PROJECT_PLAN.md §T Phase 8 Internal Gate 8.13).

Makes no LLM call, no dataset access, no Crew kickoff — it only visualizes
`HarborValeFlow`'s registered `@start`/`@listen`/`@router` structure.

Usage:
    python scripts/generate_flow_diagram.py
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale.flow import generate_flow_diagram  # noqa: E402


def main() -> int:
    out_path = generate_flow_diagram()
    print(f"Flow diagram written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
