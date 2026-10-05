"""`tests/failure/` — scenario 4/10: `change_dtype` (PROJECT_PLAN.md §O.3).

`MonthlyCharges` (declared `expected: float64`) is cast to `int64`.
Expected: `SCHEMA_DTYPE_COMPATIBLE` (ERROR — floating and integer are
genuinely different logical families, §F.1). Casting to `str` instead
would not survive the CSV round-trip: numeric-looking strings get
re-inferred back to `float64` by `pandas.read_csv`, which is exactly why
`tests/unit/test_validator_schema.py` uses `int64` for this same proof.

Runnable two ways:
  * ``pytest tests/failure/test_change_dtype.py``
  * ``python tests/failure/test_change_dtype.py``
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


def test_change_dtype_blocks_crew2() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_crew1_result = copy_real_handoff(tmp_path / "crew1_out")
        mutate_csv_in_place(tmp_path / "crew1_out", fi.change_dtype, column="MonthlyCharges", dtype="int64")

        state, crew2_calls, report = run_flow_with_handoff(tmp_path, fake_crew1_result)

        assert state.validation_passed is False
        dtype_hits = findings(report, "SCHEMA_DTYPE_COMPATIBLE")
        assert any(f.column == "MonthlyCharges" and f.severity == "ERROR" for f in dtype_hits)
        assert state.crew2_started is False

        assert state.status == "halted_validation"
        assert crew2_calls["n"] == 0
        assert "schema" in {f.check_family for f in report.findings}


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
