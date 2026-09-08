"""Minimal, deterministic logging foundation (PROJECT_PLAN.md §Q.1).

- Console handler at INFO.
- Optional per-run file handler at DEBUG, written to
  ``logs/pipeline_<run_id>.log``.
- One logger namespace, ``harbor_vale``; modules get children via
  :func:`get_logger`.
- Idempotent: calling :func:`setup_logging` more than once reuses the handlers it
  already installed instead of stacking new ones.

No external logging services, no telemetry, no MLOps. Importing this module and
calling :func:`setup_logging` require no API key and make no network calls.
"""

from __future__ import annotations

import logging
from pathlib import Path

from harbor_vale.io_paths import LOGS, log_file_for

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
_LOGGER_NAMESPACE = "harbor_vale"

# Attributes stamped on handlers this module installs, so repeat calls can find
# and reuse them rather than adding duplicates.
_CONSOLE_MARK = "_hv_console_handler"
_FILE_MARK = "_hv_file_handler"


def _formatter() -> logging.Formatter:
    return logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)


def setup_logging(
    run_id: str | None = None,
    console_level: int | str = logging.INFO,
    file_level: int | str = logging.DEBUG,
) -> logging.Logger:
    """Configure and return the project logger (``harbor_vale``).

    Parameters
    ----------
    run_id:
        If given, a file handler for ``logs/pipeline_<run_id>.log`` is added at
        ``file_level``. If ``None``, only the console handler is configured.
    console_level, file_level:
        Levels for the two handlers. Defaults match PROJECT_PLAN.md §Q.1
        (console INFO, file DEBUG).

    Calling this repeatedly is safe: the console handler is created at most once,
    and at most one file handler per distinct target path is created.
    """
    logger = logging.getLogger(_LOGGER_NAMESPACE)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # don't double-log through the root logger

    # --- console handler: exactly one ---
    console = next(
        (h for h in logger.handlers if getattr(h, _CONSOLE_MARK, False)), None
    )
    if console is None:
        console = logging.StreamHandler()
        setattr(console, _CONSOLE_MARK, True)
        console.setFormatter(_formatter())
        logger.addHandler(console)
    console.setLevel(console_level)

    # --- optional per-run file handler: one per distinct path ---
    if run_id:
        LOGS.mkdir(parents=True, exist_ok=True)
        target = log_file_for(run_id).resolve()
        already = any(
            getattr(h, _FILE_MARK, False)
            and Path(getattr(h, "baseFilename", "")).resolve() == target
            for h in logger.handlers
        )
        if not already:
            file_handler = logging.FileHandler(target, encoding="utf-8")
            setattr(file_handler, _FILE_MARK, True)
            file_handler.setLevel(file_level)
            file_handler.setFormatter(_formatter())
            logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a module logger under the ``harbor_vale`` namespace.

    ``get_logger(__name__)`` from anywhere in the package yields a logger whose
    name starts with ``harbor_vale`` (PROJECT_PLAN.md §Q.1: a logger per module).
    """
    if name == _LOGGER_NAMESPACE or name.startswith(_LOGGER_NAMESPACE + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_LOGGER_NAMESPACE}.{name}")


def reset_logging() -> None:
    """Remove and close every handler this module installed on the project logger.

    Intended for tests and for re-initialising a long-lived process. Handlers not
    installed by :func:`setup_logging` are left untouched.
    """
    logger = logging.getLogger(_LOGGER_NAMESPACE)
    for handler in list(logger.handlers):
        if getattr(handler, _CONSOLE_MARK, False) or getattr(handler, _FILE_MARK, False):
            logger.removeHandler(handler)
            handler.close()
