"""`tests/failure/` — Internal Gate 10.2: default-run isolation
(PROJECT_PLAN.md §P.1 "בידוד ממסלול הייצור").

Proves fault injection cannot leak into a normal run, and cannot
permanently damage the real committed artifacts, from four independent
angles:

1. `HarborValeFlow()` with no `fault_injection` kwarg defaults to `None`.
2. `scripts/run_pipeline.py --inject-failure` has **no default** and
   **no environment-variable fallback** — it is settable only by an
   explicit CLI flag (`argparse`'s own `default=None`, no `os.environ`
   lookup anywhere in the module).
3. A fault-injected run (`fault_injection="scale_change"`) leaves the REAL
   committed `artifacts/crew1/clean_data.csv` / `dataset_contract.json`
   byte-identical before and after — the mutation lands only on the Flow's
   own run-scoped snapshot copy (`runs/<run_id>/handoff/`), never on the
   files it copied from.
4. A normal run (no fault flag) never emits the `CRITICAL FAULT INJECTION`
   log line at all.

No `--restore` step is required anywhere in this file — confirming §P.2's
own claim ("אין צורך ב-restore").

Runnable two ways:
  * ``pytest tests/failure/test_default_run_isolation.py``
  * ``python tests/failure/test_default_run_isolation.py``
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import sys
import tempfile
from io import StringIO
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale.flow import HarborValeFlow  # noqa: E402
from harbor_vale.io_paths import HANDOFF_CLEAN_DATA, HANDOFF_CONTRACT  # noqa: E402
from tests.failure._support import copy_real_handoff, run_flow_with_fault_injection, run_flow_with_handoff  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_flow_default_fault_injection_is_none() -> None:
    flow = HarborValeFlow()
    assert flow.state.fault_injection is None


def test_cli_inject_failure_flag_has_no_default_and_no_env_fallback() -> None:
    """Loads `scripts/run_pipeline.py` as a module (never executing its
    `__main__` block) and inspects its `argparse` configuration directly —
    the only way `fault_injection` can become non-`None` is an explicit
    `--inject-failure <scenario>` argv entry."""
    spec = importlib.util.spec_from_file_location(
        "harbor_vale_test_run_pipeline_cli", _ROOT / "scripts" / "run_pipeline.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    args_with_nothing = module._parse_args([])
    assert args_with_nothing.inject_failure is None

    import inspect

    source = inspect.getsource(module)
    assert "os.environ" not in source, "the CLI must never read a fault-injection flag from an env var"


def test_fault_injected_run_never_mutates_the_real_committed_handoff() -> None:
    real_csv_before = _sha256(HANDOFF_CLEAN_DATA)
    real_contract_before = _sha256(HANDOFF_CONTRACT)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_crew1_result = copy_real_handoff(tmp_path / "crew1_out")

        state, _crew2_calls, _report = run_flow_with_fault_injection(
            tmp_path, fake_crew1_result, fault_injection="scale_change"
        )
        assert state.status == "halted_validation"  # sanity: the fault actually fired

    # the files THIS run was shaped from, on the real committed path, are untouched
    assert _sha256(HANDOFF_CLEAN_DATA) == real_csv_before
    assert _sha256(HANDOFF_CONTRACT) == real_contract_before
    # no --restore of any kind was performed between the run above and these assertions


def test_normal_run_emits_no_critical_fault_injection_log_line() -> None:
    logger = logging.getLogger("harbor_vale")
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)

    records: list[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
            records.append(record)

    collector = _Collector()
    logger.addHandler(collector)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_crew1_result = copy_real_handoff(tmp_path / "crew1_out")
            state, _calls, _report = run_flow_with_handoff(tmp_path, fake_crew1_result, expect_crew2_runs=True)
            assert state.status == "completed"
            assert state.fault_injection is None
    finally:
        logger.removeHandler(collector)

    critical_fault_logs = [r for r in records if r.levelno == logging.CRITICAL and "FAULT INJECTION" in r.getMessage()]
    assert len(critical_fault_logs) == 0


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
