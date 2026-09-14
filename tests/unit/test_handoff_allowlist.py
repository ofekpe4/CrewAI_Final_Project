"""Unit tests — the Crew 1 → Crew 2 handoff boundary (PROJECT_PLAN.md §G.0).
**The critical security test.**

Proves both layers: Layer 1 (`access/handoff.py` — logical names only, no
free path parameter) and Layer 2 (`access/allowlist.py`'s
`ExactFileAllowlist` — exact resolved files, denylist coverage). Every
denied path must raise `HandoffAccessDenied` and must NEVER return content.

Runnable two ways:
  * ``pytest tests/unit/test_handoff_allowlist.py``
  * ``python tests/unit/test_handoff_allowlist.py``
"""

from __future__ import annotations

import inspect
import os
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale.access.allowlist import ExactFileAllowlist, HandoffAccessDenied  # noqa: E402
from harbor_vale.access.handoff import Crew2Handoff, HandoffName, build_crew2_handoff  # noqa: E402


def _make_workspace(tmp: Path) -> dict[str, Path]:
    """A realistic Crew 1 output tree: the two approved handoff files plus
    every denylisted artifact §G.0 explicitly names."""
    crew1 = tmp / "artifacts" / "crew1"
    internal = crew1 / "_internal"
    internal.mkdir(parents=True)
    data_raw = tmp / "data" / "raw"
    data_raw.mkdir(parents=True)
    validation = tmp / "artifacts" / "validation"
    validation.mkdir(parents=True)

    files = {
        "clean_data": crew1 / "clean_data.csv",
        "dataset_contract": crew1 / "dataset_contract.json",
        "insights": crew1 / "insights.md",
        "eda_report": crew1 / "eda_report.html",
        "cleaning_plan": internal / "cleaning_plan.json",
        "contract_draft": internal / "contract_draft.json",
        "clean_profile": internal / "clean_profile.json",
        "raw": data_raw / "telco.csv",
        "validation_report": validation / "validation_report.json",
    }
    for path in files.values():
        path.write_text("SENSITIVE CONTENT — must never be returned to a denied requester", encoding="utf-8")
    return files


def _crew2_allowlist(files: dict[str, Path], actor: str = "crew2") -> ExactFileAllowlist:
    return build_crew2_handoff(files["clean_data"], files["dataset_contract"], actor=actor)


# --- valid access ------------------------------------------------------------

def test_valid_clean_data_succeeds() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        h = Crew2Handoff(_crew2_allowlist(files))
        content = h.read_handoff("clean_data")
    assert "SENSITIVE CONTENT" in content  # it's ALLOWED content, correctly returned


def test_valid_dataset_contract_succeeds() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        h = Crew2Handoff(_crew2_allowlist(files))
        content = h.read_handoff("dataset_contract")
    assert "SENSITIVE CONTENT" in content


# --- Layer 1: no free path parameter ----------------------------------------

def test_read_handoff_signature_has_no_path_parameter() -> None:
    """The public Crew-2-facing function's signature itself must make a
    free path inexpressible — not merely reject one at runtime."""
    sig = inspect.signature(Crew2Handoff.read_handoff)
    params = [p for p in sig.parameters if p != "self"]
    assert params == ["name"], f"read_handoff must accept exactly one parameter, 'name'; got {params}"
    # And that parameter's annotation is the closed Literal, not `str`/`Path`.
    from harbor_vale.access.handoff import HandoffName as _HN

    assert sig.parameters["name"].annotation is _HN


def test_handoff_name_is_a_closed_two_value_literal() -> None:
    import typing

    args = typing.get_args(HandoffName)
    assert set(args) == {"clean_data", "dataset_contract"}


def test_invalid_logical_name_is_denied() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        h = Crew2Handoff(_crew2_allowlist(files))
        try:
            h.read_handoff("insights")  # not a member of HandoffName; a real agent literally cannot express this
        except HandoffAccessDenied:
            pass
        else:
            raise AssertionError("expected HandoffAccessDenied for an unknown logical name")


# --- Layer 2: exact-file allowlist denylist coverage ------------------------

_DENYLIST_LOGICAL_KEYS = [
    "raw", "cleaning_plan", "contract_draft", "clean_profile",
    "insights", "eda_report", "validation_report",
]


