"""`tests/failure/` — scenario 10/10: `contract_only_change` (PROJECT_PLAN.md
§O.3) — the deliberate WARN-only / non-blocking case.

**This is not a "every mutation must fail" test — it is the opposite.** The
Plan is explicit: "לא כל שינוי חוסם" (not every contract change blocks the
gate). `gender` is removed from the contract's `columns`/`integrity.
column_order` ONLY — the CSV itself is untouched, so the column is still
present and unrecognized. Expected: `SCHEMA_UNKNOWN_COLUMN` at whatever
severity `validation_policy.on_unknown_column` declares — the real/fixture
default is `"warn"` — so the gate PASSES (0 errors) and the pipeline
CONTINUES into Crew 2.

Uses the Phase 3/4 synthetic fixture (`tests/fixtures/gate_fixtures.py`):
its draft's `required_features` names only 4 columns, so `gender` is a
genuinely unreferenced column to drop from the contract. The real
production contract's `required_features` lists every non-key, non-target
column — there is no unreferenced column to use this scenario on there.

Runnable two ways:
  * ``pytest tests/failure/test_contract_only_change.py``
  * ``python tests/failure/test_contract_only_change.py``
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
from tests.failure._support import build_fixture_handoff, findings, mutate_contract_in_place, run_flow_with_handoff  # noqa: E402


def test_contract_only_change_is_warn_only_and_crew2_continues() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_crew1_result = build_fixture_handoff(tmp_path / "crew1_out")
        mutate_contract_in_place(tmp_path / "crew1_out", fi.contract_only_change, drop_column="gender")

        state, crew2_calls, report = run_flow_with_handoff(tmp_path, fake_crew1_result, expect_crew2_runs=True)

        # the finding exists, as a WARNING, never an ERROR
        hits = findings(report, "SCHEMA_UNKNOWN_COLUMN")
        assert any(f.column == "gender" and f.severity == "WARN" for f in hits)
        assert not any(f.column == "gender" and f.severity == "ERROR" for f in hits)

        # the gate PASSES (0 errors — WARN never fails it, §F.2) and the
        # pipeline CONTINUES — the opposite of every other scenario in this
        # directory, proving the gate does not block on every contract edit.
        assert state.validation_passed is True
        assert state.validation_errors == 0
        assert state.crew2_started is True
        assert crew2_calls["n"] == 1
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
