"""Layer 1 of the Crew 1 → Crew 2 handoff boundary: logical names instead of
paths (PROJECT_PLAN.md §G.0).

**The approved Crew 2 handoff is exactly two files:**
`artifacts/crew1/clean_data.csv` and `artifacts/crew1/dataset_contract.json`.

```python
HandoffName = Literal["clean_data", "dataset_contract"]

@tool
def read_handoff(name: HandoffName) -> str:
    '''The ONLY way Crew 2 can reach Crew 1 output.
    There is no path parameter — a path cannot be expressed.'''
    return HANDOFF.read(name)
```

An agent cannot express "read `data/raw/x.csv`" — there is no place in the
signature for it, and `Literal` blocks every other string. **This module is
that plain-Python function, one phase early**: Phase 5 builds and proves the
deterministic function; Phase 6+ wraps it with CrewAI's `@tool` decorator
(already proven to enforce `Literal` at the tool-argument level — Phase 1
Task 1.5, `docs/architecture.md` §10). No `@tool`/`BaseTool` here.

`read_handoff`'s public signature takes `name` and nothing else — no path,
no directory, no glob. Layer 2 (`access/allowlist.py`'s `ExactFileAllowlist`)
is the defence-in-depth backstop underneath it.
"""

# Deliberate omission: no `from __future__ import annotations`. `HandoffName`
# is a `Literal` that Phase 6+ will bind directly onto a CrewAI `@tool`
# argument (proven mechanism: docs/architecture.md §10, Phase 1 Task 1.5) —
# CrewAI's tool-schema generation needs the REAL `Literal` object at
# introspection time, not a stringized annotation. The same discipline
# `plans/contract_draft.py` documents for guardrail return annotations
# (Sessions 17–18) applies here to an argument annotation instead.

from pathlib import Path
from typing import Literal

from harbor_vale.access.allowlist import ExactFileAllowlist
from harbor_vale.io_paths import HANDOFF_CLEAN_DATA, HANDOFF_CONTRACT

HandoffName = Literal["clean_data", "dataset_contract"]
"""The closed set of logical names Crew 2 may ever request. Exactly two —
the approved handoff, §G.0 — nothing else is a legal value of this type."""

CREW2_ACTOR = "crew2"


def build_crew2_handoff(
    clean_data_path: Path | str,
    dataset_contract_path: Path | str,
    *,
    actor: str = CREW2_ACTOR,
) -> ExactFileAllowlist:
    """Construct the Crew 2 handoff allowlist from two explicit file paths.

    This is how a caller (a test, or eventually the Flow before Crew 2's
    `kickoff`) supplies *which* two files are the approved handoff for a
    given run — the allowlist itself never guesses or globs for them.
    """
    return ExactFileAllowlist(
        {"clean_data": Path(clean_data_path), "dataset_contract": Path(dataset_contract_path)},
        actor=actor,
    )


class Crew2Handoff:
    """Binds a `HandoffName`-only `read_handoff` function to one concrete
    `ExactFileAllowlist` instance — the shape Phase 6+ wraps with `@tool`.

    Deliberately a thin wrapper: all boundary enforcement is
    `ExactFileAllowlist`'s; this class exists only to give
    `read_handoff(name)` the exact two-argument-free signature §G.0
    specifies, bound to a specific run's two files (constructed once, e.g.
    by the Flow, before Crew 2's `kickoff`).
    """

    def __init__(self, allowlist: ExactFileAllowlist) -> None:
        self._allowlist = allowlist

    def read_handoff(self, name: HandoffName) -> str:
        """The ONLY way Crew 2 can reach Crew 1 output. There is no path
        parameter — a path cannot be expressed. See module docstring."""
        return self._allowlist.read(name)


def default_crew2_handoff() -> Crew2Handoff:
    """The production handoff: the two files `io_paths.py` declares as the
    approved Crew 1 → Crew 2 handoff (`HANDOFF_CLEAN_DATA`,
    `HANDOFF_CONTRACT`). Constructed fresh on each call — never cached at
    import time, so importing this module has no filesystem side effects
    and does not require the production artifacts to exist yet (they don't,
    until Phase 6+ runs Crew 1)."""
    return Crew2Handoff(build_crew2_handoff(HANDOFF_CLEAN_DATA, HANDOFF_CONTRACT))
