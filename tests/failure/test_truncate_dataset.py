"""`tests/failure/` — scenario 8/10: `truncate_dataset` (PROJECT_PLAN.md §O.3).

Keeps only the first 10 of the real committed `clean_data.csv`'s 7043 rows
— well below `_MIN_ROWS_FOR_MODELING` (20). Expected: `MODELING_MIN_ROWS`
(ERROR), plus `INTEGRITY_SHA256_MATCH` (ERROR — the bytes changed).

Runnable two ways:
  * ``pytest tests/failure/test_truncate_dataset.py``
  * ``python tests/failure/test_truncate_dataset.py``
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
from tests.failure._support import copy_real_handoff, findings, mutate_csv_in_place, run_flow_with_handoff  # noqa: E402


def test_truncate_dataset_blocks_crew2() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_crew1_result = copy_real_handoff(tmp_path / "crew1_out")
        mutate_csv_in_place(tmp_path / "crew1_out", fi.truncate_dataset, keep_rows=10)

        state, crew2_calls, report = run_flow_with_handoff(tmp_path, fake_crew1_result)

        assert state.validation_passed is False
        modeling_hits = findings(report, "MODELING_MIN_ROWS")
        assert len(modeling_hits) == 1 and modeling_hits[0].severity == "ERROR"
        assert state.crew2_started is False

        integrity_hits = findings(report, "INTEGRITY_SHA256_MATCH")
        assert len(integrity_hits) == 1 and integrity_hits[0].severity == "ERROR"

        assert state.status == "halted_validation"
        assert crew2_calls["n"] == 0
        assert {"modeling", "integrity"} <= {f.check_family for f in report.findings}


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
