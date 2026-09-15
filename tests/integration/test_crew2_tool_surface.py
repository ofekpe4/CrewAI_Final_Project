"""Integration tests — the Crew 2 tool surface end to end (PROJECT_PLAN.md
§G.0, Phase 7 Internal Gate 7.1). **The critical security test for Phase 7.**

Builds a real, on-disk two-file handoff (`clean_data.csv` +
`dataset_contract.json`) plus every denylisted sibling artifact §G.0 names,
then proves — through the ACTUAL `@tool`-wrapped `read_handoff` /
`profile_handoff_data` / `read_feature_plan` / `read_experiment_results`
functions Crew 2's agents are wired with, inside a real `Crew2RunContext` —
that only the two approved logical names ever return content, and every
denylisted path raises `HandoffAccessDenied`, mechanically, never by
prompt instruction alone.

Runnable two ways:
  * ``pytest tests/integration/test_crew2_tool_surface.py``
  * ``python tests/integration/test_crew2_tool_surface.py``
"""

from __future__ import annotations

import inspect
import sys
import tempfile
import typing
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale.access.allowlist import HandoffAccessDenied  # noqa: E402
from harbor_vale.access.handoff import Crew2Handoff, HandoffName, build_crew2_handoff  # noqa: E402
from harbor_vale.crews.scientist_crew.runtime import Crew2RunContext, crew2_run_context  # noqa: E402
from harbor_vale.crews.scientist_crew.tools import (  # noqa: E402
    profile_handoff_data,
    read_experiment_results,
    read_feature_plan,
    read_handoff,
)

_PASS: list[str] = []
_FAIL: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        _PASS.append(name)
        print(f"PASS  {name}")
    else:
        _FAIL.append(name)
        print(f"FAIL  {name}  {detail}")


_MINIMAL_CONTRACT_JSON = """{
  "contract_version": "1.0.0", "created_at": "2026-01-01T00:00:00Z",
  "created_by": "test", "run_id": "r1", "dataset_name": "x",
  "source_documentation_url": "https://x",
  "target": {"name": "churn", "task_type": "binary_classification",
    "constraints": {}, "observed": {"positive_rate": 0.3, "class_counts": {"0": 7, "1": 3}}},
  "required_features": [], "excluded_features": [],
  "primary_key": {"columns": ["id"], "constraints": {"unique": {"value": true, "justification": "j"}}},
  "columns": [{"name": "id", "semantic_type": "identifier",
    "observed": {"dtype": "object", "null_count": 0, "unique_count": 10}, "constraints": {}}],
  "integrity": {"clean_data_sha256": "%s", "row_count": 10, "column_count": 2, "column_order": ["id", "churn"]},
  "assumptions": ["one row per id"],
  "validation_policy": {}
}"""


def _make_handoff_workspace(tmp: Path) -> dict[str, Path]:
    """A realistic Crew 1 output tree, plus every §G.0 denylist target."""
    crew1 = tmp / "artifacts" / "crew1"
    internal = crew1 / "_internal"
    internal.mkdir(parents=True)
    data_raw = tmp / "data" / "raw"
    data_raw.mkdir(parents=True)
    validation = tmp / "artifacts" / "validation"
    validation.mkdir(parents=True)

    import hashlib

    clean_data_csv = crew1 / "clean_data.csv"
    clean_data_csv.write_text("id,churn\n1,0\n2,1\n3,0\n4,0\n5,1\n6,0\n7,0\n8,1\n9,0\n10,0\n", encoding="utf-8")
    sha = hashlib.sha256(clean_data_csv.read_bytes()).hexdigest()

    files = {
        "clean_data": clean_data_csv,
        "dataset_contract": crew1 / "dataset_contract.json",
        "insights": crew1 / "insights.md",
        "eda_report": crew1 / "eda_report.html",
        "cleaning_plan": internal / "cleaning_plan.json",
        "contract_draft": internal / "contract_draft.json",
        "clean_profile": internal / "clean_profile.json",
        "raw": data_raw / "telco.csv",
        "validation_report": validation / "validation_report.json",
    }
    files["dataset_contract"].write_text(_MINIMAL_CONTRACT_JSON % sha, encoding="utf-8")
    for key, path in files.items():
        if key in ("clean_data", "dataset_contract"):
            continue
        path.write_text("SENSITIVE CONTENT — must never be returned to Crew 2", encoding="utf-8")
    return files