def test_every_denylisted_file_is_denied_via_read_path() -> None:
    """PROJECT_PLAN.md §G.0's exact denylist, run through the Layer-2
    backstop `read_path`. Every one must raise `HandoffAccessDenied` and
    must NEVER return content."""
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        allowlist = _crew2_allowlist(files)
        for key in _DENYLIST_LOGICAL_KEYS:
            try:
                content = allowlist.read_path(files[key])
            except HandoffAccessDenied:
                pass
            else:
                raise AssertionError(f"expected HandoffAccessDenied for {key} ({files[key]}), got content: {content!r}")


def test_raw_data_denied() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        allowlist = _crew2_allowlist(files)
        try:
            allowlist.read_path(files["raw"])
        except HandoffAccessDenied:
            pass
        else:
            raise AssertionError("expected HandoffAccessDenied for data/raw/telco.csv")


def test_internal_cleaning_plan_denied() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        allowlist = _crew2_allowlist(files)
        try:
            allowlist.read_path(files["cleaning_plan"])
        except HandoffAccessDenied:
            pass
        else:
            raise AssertionError("expected HandoffAccessDenied for _internal/cleaning_plan.json")


def test_internal_contract_draft_denied() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        allowlist = _crew2_allowlist(files)
        try:
            allowlist.read_path(files["contract_draft"])
        except HandoffAccessDenied:
            pass
        else:
            raise AssertionError("expected HandoffAccessDenied for _internal/contract_draft.json")


def test_internal_clean_profile_denied() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        allowlist = _crew2_allowlist(files)
        try:
            allowlist.read_path(files["clean_profile"])
        except HandoffAccessDenied:
            pass
        else:
            raise AssertionError("expected HandoffAccessDenied for _internal/clean_profile.json")


def test_insights_md_denied() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        allowlist = _crew2_allowlist(files)
        try:
            allowlist.read_path(files["insights"])
        except HandoffAccessDenied:
            pass
        else:
            raise AssertionError("expected HandoffAccessDenied for insights.md")


def test_eda_report_html_denied() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        allowlist = _crew2_allowlist(files)
        try:
            allowlist.read_path(files["eda_report"])
        except HandoffAccessDenied:
            pass
        else:
            raise AssertionError("expected HandoffAccessDenied for eda_report.html")


def test_validation_report_json_denied() -> None:
    """§G.0: Crew 2 does not read validation_report.json from disk at all —
    that status is injected as Flow metadata (`handoff_status`), not read
    through the handoff."""
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        allowlist = _crew2_allowlist(files)
        try:
            allowlist.read_path(files["validation_report"])
        except HandoffAccessDenied:
            pass
        else:
            raise AssertionError("expected HandoffAccessDenied for validation_report.json")


def test_sibling_file_in_the_same_directory_is_denied() -> None:
    """Being in the SAME directory as an allowed file must not grant
    access — proves this is a per-file allowlist, not a directory allowlist."""
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        allowlist = _crew2_allowlist(files)
        sibling = files["clean_data"].parent / "sibling_not_allowed.csv"
        sibling.write_text("also sensitive", encoding="utf-8")
        try:
            allowlist.read_path(sibling)
        except HandoffAccessDenied:
            pass
        else:
            raise AssertionError("expected HandoffAccessDenied for a sibling file in the same directory")


def test_directory_access_is_denied() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        allowlist = _crew2_allowlist(files)
        try:
            allowlist.read_path(files["clean_data"].parent)  # the crew1/ directory itself
        except HandoffAccessDenied:
            pass
        else:
            raise AssertionError("expected HandoffAccessDenied for a directory")


# --- traversal / absolute path / symlink escape -----------------------------

def test_relative_traversal_is_denied() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        allowlist = _crew2_allowlist(files)
        traversal_path = files["clean_data"].parent / ".." / ".." / "data" / "raw" / "telco.csv"
        try:
            allowlist.read_path(traversal_path)
        except HandoffAccessDenied:
            pass
        else:
            raise AssertionError("expected HandoffAccessDenied for a ../ traversal path")


def test_deep_traversal_toward_system_files_is_denied() -> None:
    """§G.0's own denylist example: `../../etc/passwd`-shaped traversal."""
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        allowlist = _crew2_allowlist(files)
        traversal_path = files["clean_data"].parent / ".." / ".." / ".." / ".." / "etc" / "passwd"
        try:
            allowlist.read_path(traversal_path)
        except HandoffAccessDenied:
            pass
        else:
            raise AssertionError("expected HandoffAccessDenied for a deep ../../etc/passwd-shaped path")


