"""Phase 9 smoke test — `test_app_imports` (PROJECT_PLAN.md §O.4).

Proves: the main Streamlit app and all six pages import/load without error,
the shared UI helpers import cleanly, and none of this requires
`OPENAI_API_KEY` to be set (viewing already-produced results must never
need a live LLM key).

No OpenAI calls. No live Crew execution. Run directly:
    python tests/smoke/test_app_imports.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import ALL_PAGES, PROJECT_ROOT, isolated_artifacts, run_page  # noqa: E402

_PASS: list[str] = []
_FAIL: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        _PASS.append(name)
        print(f"PASS  {name}")
    else:
        _FAIL.append(name)
        print(f"FAIL  {name}  {detail}")


def test_no_api_key_required_to_import() -> None:
    """Importing every module this app needs must never require
    OPENAI_API_KEY — only Crew *execution* needs it (Phase 0 invariant,
    still true for Phase 9's read-only pages)."""
    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
        import importlib

        for mod_name in ("lib.ui_helpers", "lib.pipeline_runner"):
            mod = importlib.import_module(mod_name)
            importlib.reload(mod)
        check("test_no_api_key_required_to_import", True)
    except Exception as exc:  # noqa: BLE001
        check("test_no_api_key_required_to_import", False, f"{type(exc).__name__}: {exc}")
    finally:
        if saved is not None:
            os.environ["OPENAI_API_KEY"] = saved


def test_shared_helpers_import() -> None:
    try:
        from lib import ui_helpers, pipeline_runner  # noqa: F401

        check("test_shared_helpers_import", True)
    except Exception as exc:  # noqa: BLE001
        check("test_shared_helpers_import", False, f"{type(exc).__name__}: {exc}")


def test_all_scripts_compile() -> None:
    """Every page + the main app is syntactically valid Python."""
    import py_compile

    ok = True
    detail = ""
    for script in ALL_PAGES:
        try:
            py_compile.compile(str(script), doraise=True)
        except py_compile.PyCompileError as exc:
            ok = False
            detail = f"{script.name}: {exc}"
            break
    check("test_all_scripts_compile", ok, detail)


def test_main_app_runs_without_exception() -> None:
    with tempfile.TemporaryDirectory() as td:
        with isolated_artifacts(Path(td)):
            at = run_page(PROJECT_ROOT / "app" / "streamlit_app.py")
            check(
                "test_main_app_runs_without_exception",
                len(at.exception) == 0,
                str(list(at.exception)),
            )


def test_all_six_pages_run_without_exception() -> None:
    with tempfile.TemporaryDirectory() as td:
        with isolated_artifacts(Path(td)):
            for script in ALL_PAGES[1:]:
                at = run_page(script)
                check(
                    f"test_page_runs_without_exception[{script.name}]",
                    len(at.exception) == 0,
                    str(list(at.exception)),
                )


ALL_TESTS = [
    test_no_api_key_required_to_import,
    test_shared_helpers_import,
    test_all_scripts_compile,
    test_main_app_runs_without_exception,
    test_all_six_pages_run_without_exception,
]


def main() -> int:
    for fn in ALL_TESTS:
        fn()
    print(f"\n{len(_PASS)} passed, {len(_FAIL)} failed")
    if _FAIL:
        print("all failed:", _FAIL)
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
