"""Unit tests for ``harbor_vale.io_paths`` (PROJECT_PLAN.md §L, §O.1, §W).

Focus: project-root resolution, the approved important locations, absence of
machine-specific absolute paths, and determinism.

Runnable two ways:
  * ``pytest tests/unit/test_io_paths.py``   (once pytest is installed)
  * ``python tests/unit/test_io_paths.py``   (no test dependency required)
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

# --- make the project importable without an install step ---
_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale import io_paths  # noqa: E402


def _exported_paths() -> dict[str, Path]:
    return {
        name: value
        for name, value in vars(io_paths).items()
        if isinstance(value, Path) and not name.startswith("_")
    }


def test_project_root_is_the_repo_root() -> None:
    root = io_paths.PROJECT_ROOT
    assert root.is_dir()
    assert (root / "PROJECT_PLAN.md").is_file()
    assert (root / "config").is_dir()
    assert (root / "src" / "harbor_vale").is_dir()
    assert (root / ".git").exists()


def test_project_root_is_derived_from_file_location_not_hardcoded() -> None:
    # Derived purely from this module's own location — three parents up.
    expected = Path(io_paths.__file__).resolve().parents[2]
    assert io_paths.PROJECT_ROOT == expected


def test_source_has_no_machine_specific_absolute_paths() -> None:
    src = Path(io_paths.__file__).read_text(encoding="utf-8")
    for needle in ("/Users/", "/home/", "C:\\", str(Path.home())):
        assert needle not in src, f"machine-specific path {needle!r} in io_paths.py"


def test_every_exported_path_is_within_project_root() -> None:
    root = io_paths.PROJECT_ROOT.resolve()
    for name, value in _exported_paths().items():
        resolved = value.resolve()
        assert resolved == root or root in resolved.parents, f"{name} escapes PROJECT_ROOT: {value}"


def test_key_locations_resolve_exactly_as_the_plan_specifies() -> None:
    root = io_paths.PROJECT_ROOT
    assert io_paths.ARTIFACTS == root / "artifacts"
    assert io_paths.CONFIG == root / "config"
    assert io_paths.SRC == root / "src"
    assert io_paths.DATA_RAW == root / "data" / "raw"
    assert io_paths.LOGS == root / "logs"
    assert io_paths.RUNS == root / "runs"
    assert io_paths.SETTINGS_YAML == root / "config" / "settings.yaml"
    # The approved handoff — exactly these two files (§G.0).
    assert io_paths.HANDOFF_CLEAN_DATA == root / "artifacts" / "crew1" / "clean_data.csv"
    assert io_paths.HANDOFF_CONTRACT == root / "artifacts" / "crew1" / "dataset_contract.json"
    # Blocked-for-Crew-2 narrative artifacts still have canonical locations.
    assert io_paths.INSIGHTS_MD == root / "artifacts" / "crew1" / "insights.md"
    assert io_paths.EDA_REPORT_HTML == root / "artifacts" / "crew1" / "eda_report.html"
    # Gate + Crew 2.
    assert io_paths.VALIDATION_REPORT_JSON == root / "artifacts" / "validation" / "validation_report.json"
    assert io_paths.FEATURES_CSV == root / "artifacts" / "crew2" / "features.csv"
    assert io_paths.MODEL_JOBLIB == root / "artifacts" / "crew2" / "model.joblib"
    assert io_paths.RUN_METADATA_JSON == root / "artifacts" / "run_metadata.json"


def test_values_are_deterministic_across_reimport() -> None:
    before = {k: str(v) for k, v in _exported_paths().items()}
    reloaded = importlib.reload(io_paths)
    after = {
        k: str(v)
        for k, v in vars(reloaded).items()
        if isinstance(v, Path) and not k.startswith("_")
    }
    assert before == after


def test_log_file_for_matches_plan_naming() -> None:
    assert io_paths.log_file_for("20260908T101112Z-abcd") == (
        io_paths.LOGS / "pipeline_20260908T101112Z-abcd.log"
    )
    try:
        io_paths.log_file_for("")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("empty run_id must raise ValueError")


def test_ensure_runtime_dirs_is_idempotent_and_only_touches_outputs() -> None:
    first = io_paths.ensure_runtime_dirs()
    second = io_paths.ensure_runtime_dirs()
    assert first == second
    for directory in first:
        assert directory.is_dir()
    # Source trees are never among the ensured directories.
    assert io_paths.SRC not in first
    assert io_paths.CONFIG not in first
    assert io_paths.TESTS not in first


def test_relative_to_root_is_portable() -> None:
    assert io_paths.relative_to_root(io_paths.ARTIFACTS) == "artifacts"
    assert io_paths.relative_to_root(io_paths.HANDOFF_CONTRACT) == (
        "artifacts/crew1/dataset_contract.json"
    )
    # A path outside the project is returned unchanged (POSIX). Use a synthetic
    # absolute path with no real filesystem components so symlink normalisation
    # (e.g. macOS /etc -> /private/etc) cannot rewrite it.
    outside = io_paths.relative_to_root("/nowhere/outside/the/project")
    assert outside == "/nowhere/outside/the/project"


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
