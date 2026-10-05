"""`tests/failure/` — scenario 1/10: `scale_change` (PROJECT_PLAN.md §O.3 ⭐
MANDATORY, Phase 10 Internal Gate 10.1).

**The central demonstration of the whole project.** Reproduces the Harbor &
Vale incident end to end through the REAL Flow, using the REAL injection
point (`HarborValeFlow(fault_injection="scale_change")` —
`inject_fault_if_requested`, §P.1 mechanism 1): Crew 1 completes -> its
final `clean_data.csv`/`dataset_contract.json` are written -> the Flow
builds its run-scoped handoff snapshot -> fault injection mutates ONLY that
snapshot's `MonthlyCharges` column (x100, dtype unchanged) -> the real
deterministic gate runs -> `gate_router` emits `"gate_failed"` -> Crew 2 is
structurally unreachable.

Crew 1 is mocked (zero LLM calls) to return the REAL, currently
gate-passing committed `artifacts/crew1/*` **unmutated** — the Flow itself
performs the mutation, on its own run-scoped copy, never on the source.
Crew 2 is mocked to raise if ever called. The validation gate itself runs
for real, unmocked.

Runnable two ways:
  * ``pytest tests/failure/test_scale_change.py``
  * ``python tests/failure/test_scale_change.py``
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale.flow.pipeline_flow import FAULT_SCALE_COLUMN, build_run_summary  # noqa: E402
from tests.failure._support import copy_real_handoff, findings, run_flow_with_fault_injection  # noqa: E402


def test_scale_change_blocks_crew2_end_to_end() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_crew1_result = copy_real_handoff(tmp_path / "crew1_out")
        pre_fault_bytes = fake_crew1_result.clean_data_csv.read_bytes()

        state, crew2_calls, report = run_flow_with_fault_injection(
            tmp_path, fake_crew1_result, fault_injection="scale_change"
        )

        # 0. the mutation target is the real, live-verified scale-sensitive column
        assert FAULT_SCALE_COLUMN == "MonthlyCharges"

        # 1. the source Crew 1 output (the real committed artifacts/crew1/*, via
        #    the tmp copy standing in for them) was never touched — only the
        #    Flow's own run-scoped snapshot was mutated.
        assert fake_crew1_result.clean_data_csv.read_bytes() == pre_fault_bytes

        # 2. §O.3's three mandatory assertions
        assert state.validation_passed is False
        scale_hits = findings(report, "SCALE_DRIFT_MEDIAN")
        assert len(scale_hits) == 1
        assert state.crew2_started is False

        # 3. Internal Gate 10.1's exact required wording + ratio
        finding = scale_hits[0]
        assert finding.severity == "ERROR"
        assert finding.column == "MonthlyCharges"
        assert "SUSPECTED SCALE CHANGE" in finding.message
        ratio = finding.observed / finding.expected
        assert abs(ratio - 100.0) / 100.0 < 0.05, f"expected an ~100x ratio, got {ratio}"

        # 4. integrity mismatch is ALSO reported (the bytes changed)
        integrity_hits = findings(report, "INTEGRITY_SHA256_MATCH")
        assert len(integrity_hits) == 1 and integrity_hits[0].severity == "ERROR"

        # 5. terminal state (Internal Gate 10.1's exact required fields)
        assert state.status == "halted_validation"
        assert state.failure_category == "contract_validation"

        # 6. Crew 2 kickoff call count == 0 (not merely "never completed" — never CALLED)
        assert crew2_calls["n"] == 0

        # 7. zero Crew 2 artifacts created FOR THIS RUN (Internal Gate 10.8 — this
        #    is a fresh tmp_path; nothing here could be a stale prior-run leftover)
        crew2_out = tmp_path / "crew2_out"
        assert not crew2_out.exists()

        # 8. run_summary.json's own shape carries the same story
        summary = build_run_summary(state)
        assert summary["status"] == "halted_validation"
        assert summary["failure_category"] == "contract_validation"
        assert summary["fault_injection"] == "scale_change"
        assert summary["crew2"]["started"] is False
        assert bool(summary["crew2"].get("reason"))

        # 9. epistemic honesty (§P.3) — no fabricated currency claim
        assert "USD" not in finding.message and "cents" not in finding.message.lower()


def test_scale_change_still_runs_every_other_check_family() -> None:
    """The gate does not stop at the first failure — it keeps evaluating
    every other family, so a real incident report shows the complete
    picture, not just the first symptom (§F.2)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_crew1_result = copy_real_handoff(tmp_path / "crew1_out")
        _state, _calls, report = run_flow_with_fault_injection(
            tmp_path, fake_crew1_result, fault_injection="scale_change"
        )
    assert report.checks_run >= 60
    families_with_findings = {f.check_family for f in report.findings}
    # scale_drift + integrity are the two families THIS mutation targets;
    # the real production contract also declares a business_range on
    # MonthlyCharges, so a x100 shift legitimately trips `constraints` too
    # (18.25-118.75 vs. ~7035) — a real, honest side effect of the
    # mutation, not something this test should hide by using a weaker
    # contract. The two targeted families must be present; nothing outside
    # the known "a 100x shift on a bounded currency column" blast radius is.
    assert {"scale_drift", "integrity"} <= families_with_findings
    assert families_with_findings <= {"scale_drift", "integrity", "constraints"}


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
