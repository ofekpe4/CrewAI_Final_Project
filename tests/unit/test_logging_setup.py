"""Unit tests for ``harbor_vale.logging_setup`` (PROJECT_PLAN.md §Q.1, §O.1).

Focus: initialisation succeeds, the per-run file behaviour, no duplicate handlers
on repeated setup, and that none of this needs an LLM/API key.

Runnable two ways:
  * ``pytest tests/unit/test_logging_setup.py``   (once pytest is installed)
  * ``python tests/unit/test_logging_setup.py``   (no test dependency required)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# --- make the project importable without an install step ---
_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale import io_paths, logging_setup  # noqa: E402

_RUN_ID = "pytest-logging-setup-check"


def _clean() -> None:
    logging_setup.reset_logging()
    stray = io_paths.log_file_for(_RUN_ID)
    if stray.exists():
        stray.unlink()


def _hv_handlers() -> list[logging.Handler]:
    return list(logging.getLogger("harbor_vale").handlers)


def test_setup_without_run_id_returns_project_logger() -> None:
    _clean()
    try:
        logger = logging_setup.setup_logging()
        assert logger.name == "harbor_vale"
        console = [h for h in _hv_handlers() if getattr(h, "_hv_console_handler", False)]
        assert len(console) == 1
        assert console[0].level == logging.INFO
        # No file handler when no run_id was given.
        assert not [h for h in _hv_handlers() if getattr(h, "_hv_file_handler", False)]
    finally:
        _clean()


def test_repeated_setup_does_not_stack_handlers() -> None:
    _clean()
    try:
        logging_setup.setup_logging()
        logging_setup.setup_logging()
        logging_setup.setup_logging(run_id=_RUN_ID)
        logging_setup.setup_logging(run_id=_RUN_ID)
        console = [h for h in _hv_handlers() if getattr(h, "_hv_console_handler", False)]
        files = [h for h in _hv_handlers() if getattr(h, "_hv_file_handler", False)]
        assert len(console) == 1
        assert len(files) == 1
    finally:
        _clean()


def test_run_id_creates_and_writes_the_planned_log_file() -> None:
    _clean()
    try:
        logging_setup.setup_logging(run_id=_RUN_ID)
        target = io_paths.log_file_for(_RUN_ID)
        assert target.exists()
        assert target == io_paths.LOGS / f"pipeline_{_RUN_ID}.log"

        logging_setup.get_logger("io_paths_test").debug("hello-from-test-%s", _RUN_ID)
        for handler in _hv_handlers():
            handler.flush()
        contents = target.read_text(encoding="utf-8")
        assert f"hello-from-test-{_RUN_ID}" in contents
        assert "harbor_vale.io_paths_test" in contents
    finally:
        _clean()


def test_file_handler_is_debug_level() -> None:
    _clean()
    try:
        logging_setup.setup_logging(run_id=_RUN_ID)
        files = [h for h in _hv_handlers() if getattr(h, "_hv_file_handler", False)]
        assert len(files) == 1
        assert files[0].level == logging.DEBUG
    finally:
        _clean()


def test_setup_needs_no_api_key() -> None:
    _clean()
    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
        logger = logging_setup.setup_logging(run_id=_RUN_ID)
        logger.info("no key required for logging")
        assert io_paths.log_file_for(_RUN_ID).exists()
    finally:
        if saved is not None:
            os.environ["OPENAI_API_KEY"] = saved
        _clean()


def test_get_logger_namespacing() -> None:
    assert logging_setup.get_logger("flow.pipeline").name == "harbor_vale.flow.pipeline"
    assert logging_setup.get_logger("harbor_vale.contract").name == "harbor_vale.contract"
    assert logging_setup.get_logger("harbor_vale").name == "harbor_vale"


def test_reset_logging_removes_only_our_handlers() -> None:
    _clean()
    try:
        project_logger = logging.getLogger("harbor_vale")
        sentinel = logging.NullHandler()
        project_logger.addHandler(sentinel)

        logging_setup.setup_logging(run_id=_RUN_ID)
        assert len(_hv_handlers()) >= 3  # sentinel + console + file

        logging_setup.reset_logging()
        remaining = _hv_handlers()
        assert sentinel in remaining
        assert not [h for h in remaining if getattr(h, "_hv_console_handler", False)]
        assert not [h for h in remaining if getattr(h, "_hv_file_handler", False)]

        project_logger.removeHandler(sentinel)
    finally:
        _clean()


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
