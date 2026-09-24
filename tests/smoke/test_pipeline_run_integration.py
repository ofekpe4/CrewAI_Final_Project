"""Phase 9 — UI run-button integration test (PROJECT_PLAN.md §Q.5, Phase 9
Internal Gate 9.13).

Proves the UI's "Run pipeline" control targets the existing Phase 8
entrypoint (`scripts/run_pipeline.py`) through a closed, fixed argv —
never an arbitrary/user-constructed shell command — using module-attribute
patching only (the same technique `tests/unit/test_pipeline_flow.py` already
uses; no live subprocess is ever actually spawned by this file).

No OpenAI calls. No live Crew execution, no real subprocess spawned. Run
directly: python tests/smoke/test_pipeline_run_integration.py
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import PROJECT_ROOT, isolated_artifacts, run_page  # noqa: E402
from lib import pipeline_runner as runner  # noqa: E402

_PASS: list[str] = []
_FAIL: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        _PASS.append(name)
        print(f"PASS  {name}")
    else:
        _FAIL.append(name)
        print(f"FAIL  {name}  {detail}")


# ---------------------------------------------------------------------------
# build_command — pure function, no process ever spawned by these
# ---------------------------------------------------------------------------


def test_normal_mode_maps_to_the_real_entrypoint_no_extra_flags() -> None:
    cmd = runner.build_command("normal")
    check(
        "test_normal_mode_maps_to_the_real_entrypoint_no_extra_flags",
        cmd == [sys.executable, str(PROJECT_ROOT / "scripts" / "run_pipeline.py")],
        str(cmd),
    )


def test_normal_mode_never_includes_fault_flag_by_default() -> None:
    cmd = runner.build_command("normal")
    check(
        "test_normal_mode_never_includes_fault_flag_by_default",
        "--inject-failure" not in cmd,
        str(cmd),
    )


def test_validate_only_maps_to_validate_only_flag() -> None:
    cmd = runner.build_command("validate_only")
    check(
        "test_validate_only_maps_to_validate_only_flag",
        cmd[-1] == "--validate-only" and "--inject-failure" not in cmd,
        str(cmd),
    )


def test_replay_plans_maps_to_replay_flag() -> None:
    cmd = runner.build_command("replay_plans")
    check("test_replay_plans_maps_to_replay_flag", cmd[-1] == "--replay-plans", str(cmd))


def test_explicit_fault_injection_maps_to_inject_failure_flag() -> None:
    cmd = runner.build_command("normal", "scale_change")
    check(
        "test_explicit_fault_injection_maps_to_inject_failure_flag",
        cmd[-2:] == ["--inject-failure", "scale_change"],
        str(cmd),
    )


def test_invalid_mode_rejected_before_any_process() -> None:
    try:
        runner.build_command("rm -rf /")  # type: ignore[arg-type]
        check("test_invalid_mode_rejected_before_any_process", False, "did not raise")
    except runner.InvalidRunRequest:
        check("test_invalid_mode_rejected_before_any_process", True)


def test_invalid_fault_scenario_rejected() -> None:
    try:
        runner.build_command("normal", "definitely_not_a_real_fault")
        check("test_invalid_fault_scenario_rejected", False, "did not raise")
    except runner.InvalidRunRequest:
        check("test_invalid_fault_scenario_rejected", True)


def test_fault_injection_rejected_with_validate_only() -> None:
    try:
        runner.build_command("validate_only", "scale_change")
        check("test_fault_injection_rejected_with_validate_only", False, "did not raise")
    except runner.InvalidRunRequest:
        check("test_fault_injection_rejected_with_validate_only", True)


def test_command_is_never_a_shell_string() -> None:
    cmd = runner.build_command("normal")
    check("test_command_is_never_a_shell_string", isinstance(cmd, list), str(type(cmd)))


# ---------------------------------------------------------------------------
# stream_pipeline_run — subprocess wiring, Popen mocked (module-attribute
# swap, no real process spawned)
# ---------------------------------------------------------------------------


class _FakeStdout:
    def __init__(self, lines: list[str]):
        self._lines = lines

    def __iter__(self):
        return iter(self._lines)


class _FakeProcess:
    def __init__(self, lines: list[str], returncode: int = 0):
        self.stdout = _FakeStdout(lines)
        self.returncode = returncode
        self.waited = False

    def wait(self) -> None:
        self.waited = True


@contextmanager
def _patched_popen(fake_process: _FakeProcess):
    calls: list[dict] = []

    def _fake_popen(cmd, **kwargs):
        calls.append({"cmd": cmd, "kwargs": kwargs})
        return fake_process

    original = runner.subprocess.Popen
    runner.subprocess.Popen = _fake_popen  # type: ignore[assignment]
    try:
        yield calls
    finally:
        runner.subprocess.Popen = original


def test_stream_pipeline_run_uses_fixed_argv_and_shell_false() -> None:
    fake = _FakeProcess(["line one", "line two"], returncode=0)
    with _patched_popen(fake) as calls:
        lines = list(runner.stream_pipeline_run("normal"))
    check("test_stream_pipeline_run_spawned_once", len(calls) == 1, str(calls))
    check("test_stream_pipeline_run_shell_false", calls[0]["kwargs"].get("shell") is False, str(calls[0]["kwargs"]))
    check(
        "test_stream_pipeline_run_fixed_argv",
        calls[0]["cmd"] == [sys.executable, str(PROJECT_ROOT / "scripts" / "run_pipeline.py")],
        str(calls[0]["cmd"]),
    )
    check("test_stream_pipeline_run_yields_lines", lines[:2] == ["line one", "line two"], str(lines))
    check("test_stream_pipeline_run_yields_exit_code", lines[-1] == "__EXIT_CODE__:0", str(lines))
    check("test_stream_pipeline_run_waits_on_process", fake.waited is True)


def test_stream_pipeline_run_rejects_bad_request_before_spawning() -> None:
    fake = _FakeProcess([], returncode=0)
    raised = False
    with _patched_popen(fake) as calls:
        try:
            list(runner.stream_pipeline_run("validate_only", "scale_change"))
        except runner.InvalidRunRequest:
            raised = True
    check("test_stream_pipeline_run_rejects_bad_request_before_spawning__raised", raised)
    check("test_stream_pipeline_run_rejects_bad_request_before_spawning__no_spawn", len(calls) == 0, str(calls))


# ---------------------------------------------------------------------------
# The Pipeline Run page itself must never spawn a process merely by loading
# (only an explicit button click may run the pipeline).
# ---------------------------------------------------------------------------


def test_page_load_never_spawns_a_process() -> None:
    fake = _FakeProcess([], returncode=0)
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        with isolated_artifacts(Path(td)):
            with _patched_popen(fake) as calls:
                at = run_page(PROJECT_ROOT / "app" / "pages" / "1_Pipeline_Run.py")
    check("test_page_load_no_exception", len(at.exception) == 0, str(list(at.exception)))
    check("test_page_load_never_spawns_a_process", len(calls) == 0, str(calls))


ALL_TESTS = [
    test_normal_mode_maps_to_the_real_entrypoint_no_extra_flags,
    test_normal_mode_never_includes_fault_flag_by_default,
    test_validate_only_maps_to_validate_only_flag,
    test_replay_plans_maps_to_replay_flag,
    test_explicit_fault_injection_maps_to_inject_failure_flag,
    test_invalid_mode_rejected_before_any_process,
    test_invalid_fault_scenario_rejected,
    test_fault_injection_rejected_with_validate_only,
    test_command_is_never_a_shell_string,
    test_stream_pipeline_run_uses_fixed_argv_and_shell_false,
    test_stream_pipeline_run_rejects_bad_request_before_spawning,
    test_page_load_never_spawns_a_process,
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