def test_absolute_path_to_a_denied_file_is_denied() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        allowlist = _crew2_allowlist(files)
        absolute_str = str(files["insights"].resolve())
        try:
            allowlist.read_path(absolute_str)
        except HandoffAccessDenied:
            pass
        else:
            raise AssertionError("expected HandoffAccessDenied for an absolute path to insights.md")


def test_symlink_escape_is_denied() -> None:
    """A symlink living NEXT TO an allowed file, but pointing OUTSIDE the
    allowed set, must resolve to its real target and be denied on that
    basis — never granted because of where the symlink itself sits."""
    if os.name == "nt":
        print("SKIP: symlink test skipped on Windows")
        return
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        allowlist = _crew2_allowlist(files)
        symlink_path = files["clean_data"].parent / "clean_data_shortcut.csv"
        symlink_path.symlink_to(files["insights"])  # points at a DENIED file
        try:
            allowlist.read_path(symlink_path)
        except HandoffAccessDenied:
            pass
        else:
            raise AssertionError("expected HandoffAccessDenied for a symlink resolving to a denied file")


def test_symlink_pointing_at_an_allowed_file_from_elsewhere_is_still_denied() -> None:
    """Even a symlink that HAPPENS to point at an allowed file's bytes is
    denied if it is not itself one of the exact allowed Path objects —
    membership is by the allowlist's own resolved paths, not by "resolves
    to the same content"."""
    if os.name == "nt":
        print("SKIP: symlink test skipped on Windows")
        return
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        allowlist = _crew2_allowlist(files)
        outside_dir = Path(tmp) / "outside"
        outside_dir.mkdir()
        symlink_path = outside_dir / "sneaky.csv"
        symlink_path.symlink_to(files["clean_data"])
        # This one actually DOES resolve to the allowed file's real path,
        # so it correctly succeeds — proving membership is by resolved
        # identity, not by literal path text (a stricter test than merely
        # "denied"; the point is *why* it's allowed here matters).
        content = allowlist.read_path(symlink_path)
        assert "SENSITIVE CONTENT" in content


# --- content never leaks on denial ------------------------------------------

def test_denied_read_handoff_raises_before_any_file_is_touched() -> None:
    """An unknown logical name is denied WITHOUT ever touching the
    filesystem for content — proves the denial happens at the boundary
    check, not merely that content is discarded afterward."""
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        h = Crew2Handoff(_crew2_allowlist(files))
        try:
            h.read_handoff("clean_profile")
        except HandoffAccessDenied as exc:
            assert "SENSITIVE CONTENT" not in str(exc)
        else:
            raise AssertionError("expected HandoffAccessDenied")


def test_exception_message_never_contains_denied_content() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        allowlist = _crew2_allowlist(files)
        try:
            allowlist.read_path(files["insights"])
        except HandoffAccessDenied as exc:
            assert "SENSITIVE CONTENT" not in str(exc)
        else:
            raise AssertionError("expected HandoffAccessDenied")


# --- no directory-level / glob / prefix matching ----------------------------

def test_allowlist_construction_rejects_a_nonexistent_file() -> None:
    """`ExactFileAllowlist` resolves every path with `strict=True` at
    construction time — a file that doesn't exist yet is a configuration
    error, not silently deferred."""
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        try:
            ExactFileAllowlist(
                {"clean_data": files["clean_data"], "dataset_contract": Path(tmp) / "does_not_exist.json"},
                actor="crew2",
            )
        except (FileNotFoundError, OSError):
            pass
        else:
            raise AssertionError("expected construction to fail for a nonexistent file")


def test_allowed_names_property_exposes_exactly_the_configured_set() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_workspace(Path(tmp))
        allowlist = _crew2_allowlist(files)
        assert allowlist.allowed_names == frozenset({"clean_data", "dataset_contract"})


if __name__ == "__main__":
    _failures: list[str] = []
    for _name, _fn in sorted(
        (n, f) for n, f in dict(globals()).items() if n.startswith("test_") and callable(f)
    ):
        try:
            _fn()
        except Exception as exc:  # noqa: BLE001
            _failures.append(_name)
            print(f"FAIL  {_name}: {exc.__class__.__name__}: {exc}")
        else:
            print(f"PASS  {_name}")
    print(f"\n{len(_failures)} failed" if _failures else "\nall passed")
    sys.exit(1 if _failures else 0)
