"""`tests/failure/` — Internal Gate 10.4: the `--validate-only` demonstration
(PROJECT_PLAN.md §P.1 mechanism 2).

The second legitimate failure-demo mechanism — "מישהו ערך את הקובץ
במעלה הזרם" (someone edited the file upstream): `--validate-only` skips
`load_dataset` and `run_analyst_crew` entirely and runs the gate against
whatever is already on disk, **without ever overwriting it** — unlike the
old, rejected demo design (§P, "תיקון #2"), where re-running the full
pipeline would have regenerated and silently erased the edit before the
gate ever saw it.

Both sub-cases are reached by monkeypatching the fixed production path
constants `validate_handoff` reads (`pipeline_flow.HANDOFF_CLEAN_DATA` /
`HANDOFF_CONTRACT` / `EDA_REPORT_HTML` / `INSIGHTS_MD`) to point at a
prepared `tmp_path` candidate — never by touching the real committed
`artifacts/crew1/*`.

Runnable two ways:
  * ``pytest tests/failure/test_validate_only_demo.py``
  * ``python tests/failure/test_validate_only_demo.py``
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import harbor_vale.flow.pipeline_flow as pipeline_flow  # noqa: E402
from harbor_vale.demo import fault_injection as fi  # noqa: E402
from harbor_vale.flow import HarborValeFlow  # noqa: E402
from harbor_vale.io_paths import CREW1  # noqa: E402
from tests.failure._support import mutate_csv_in_place, patched  # noqa: E402

_NAMES = ("clean_data.csv", "dataset_contract.json", "eda_report.html", "insights.md")


def _copy_candidate(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in _NAMES:
        shutil.copy2(CREW1 / name, dest / name)


def _run_validate_only(candidate_dir: Path):
    crew1_calls = {"n": 0}
    crew2_calls = {"n": 0}

    def fake_crew1(raw_df, *, run_id, llm=None):  # noqa: ARG001
        crew1_calls["n"] += 1
        raise AssertionError("Crew 1 must never run in --validate-only mode")

    def fake_crew2(**kwargs):  # noqa: ARG001
        crew2_calls["n"] += 1
        raise AssertionError("Crew 2 must never run in --validate-only mode")

    with patched(pipeline_flow, "_crew1_run_analyst_crew", fake_crew1), \
         patched(pipeline_flow, "_crew2_run_scientist_crew", fake_crew2), \
         patched(pipeline_flow, "HANDOFF_CLEAN_DATA", candidate_dir / "clean_data.csv"), \
         patched(pipeline_flow, "HANDOFF_CONTRACT", candidate_dir / "dataset_contract.json"), \
         patched(pipeline_flow, "EDA_REPORT_HTML", candidate_dir / "eda_report.html"), \
         patched(pipeline_flow, "INSIGHTS_MD", candidate_dir / "insights.md"):
        flow = HarborValeFlow(validate_only=True)
        flow.kickoff()
    return flow.state, crew1_calls, crew2_calls, flow._validation_report


def test_validate_only_detects_an_upstream_edit_without_overwriting_it() -> None:
    """Step 2 of §P.1 mechanism 2's manual sequence: 'someone edited
    clean_data.csv' — reproduced here by applying the real `scale_change`
    fault helper to a prepared candidate copy, never to the committed
    `artifacts/crew1/*`."""
    with tempfile.TemporaryDirectory() as tmp:
        candidate_dir = Path(tmp) / "candidate"
        _copy_candidate(candidate_dir)
        mutate_csv_in_place(candidate_dir, fi.scale_change, column="MonthlyCharges", factor=100.0)
        candidate_bytes_before_gate = {name: (candidate_dir / name).read_bytes() for name in _NAMES}

        state, crew1_calls, crew2_calls, report = _run_validate_only(candidate_dir)

        # Crew 1 and Crew 2 are both structurally skipped
        assert crew1_calls["n"] == 0
        assert crew2_calls["n"] == 0
        assert state.crew2_started is False

        # the validator reports the real mismatch — never silently passes a
        # mutated candidate just because it technically loads
        assert state.validation_passed is False
        assert state.status == "halted_validation"
        assert any(f.check_family == "scale_drift" for f in report.findings)

        # the gate never overwrote what it validated — not even the
        # candidate copy, let alone the real committed artifacts
        for name in _NAMES:
            assert (candidate_dir / name).read_bytes() == candidate_bytes_before_gate[name]

    # the real committed artifacts/crew1/* were never even opened for writing
    real_csv_bytes = (CREW1 / "clean_data.csv").read_bytes()
    assert real_csv_bytes != candidate_bytes_before_gate["clean_data.csv"]  # proves the two are genuinely distinct files


def test_validate_only_passes_an_unmodified_candidate_without_running_either_crew() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        candidate_dir = Path(tmp) / "candidate"
        _copy_candidate(candidate_dir)

        state, crew1_calls, crew2_calls, _report = _run_validate_only(candidate_dir)

        assert crew1_calls["n"] == 0
        assert crew2_calls["n"] == 0
        assert state.crew2_started is False
        assert state.validation_passed is True
        assert state.status == "completed"


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
