"""Safe, closed-vocabulary invocation of the existing Phase 8 CLI entrypoint
(`scripts/run_pipeline.py`) from the Streamlit UI (PROJECT_PLAN.md §Q.5,
Phase 9 Internal Gate 9.4).

**The UI never re-implements pipeline orchestration.** This module's only
job is to map a small, closed set of UI choices onto the exact same
`argv` a human would type at the terminal, and run it as a fixed-argument
subprocess:

- ``shell=False`` always — no shell, no string interpolation into a command
  line, no `os.system`.
- The executable is always the current interpreter (`sys.executable`) and
  the script is always the fixed path to `scripts/run_pipeline.py` — never
  a path derived from user input.
- The only accepted "free" inputs are a `RunMode` literal and a fault
  scenario literal, both validated against a closed vocabulary
  (`InvalidRunRequest` otherwise) before a process is ever spawned.
- Fault injection is never combined with `validate_only` (the CLI itself
  rejects that combination — this module rejects it earlier, before
  spawning anything) and is never turned on implicitly.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Iterator, Literal

from harbor_vale.io_paths import PROJECT_ROOT

RunMode = Literal["normal", "validate_only", "replay_plans"]

_VALID_MODES: tuple[RunMode, ...] = ("normal", "validate_only", "replay_plans")
_VALID_FAULTS: tuple[str, ...] = ("scale_change",)  # same closed vocabulary as scripts/run_pipeline.py

_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_pipeline.py"


class InvalidRunRequest(ValueError):
    """Raised before any process is spawned — a UI control mapped to
    something outside the closed, approved flag vocabulary."""


def build_command(mode: RunMode, fault_injection: str | None = None) -> list[str]:
    """Builds the fixed argv for one pipeline invocation. Never returns a
    shell string — always a list, always passed with `shell=False`."""
    if mode not in _VALID_MODES:
        raise InvalidRunRequest(f"unsupported run mode: {mode!r}")
    if fault_injection is not None and fault_injection not in _VALID_FAULTS:
        raise InvalidRunRequest(f"unsupported fault scenario: {fault_injection!r}")
    if fault_injection and mode == "validate_only":
        # Mirrors scripts/run_pipeline.py's own argparse rejection — caught
        # here too so the UI can show a clear message before ever spawning
        # a process that would immediately exit with a CLI usage error.
        raise InvalidRunRequest(
            "--validate-only has no run-scoped snapshot to mutate; it cannot be combined with fault injection."
        )

    cmd: list[str] = [sys.executable, str(_SCRIPT_PATH)]
    if mode == "validate_only":
        cmd.append("--validate-only")
    elif mode == "replay_plans":
        cmd.append("--replay-plans")
    if fault_injection:
        cmd += ["--inject-failure", fault_injection]
    return cmd


def stream_pipeline_run(mode: RunMode, fault_injection: str | None = None) -> Iterator[str]:
    """Runs the pipeline as a subprocess and yields its combined
    stdout/stderr, one line at a time, as it is produced — for `st.status()`
    live progress (Internal Gate 9.4). The final yielded line is always
    ``__EXIT_CODE__:<n>`` so the caller can distinguish success from
    failure without inspecting process internals directly.

    Raises `InvalidRunRequest` before spawning anything for a request
    outside the closed vocabulary above.
    """
    cmd = build_command(mode, fault_injection)
    process = subprocess.Popen(  # noqa: S603 — fixed argv, shell=False, no user-controlled executable/path
        cmd,
        cwd=str(PROJECT_ROOT),
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    try:
        assert process.stdout is not None
        for raw_line in process.stdout:
            yield raw_line.rstrip("\n")
    finally:
        process.wait()
    yield f"__EXIT_CODE__:{process.returncode}"
