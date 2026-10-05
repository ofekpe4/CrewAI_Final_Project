"""`tests/failure/` — scenario 9/10: `corrupt_contract_json` (PROJECT_PLAN.md §O.3).

Truncates the contract JSON's bytes mid-structure so it no longer parses.
Expected: `ARTIFACTS_CONTRACT_JSON_PARSES` fails, and — because families B-G
all need a successfully-parsed contract — every downstream family is
skipped entirely (the documented "prerequisite gating" behaviour, §F.1),
never silently treated as a pass.

Runnable two ways:
  * ``pytest tests/failure/test_corrupt_contract_json.py``
  * ``python tests/failure/test_corrupt_contract_json.py``
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
from tests.failure._support import copy_real_handoff, findings, mutate_contract_in_place, run_flow_with_handoff  # noqa: E402


def test_corrupt_contract_json_blocks_crew2() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_crew1_result = copy_real_handoff(tmp_path / "crew1_out")
        mutate_contract_in_place(tmp_path / "crew1_out", fi.corrupt_contract_json)

        state, crew2_calls, report = run_flow_with_handoff(tmp_path, fake_crew1_result)

        assert state.validation_passed is False
        parse_hits = findings(report, "ARTIFACTS_CONTRACT_JSON_PARSES")
        assert len(parse_hits) == 1 and parse_hits[0].severity == "ERROR"
        assert state.crew2_started is False

        # prerequisite gating: no family beyond "artifacts" ran at all
        assert {f.check_family for f in report.findings} == {"artifacts"}

        assert state.status == "halted_validation"
        assert crew2_calls["n"] == 0


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
