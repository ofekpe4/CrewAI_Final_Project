"""Shared Phase 4 (validation gate) test fixtures.

Not a test file itself — imported by `tests/unit/test_validator_*.py` and
`tests/unit/test_fault_injection.py` so each of those files does not have to
re-derive "how do I get a real, on-disk contract + CSV pair" on its own.

Everything here is built from the already-committed Phase 3 fixtures
(`telco_contract_fixture.csv`, `build_example_contract.py`) — never a
hand-typed JSON blob standing in for a real contract, and never the
production `clean_data.csv` (which does not exist until Phase 5+/6+).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale.contract.builder import build_contract  # noqa: E402
from harbor_vale.contract.schema import TargetDriftConstraint  # noqa: E402
from harbor_vale.plans.contract_draft import validate_contract_draft  # noqa: E402
from tests.fixtures.build_example_contract import build_draft  # noqa: E402

FIXTURE_CSV: Path = _ROOT / "tests" / "fixtures" / "telco_contract_fixture.csv"
CONTRACT_JSON: Path = _ROOT / "tests" / "fixtures" / "contract_example.json"

assert FIXTURE_CSV.is_file(), "the Phase 3 fixture CSV must exist on disk"
assert CONTRACT_JSON.is_file(), (
    "tests/fixtures/contract_example.json must exist — regenerate with "
    "`python tests/fixtures/build_example_contract.py` if missing"
)


def _validated_draft():
    ok, draft = validate_contract_draft(build_draft())
    assert ok, f"fixture draft should be valid: {draft}"
    return draft


def build_contract_json(tmp_path: Path, *, with_target_drift: bool = False, filename: str = "contract.json") -> Path:
    """Build a fresh `DatasetContract` from the Phase 3 fixture draft + CSV,
    optionally with a `target.drift` policy attached (the checked-in
    `contract_example.json` deliberately has none — §D.3's example target
    drift declaration is illustrative, not mandatory — so tests that need to
    exercise `TARGET_POSITIVE_RATE_DRIFT` build this variant instead of
    mutating the shared Phase 3 fixture file).

    Writes the contract JSON to `tmp_path / filename` and returns that path.
    """
    draft = _validated_draft()
    if with_target_drift:
        drifting_target = draft.target.model_copy(
            update={
                "drift": TargetDriftConstraint(
                    positive_rate_tolerance_abs=0.05,
                    justification="a large shift in base rate implies the label's meaning changed",
                )
            }
        )
        draft = draft.model_copy(update={"target": drifting_target})

    contract = build_contract(
        draft, FIXTURE_CSV,
        contract_version="1.0.0", run_id="gate-fixture-run", created_by="tests.fixtures.gate_fixtures",
        dataset_name="telco_customer_churn",
        source_documentation_url="https://github.com/IBM/telco-customer-churn-on-icp4d",
    )
    out_path = tmp_path / filename
    out_path.write_text(contract.model_dump_json(indent=2), encoding="utf-8")
    return out_path
