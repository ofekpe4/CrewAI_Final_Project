"""Phase 9 smoke test — `test_app_handles_missing_artifacts` (PROJECT_PLAN.md
§O.4, Internal Gate 9.10: "the application MUST work before the first
pipeline run").

With a completely empty temporary artifacts directory, every page and the
main app must survive — no uncaught `FileNotFoundError`, no crash, and each
page must render a clear empty state rather than fabricate data.

Run directly: python tests/smoke/test_app_handles_missing_artifacts.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import ALL_PAGES, isolated_artifacts, run_page  # noqa: E402

_PASS: list[str] = []
_FAIL: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        _PASS.append(name)
        print(f"PASS  {name}")
    else:
        _FAIL.append(name)
        print(f"FAIL  {name}  {detail}")


def test_every_page_survives_empty_artifacts_dir() -> None:
    with tempfile.TemporaryDirectory() as td:
        empty_dir = Path(td)  # deliberately never populated
        with isolated_artifacts(empty_dir):
            for script in ALL_PAGES:
                at = run_page(script)
                check(
                    f"test_survives_empty_artifacts[{script.name}]",
                    len(at.exception) == 0,
                    str(list(at.exception)),
                )


def test_main_app_shows_no_run_yet_message() -> None:
    with tempfile.TemporaryDirectory() as td:
        with isolated_artifacts(Path(td)):
            at = run_page(Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py")
            info_texts = " ".join(b.value for b in at.info)
            markdown_texts = " ".join(m.value for m in at.markdown)
            combined = info_texts + markdown_texts
            check(
                "test_main_app_shows_no_run_yet_message",
                "no run" in combined.lower() or "no pipeline run" in combined.lower(),
                combined[:300],
            )


def test_contract_page_shows_empty_state_not_crash() -> None:
    with tempfile.TemporaryDirectory() as td:
        with isolated_artifacts(Path(td)):
            script = Path(__file__).resolve().parents[2] / "app" / "pages" / "3_Dataset_Contract.py"
            at = run_page(script)
            check("test_contract_page_no_exception", len(at.exception) == 0, str(list(at.exception)))


def test_logs_page_shows_empty_state_not_crash() -> None:
    with tempfile.TemporaryDirectory() as td:
        with isolated_artifacts(Path(td)):
            script = Path(__file__).resolve().parents[2] / "app" / "pages" / "6_Logs.py"
            at = run_page(script)
            check("test_logs_page_no_exception", len(at.exception) == 0, str(list(at.exception)))


ALL_TESTS = [
    test_every_page_survives_empty_artifacts_dir,
    test_main_app_shows_no_run_yet_message,
    test_contract_page_shows_empty_state_not_crash,
    test_logs_page_shows_empty_state_not_crash,
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
