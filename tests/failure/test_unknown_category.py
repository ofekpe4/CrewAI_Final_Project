"""`tests/failure/` — scenario 6/10: `unknown_category` (PROJECT_PLAN.md §O.3).

Two cases, because this is the scenario the Plan explicitly warns against
over-blocking on: `CONSTRAINTS_CLOSED_DOMAIN` must fire ONLY where the
contract actually declares a `closed_domain` for that column.

1. `InternetService` DOES declare a `closed_domain` -> blocking ERROR.
2. `customerID` declares NO `closed_domain` (only `primary_key.unique`) ->
   writing a brand-new, still-unique id into one cell must produce NO
   `CONSTRAINTS_CLOSED_DOMAIN` finding at all — there is nothing declared
   for this mutation to violate. This is the documented, intentional
   non-finding case (§F.1), not a bug.

Runnable two ways:
  * ``pytest tests/failure/test_unknown_category.py``
  * ``python tests/failure/test_unknown_category.py``
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


def test_unknown_category_on_a_declared_closed_domain_blocks_crew2() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_crew1_result = copy_real_handoff(tmp_path / "crew1_out")
        mutate_csv_in_place(
            tmp_path / "crew1_out", fi.unknown_category,
            column="InternetService", new_value="Satellite", row_index=0,
        )

        state, crew2_calls, report = run_flow_with_handoff(tmp_path, fake_crew1_result)

        assert state.validation_passed is False
        hits = findings(report, "CONSTRAINTS_CLOSED_DOMAIN")
        assert any(f.column == "InternetService" and f.severity == "ERROR" for f in hits)
        assert state.crew2_started is False

        assert state.status == "halted_validation"
        assert crew2_calls["n"] == 0
        assert "constraints" in {f.check_family for f in report.findings}


def test_unknown_category_without_a_declared_closed_domain_is_not_a_finding() -> None:
    """The documented non-finding case: `customerID` has no declared
    `closed_domain`, so a new (still-unique) value for it must not trip
    `CONSTRAINTS_CLOSED_DOMAIN` — proving the check is genuinely
    conditional on the contract declaring one, not a blanket "any unseen
    value fails" rule.

    The gate still ends up FAILING this run — but for a completely
    different, expected reason: ANY byte-level CSV edit trips
    `INTEGRITY_SHA256_MATCH` (the contract's hash was computed against the
    original bytes), independent of which column changed or why. That is
    not this scenario's finding to suppress; it is the correct, honest
    behavior of a hash check. The one thing this test exists to prove is
    the ABSENCE of `CONSTRAINTS_CLOSED_DOMAIN` specifically."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_crew1_result = copy_real_handoff(tmp_path / "crew1_out")
        mutate_csv_in_place(
            tmp_path / "crew1_out", fi.unknown_category,
            column="customerID", new_value="NEW-UNSEEN-ID-00001", row_index=0,
        )

        state, crew2_calls, report = run_flow_with_handoff(tmp_path, fake_crew1_result)

        assert not findings(report, "CONSTRAINTS_CLOSED_DOMAIN")
        # primary-key uniqueness is preserved (the new id is still unique),
        # so the ONLY finding is the (expected, unrelated) integrity mismatch
        assert {f.check_family for f in report.findings} == {"integrity"}
        assert state.validation_passed is False
        assert state.crew2_started is False
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
