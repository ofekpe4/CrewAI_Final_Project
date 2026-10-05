"""`tests/failure/` — scenario 7/10: `flip_target_encoding` (PROJECT_PLAN.md §O.3).

Swaps every `churn` label (`0<->1`) — same dtype, same closed domain, only
the label's *meaning* inverts. Schema-level checks alone cannot catch this
(that is the point of the scenario); only a declared `target.drift` policy
comparing the candidate's positive rate against the contract snapshot can.

The real committed production contract does not declare `target.drift`
(verified: `artifacts/crew1/dataset_contract.json`'s `target.drift is
null`) — this scenario therefore uses the Phase 3/4 synthetic fixture
(`tests/fixtures/gate_fixtures.py`) with a `target.drift` policy attached,
the one legitimate way to exercise a declared-but-not-yet-produced policy
without inventing a fake finding.

Runnable two ways:
  * ``pytest tests/failure/test_flip_target_encoding.py``
  * ``python tests/failure/test_flip_target_encoding.py``
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale.demo import fault_injection as fi  # noqa: E402
from tests.failure._support import build_fixture_handoff, findings, mutate_csv_in_place, run_flow_with_handoff  # noqa: E402


def test_flip_target_encoding_blocks_crew2_when_drift_policy_declared() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_crew1_result = build_fixture_handoff(tmp_path / "crew1_out", with_target_drift=True)
        mutate_csv_in_place(tmp_path / "crew1_out", fi.flip_target_encoding, target_column="churn")

        state, crew2_calls, report = run_flow_with_handoff(tmp_path, fake_crew1_result)

        assert state.validation_passed is False
        hits = findings(report, "TARGET_POSITIVE_RATE_DRIFT")
        assert len(hits) == 1 and hits[0].severity == "ERROR"
        assert state.crew2_started is False

        assert state.status == "halted_validation"
        assert crew2_calls["n"] == 0
        assert "target" in {f.check_family for f in report.findings}


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
