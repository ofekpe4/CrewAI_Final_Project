"""Layer 2 of the Crew 1 → Crew 2 handoff boundary: an exact-file allowlist
(PROJECT_PLAN.md §G.0).

> **Crew 1 may know *how* it produced the data. Crew 2 may know only *what*
> the approved handoff explicitly tells it.**

`ExactFileAllowlist` is deliberately narrow: it allows exact, individually
resolved files — never a directory, a glob, or a prefix. "Anything under
this folder" is exactly the design mistake §G.0 corrects (v1 gave
folder-level access, which was too wide). There is no method on this class
that accepts a directory and no method that matches by string prefix.

This module has no CrewAI dependency and constructs no Agent/Task/Crew — it
is the deterministic filesystem boundary Phase 6+'s `@tool`-wrapped
`read_handoff` (see `access/handoff.py`) sits on top of. See
`docs/architecture.md`/Phase 1 Task 1.5 for the proven companion layer
(CrewAI `Literal` tool-argument enforcement) this defends in depth against —
Layer 1 makes an out-of-allowlist request *inexpressible* to an agent at
all; Layer 2 makes it *impossible* even if Layer 1 were somehow bypassed.
"""

from __future__ import annotations

from pathlib import Path

from harbor_vale.logging_setup import get_logger

logger = get_logger(__name__)


class HandoffAccessDenied(Exception):
    """Raised for any access attempt outside an `ExactFileAllowlist`'s exact
    set of allowed files — an unknown logical name, a path that resolves
    outside the allowed set (including via `../` traversal or a symlink
    pointing elsewhere), or a directory where a file was expected.
    """


class ExactFileAllowlist:
    """Exact resolved file paths. No directories. No globs. No prefixes.

    Every allowed file is resolved once, at construction time
    (`Path.resolve(strict=True)` — the file must actually exist), so a
    symlink pointing outside the intended location is caught immediately
    rather than silently allowed later. Membership is then checked against
    that frozen, exact set of resolved paths — never a string prefix
    comparison, which a `../` sequence or a symlink could defeat.
    """

    def __init__(self, files: dict[str, Path], actor: str) -> None:
        """
        Args:
            files: logical name -> path, e.g.
                `{"clean_data": HANDOFF_CLEAN_DATA, "dataset_contract": HANDOFF_CONTRACT}`.
                Every path must exist on disk (`resolve(strict=True)`) —
                constructing an allowlist for a file that doesn't exist yet
                is a configuration error, not something to defer.
            actor: a short label for log messages (e.g. `"crew2"`) — never
                secret, never used for anything but attribution in logs.
        """
        self._by_name: dict[str, Path] = {
            name: path.resolve(strict=True) for name, path in files.items()
        }
        self._allowed: frozenset[Path] = frozenset(self._by_name.values())
        self.actor = actor

    def read(self, name: str) -> str:
        """The primary access path: read by logical name.

        Raises `HandoffAccessDenied` for any name not in this allowlist's
        exact set — including a syntactically plausible name that simply
        wasn't configured. Never returns content for a denied request.
        """
        if name not in self._by_name:
            logger.error(
                "HANDOFF VIOLATION: actor=%s requested unknown logical name %r "
                "(allowed: %s)",
                self.actor, name, sorted(self._by_name),
            )
            raise HandoffAccessDenied(
                f"{self.actor} may only read: {sorted(self._by_name)}. "
                "Crew 2 works exclusively through the approved handoff."
            )
        return self._by_name[name].read_text(encoding="utf-8")

    def read_path(self, path: Path | str) -> str:
        """Backstop for internal/trusted code only — never exposed to an
        agent's tool surface (that surface is `read_handoff`, logical-name
        only; see `access/handoff.py`).

        `Path(path).resolve()` neutralises `../` traversal and follows
        symlinks to their real target — so a symlink crafted to point
        outside the allowed set still resolves to a path that is not a
        member of `self._allowed`, and is denied on that basis, not on a
        string comparison of the symlink's own literal text.
        """
        resolved = Path(path).resolve()
        if resolved not in self._allowed:
            logger.error(
                "HANDOFF VIOLATION: actor=%s attempted to read %s (resolved: %s)",
                self.actor, path, resolved,
            )
            raise HandoffAccessDenied(
                f"{self.actor} may only read the approved handoff files; "
                f"{resolved} is not one of them."
            )
        if resolved.is_dir():
            raise HandoffAccessDenied(f"{resolved} is a directory, not an allowed file.")
        return resolved.read_text(encoding="utf-8")

    @property
    def allowed_names(self) -> frozenset[str]:
        return frozenset(self._by_name)