def _crew2_context(files: dict[str, Path], internal_dir: Path) -> Crew2RunContext:
    handoff = Crew2Handoff(build_crew2_handoff(files["clean_data"], files["dataset_contract"], actor="crew2"))
    return Crew2RunContext(
        run_id="integration-test", handoff=handoff, handoff_status="gate_passed",
        contract_version="1.0.0", validation_warnings=0,
        features_csv=internal_dir / "features.csv", model_joblib=internal_dir / "model.joblib",
        experiments_json=internal_dir / "experiments.json", evaluation_report_md=internal_dir / "evaluation_report.md",
        model_card_md=internal_dir / "model_card.md", internal_dir=internal_dir,
    )


# --- Layer 1: signature-level proof -----------------------------------------


def test_no_crew2_tool_accepts_a_free_path_parameter() -> None:
    for tool_fn, expected_params in (
        (read_handoff, ["name"]),
        (profile_handoff_data, []),
        (read_feature_plan, []),
        (read_experiment_results, []),
    ):
        sig = inspect.signature(tool_fn.func)
        params = list(sig.parameters)
        check(
            f"test_no_crew2_tool_accepts_a_free_path_parameter: {tool_fn.name} params == {expected_params}",
            params == expected_params, f"got {params}",
        )
    sig = inspect.signature(read_handoff.func)
    check(
        "test_no_crew2_tool_accepts_a_free_path_parameter: read_handoff.name is HandoffName-shaped (2-value Literal)",
        set(typing.get_args(sig.parameters["name"].annotation)) == {"clean_data", "dataset_contract"},
    )
    check(
        "test_no_crew2_tool_accepts_a_free_path_parameter: HandoffName itself is exactly 2 values",
        set(typing.get_args(HandoffName)) == {"clean_data", "dataset_contract"},
    )


# --- allowed access, through the REAL tool layer ----------------------------


def test_read_handoff_tool_clean_data_allowed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_handoff_workspace(Path(tmp))
        ctx = _crew2_context(files, Path(tmp) / "crew2_internal")
        with crew2_run_context(ctx):
            content = read_handoff.run(name="clean_data")
        check("test_read_handoff_tool_clean_data_allowed: real content returned", "id,churn" in content)


def test_read_handoff_tool_dataset_contract_allowed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_handoff_workspace(Path(tmp))
        ctx = _crew2_context(files, Path(tmp) / "crew2_internal")
        with crew2_run_context(ctx):
            content = read_handoff.run(name="dataset_contract")
        check("test_read_handoff_tool_dataset_contract_allowed: real content returned", '"contract_version"' in content)


def test_profile_handoff_data_tool_works_through_the_boundary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_handoff_workspace(Path(tmp))
        ctx = _crew2_context(files, Path(tmp) / "crew2_internal")
        with crew2_run_context(ctx):
            profile = profile_handoff_data.run()
        check("test_profile_handoff_data_tool_works_through_the_boundary: returns a real measured profile", "columns" in profile)


# --- denied access, through the REAL tool layer -----------------------------


def test_read_handoff_tool_rejects_unknown_logical_name() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_handoff_workspace(Path(tmp))
        ctx = _crew2_context(files, Path(tmp) / "crew2_internal")
        with crew2_run_context(ctx):
            try:
                read_handoff.run(name="insights")
            except Exception as exc:  # noqa: BLE001 — CrewAI's own tool-arg schema rejects before the body
                check("test_read_handoff_tool_rejects_unknown_logical_name: rejected before the body runs", True, str(exc)[:200])
            else:
                check("test_read_handoff_tool_rejects_unknown_logical_name: rejected before the body runs", False)


_DENYLIST_KEYS = ["raw", "cleaning_plan", "contract_draft", "clean_profile", "insights", "eda_report", "validation_report"]


def test_allowlist_denies_every_denylisted_file_for_crew2() -> None:
    """Proves `HandoffAccessDenied` for raw / `_internal` / insights / eda /
    validation-report — through the SAME `ExactFileAllowlist` Crew 2's own
    `Crew2Handoff` (and therefore every Crew 2 tool) is built on."""
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_handoff_workspace(Path(tmp))
        allowlist = build_crew2_handoff(files["clean_data"], files["dataset_contract"], actor="crew2")
        for key in _DENYLIST_KEYS:
            try:
                content = allowlist.read_path(files[key])
            except HandoffAccessDenied:
                check(f"test_allowlist_denies_every_denylisted_file_for_crew2: {key} denied", True)
            else:
                check(f"test_allowlist_denies_every_denylisted_file_for_crew2: {key} denied", False, f"got content: {content!r}")


def test_traversal_and_absolute_path_denied_for_crew2() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_handoff_workspace(Path(tmp))
        allowlist = build_crew2_handoff(files["clean_data"], files["dataset_contract"], actor="crew2")

        traversal = files["clean_data"].parent / ".." / ".." / "data" / "raw" / "telco.csv"
        try:
            allowlist.read_path(traversal)
        except HandoffAccessDenied:
            check("test_traversal_and_absolute_path_denied_for_crew2: ../ traversal denied", True)
        else:
            check("test_traversal_and_absolute_path_denied_for_crew2: ../ traversal denied", False)

        absolute_str = str(files["insights"].resolve())
        try:
            allowlist.read_path(absolute_str)
        except HandoffAccessDenied:
            check("test_traversal_and_absolute_path_denied_for_crew2: absolute path to insights.md denied", True)
        else:
            check("test_traversal_and_absolute_path_denied_for_crew2: absolute path to insights.md denied", False)


def test_symlink_escape_denied_for_crew2() -> None:
    import os

    if os.name == "nt":
        print("SKIP: symlink test skipped on Windows")
        return
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_handoff_workspace(Path(tmp))
        allowlist = build_crew2_handoff(files["clean_data"], files["dataset_contract"], actor="crew2")
        symlink_path = files["clean_data"].parent / "clean_data_shortcut.csv"
        symlink_path.symlink_to(files["insights"])
        try:
            allowlist.read_path(symlink_path)
        except HandoffAccessDenied:
            check("test_symlink_escape_denied_for_crew2: symlink resolving to a denied file denied", True)
        else:
            check("test_symlink_escape_denied_for_crew2: symlink resolving to a denied file denied", False)


def test_own_crew2_artifact_tools_fail_clearly_before_written() -> None:
    """`read_feature_plan`/`read_experiment_results` read Crew 2's OWN
    artifacts — calling them before Task 1/2's callback ran must fail
    loudly (a wiring error), never silently return stale/fabricated data."""
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_handoff_workspace(Path(tmp))
        ctx = _crew2_context(files, Path(tmp) / "crew2_internal")
        with crew2_run_context(ctx):
            try:
                read_feature_plan.run()
            except RuntimeError:
                check("test_own_crew2_artifact_tools_fail_clearly_before_written: read_feature_plan raises before Task 1", True)
            else:
                check("test_own_crew2_artifact_tools_fail_clearly_before_written: read_feature_plan raises before Task 1", False)
            try:
                read_experiment_results.run()
            except RuntimeError:
                check("test_own_crew2_artifact_tools_fail_clearly_before_written: read_experiment_results raises before Task 2", True)
            else:
                check("test_own_crew2_artifact_tools_fail_clearly_before_written: read_experiment_results raises before Task 2", False)


ALL_TESTS = [
    test_no_crew2_tool_accepts_a_free_path_parameter,
    test_read_handoff_tool_clean_data_allowed,
    test_read_handoff_tool_dataset_contract_allowed,
    test_profile_handoff_data_tool_works_through_the_boundary,
    test_read_handoff_tool_rejects_unknown_logical_name,
    test_allowlist_denies_every_denylisted_file_for_crew2,
    test_traversal_and_absolute_path_denied_for_crew2,
    test_symlink_escape_denied_for_crew2,
    test_own_crew2_artifact_tools_fail_clearly_before_written,
]


def main() -> int:
    for fn in ALL_TESTS:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            _FAIL.append(fn.__name__)
            print(f"FAIL  {fn.__name__}  raised {type(exc).__name__}: {exc}")

    print(f"\n{len(_PASS)} passed, {len(_FAIL)} failed")
    if _FAIL:
        print("all failed:", _FAIL)
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
