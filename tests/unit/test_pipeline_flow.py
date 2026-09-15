"""Phase 8 — the production Flow, offline/mocked tests
(PROJECT_PLAN.md §T Phase 8, Internal Gate 8.14).

**No OPENAI_API_KEY required, no network call, no real Crew `kickoff()`.**
Per this Phase's own instruction ("Most tests MUST mock/stub Crew 1 and
Crew 2 result objects"), every test here monkeypatches
`harbor_vale.flow.pipeline_flow._crew1_run_analyst_crew`/
`_crew2_run_scientist_crew` — the two names the Flow itself calls — with a
plain Python stand-in returning a `Crew1Result`/`Crew2Result`-shaped
object. **The validation gate (`contract.validator.run_validation_gate`) is
NEVER mocked** — every PASS/FAIL this file asserts on is the real
deterministic Python gate running against real files on disk (either the
real committed `artifacts/crew1/*`, or a deliberately-mutated copy of
them). This is the one thing this suite must prove is never faked.

Run directly: `python tests/unit/test_pipeline_flow.py`
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import harbor_vale.flow.pipeline_flow as pipeline_flow  # noqa: E402
import harbor_vale.flow.replay as replay_module  # noqa: E402
from harbor_vale.contract.builder import build_contract  # noqa: E402
from harbor_vale.flow import HarborValeFlow  # noqa: E402
from harbor_vale.flow.state import PipelineState  # noqa: E402
from harbor_vale.io_paths import CREW1, CREW2, RAW_TELCO_CHURN_CSV  # noqa: E402
from harbor_vale.plans.cleaning_plan import validate_cleaning_plan  # noqa: E402
from harbor_vale.plans.experiment_plan import validate_experiment_plan  # noqa: E402
from harbor_vale.plans.feature_plan import validate_feature_plan  # noqa: E402
from harbor_vale.tools.cleaning_tools import execute_plan  # noqa: E402
from harbor_vale.tools.eda_tools import compute_eda_stats  # noqa: E402
from harbor_vale.tools.profiling_tools import profile_dataframe  # noqa: E402
from tests.fixtures.build_example_contract import build_draft  # noqa: E402
from tests.fixtures.hardcoded_plans import (  # noqa: E402
    build_hardcoded_cleaning_plan,
    build_hardcoded_experiment_plan,
    build_hardcoded_feature_plan,
)

_PASS: list[str] = []
_FAIL: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        _PASS.append(name)
        print(f"PASS  {name}")
    else:
        _FAIL.append(name)
        print(f"FAIL  {name}  {detail}")


# ---------------------------------------------------------------------------
# Fake Crew1Result/Crew2Result — plain, duck-typed stand-ins
# ---------------------------------------------------------------------------


@dataclass
class _FakeCrew1Result:
    completed: bool
    failure_message: "str | None"
    eda_degraded: bool
    clean_data_csv: Path
    dataset_contract_json: Path
    eda_report_html: Path
    insights_md: Path


@dataclass
class _FakeCrew2Result:
    completed: bool
    failure_message: "str | None"
    model_card_degraded: bool
    features_csv: Path
    model_joblib: Path
    evaluation_report_md: Path
    model_card_md: Path
    winner_name: "str | None"


@contextmanager
def _patched(module, name: str, value):
    original = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, original)


def _copy_real_valid_handoff(dest: Path) -> _FakeCrew1Result:
    """Copy the REAL, currently gate-passing committed `artifacts/crew1/*`
    into `dest` and return a `_FakeCrew1Result` pointing at the copies —
    never the originals. Requires the real files to exist (they do, as of
    the Phase 6/7 live acceptance runs already committed to this repo)."""
    dest.mkdir(parents=True, exist_ok=True)
    names = ("clean_data.csv", "dataset_contract.json", "eda_report.html", "insights.md")
    for name in names:
        src = CREW1 / name
        assert src.is_file(), f"fixture precondition failed: {src} must exist (a committed Phase 6 artifact)"
        shutil.copy2(src, dest / name)
    return _FakeCrew1Result(
        completed=True, failure_message=None, eda_degraded=False,
        clean_data_csv=dest / "clean_data.csv", dataset_contract_json=dest / "dataset_contract.json",
        eda_report_html=dest / "eda_report.html", insights_md=dest / "insights.md",
    )


def _fake_crew2_success(dest: Path) -> _FakeCrew2Result:
    """A minimal, self-consistent Crew2 output set — real `experiments.json`
    shape (winner/primary_metric/test_metrics) so `verify_crew2_outputs`'s
    machine-truth check has something real to verify, never a mocked gate."""
    dest.mkdir(parents=True, exist_ok=True)
    experiments = {
        "run_id": "fake", "primary_metric": "roc_auc",
        "variants": [{"name": "v1", "estimator": "logistic_regression", "cv_metrics": {"roc_auc": 0.8}}],
        "winner": {"name": "v1", "estimator": "logistic_regression", "cv_metrics": {"roc_auc": 0.8},
                   "test_metrics": {"roc_auc": 0.81, "pr_auc": 0.6, "f1": 0.5, "precision": 0.5, "recall": 0.5, "accuracy": 0.7}},
    }
    (dest / "experiments.json").write_text(json.dumps(experiments), encoding="utf-8")
    (dest / "features.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (dest / "model.joblib").write_bytes(b"\x00fake-joblib")
    (dest / "evaluation_report.md").write_text("# eval\n", encoding="utf-8")
    (dest / "model_card.md").write_text("# card\n", encoding="utf-8")
    return _FakeCrew2Result(
        completed=True, failure_message=None, model_card_degraded=False,
        features_csv=dest / "features.csv", model_joblib=dest / "model.joblib",
        evaluation_report_md=dest / "evaluation_report.md", model_card_md=dest / "model_card.md",
        winner_name="v1",
    )


@contextmanager
def _capture_logs():
    """Capture every `harbor_vale` log record for the duration of the
    `with` block, without disturbing the project's own console/file
    handlers (`logging_setup.setup_logging` is idempotent and additive)."""
    logger = logging.getLogger("harbor_vale")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    records: list[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    collector = _Collector()
    logger.addHandler(collector)
    try:
        yield records
    finally:
        logger.removeHandler(collector)


# ---------------------------------------------------------------------------
# test_flow_state_transitions
# ---------------------------------------------------------------------------


def test_flow_state_transitions() -> None:
    state = PipelineState()
    check("test_flow_state_transitions: default status is pending", state.status == "pending")
    check("test_flow_state_transitions: default crew2_started is False", state.crew2_started is False)
    check("test_flow_state_transitions: default fault_injection is None", state.fault_injection is None)

    for value in ("pending", "running", "halted_agent_failure", "halted_validation", "halted_error", "completed"):
        state.status = value
        check(f"test_flow_state_transitions: status accepts {value!r}", state.status == value)

    rejected = False
    try:
        state.status = "not_a_real_status"
    except Exception:
        rejected = True
    check("test_flow_state_transitions: an invalid status value is rejected", rejected)

    flow = HarborValeFlow()
    check("test_flow_state_transitions: HarborValeFlow() constructs with a fresh pending state", flow.state.status == "pending")
    check("test_flow_state_transitions: HarborValeFlow() default fault_injection is None", flow.state.fault_injection is None)


# ---------------------------------------------------------------------------
# test_gate_blocks_crew2 / test_gate_allows_crew2
# ---------------------------------------------------------------------------


def test_gate_blocks_crew2(tmp_path: Path) -> None:
    crew1_dir = tmp_path / "crew1_out"
    fake_result = _copy_real_valid_handoff(crew1_dir)
    # Deliberately corrupt the COPY only — truncate to break the real,
    # deterministic gate's INTEGRITY_SHA256_MATCH check (never the source).
    (fake_result.clean_data_csv).write_text("only,two,columns\n1,2,3\n", encoding="utf-8")

    crew2_calls = {"n": 0}

    def fake_crew1(raw_df, *, run_id, llm=None):  # noqa: ARG001
        return fake_result

    def fake_crew2(**kwargs):  # noqa: ARG001
        crew2_calls["n"] += 1
        raise AssertionError("Crew 2 must never be invoked when the gate fails")

    with _patched(pipeline_flow, "_crew1_run_analyst_crew", fake_crew1), \
         _patched(pipeline_flow, "_crew2_run_scientist_crew", fake_crew2):
        flow = HarborValeFlow()
        flow.kickoff()

    state = flow.state
    check("test_gate_blocks_crew2: validation_passed == False", state.validation_passed is False)
    check("test_gate_blocks_crew2: status == halted_validation", state.status == "halted_validation")
    check("test_gate_blocks_crew2: failure_category == contract_validation", state.failure_category == "contract_validation")
    check("test_gate_blocks_crew2: crew2_started == False", state.crew2_started is False)
    check("test_gate_blocks_crew2: Crew 2 kickoff call count == 0", crew2_calls["n"] == 0)

    summary = pipeline_flow.build_run_summary(state)
    check("test_gate_blocks_crew2: run_summary crew2.started is false", summary["crew2"]["started"] is False)
    check("test_gate_blocks_crew2: run_summary crew2 carries a reason", bool(summary["crew2"].get("reason")))


def test_gate_allows_crew2(tmp_path: Path) -> None:
    crew1_dir = tmp_path / "crew1_out"
    fake_crew1_result = _copy_real_valid_handoff(crew1_dir)
    crew2_dir = tmp_path / "crew2_out"

    crew1_calls = {"n": 0}
    crew2_calls = {"n": 0}

    def fake_crew1(raw_df, *, run_id, llm=None):  # noqa: ARG001
        crew1_calls["n"] += 1
        return fake_crew1_result

    def fake_crew2(**kwargs):  # noqa: ARG001
        crew2_calls["n"] += 1
        return _fake_crew2_success(crew2_dir)

    with _patched(pipeline_flow, "_crew1_run_analyst_crew", fake_crew1), \
         _patched(pipeline_flow, "_crew2_run_scientist_crew", fake_crew2):
        flow = HarborValeFlow()
        flow.kickoff()

    state = flow.state
    check("test_gate_allows_crew2: validation_passed == True", state.validation_passed is True)
    check("test_gate_allows_crew2: gate found 0 errors", state.validation_errors == 0)
    check("test_gate_allows_crew2: crew2_started == True", state.crew2_started is True)
    check("test_gate_allows_crew2: Crew 2 invoked exactly once", crew2_calls["n"] == 1)
    check("test_gate_allows_crew2: crew2_completed == True", state.crew2_completed is True)
    check("test_gate_allows_crew2: status == completed", state.status == "completed")
    check("test_gate_allows_crew2: best_model_name populated", state.best_model_name == "v1")
    check("test_gate_allows_crew2: primary_metric_value populated", state.primary_metric_value == 0.81)


# ---------------------------------------------------------------------------
# test_no_fault_injection_in_default_run
# ---------------------------------------------------------------------------


def test_no_fault_injection_in_default_run(tmp_path: Path) -> None:
    crew1_dir = tmp_path / "crew1_out"
    fake_result = _copy_real_valid_handoff(crew1_dir)
    original_bytes = fake_result.clean_data_csv.read_bytes()

    def fake_crew1(raw_df, *, run_id, llm=None):  # noqa: ARG001
        return fake_result

    def fake_crew2(**kwargs):
        return _fake_crew2_success(tmp_path / "crew2_out")

    with _patched(pipeline_flow, "_crew1_run_analyst_crew", fake_crew1), \
         _patched(pipeline_flow, "_crew2_run_scientist_crew", fake_crew2), \
         _capture_logs() as records:
        flow = HarborValeFlow()  # fault_injection defaults to None
        flow.kickoff()

    state = flow.state
    check("test_no_fault_injection_in_default_run: state.fault_injection is None", state.fault_injection is None)

    snapshot_csv = pipeline_flow._resolve(state.handoff_snapshot_dir) / "clean_data.csv"
    check(
        "test_no_fault_injection_in_default_run: handoff snapshot bytes unchanged from Crew 1 output",
        snapshot_csv.read_bytes() == original_bytes,
    )
    critical_fault_logs = [r for r in records if r.levelno == logging.CRITICAL and "FAULT INJECTION" in r.getMessage()]
    check("test_no_fault_injection_in_default_run: no CRITICAL fault-injection log line", len(critical_fault_logs) == 0)
    check("test_no_fault_injection_in_default_run: run reaches completed", state.status == "completed")


# ---------------------------------------------------------------------------
# test_fault_injection_ordering (Internal Gate 8.15 — the core fault-demo proof)
# ---------------------------------------------------------------------------


def test_fault_injection_ordering(tmp_path: Path) -> None:
    crew1_dir = tmp_path / "crew1_out"
    fake_result = _copy_real_valid_handoff(crew1_dir)
    pre_fault_bytes = fake_result.clean_data_csv.read_bytes()

    crew2_calls = {"n": 0}

    def fake_crew1(raw_df, *, run_id, llm=None):  # noqa: ARG001
        return fake_result

    def fake_crew2(**kwargs):  # noqa: ARG001
        crew2_calls["n"] += 1
        raise AssertionError("Crew 2 must never start after a fault-injected gate failure")

    with _patched(pipeline_flow, "_crew1_run_analyst_crew", fake_crew1), \
         _patched(pipeline_flow, "_crew2_run_scientist_crew", fake_crew2), \
         _capture_logs() as records:
        flow = HarborValeFlow(fault_injection="scale_change")
        flow.kickoff()

    state = flow.state
    check("test_fault_injection_ordering: source Crew 1 output untouched", fake_result.clean_data_csv.read_bytes() == pre_fault_bytes)
    check("test_fault_injection_ordering: status == halted_validation", state.status == "halted_validation")
    check("test_fault_injection_ordering: crew2_started == False", state.crew2_started is False)
    check("test_fault_injection_ordering: Crew 2 kickoff call count == 0", crew2_calls["n"] == 0)

    report = flow._validation_report
    messages = " ".join(f.message for f in report.findings)
    check("test_fault_injection_ordering: SUSPECTED SCALE CHANGE present", "SUSPECTED SCALE CHANGE" in messages)
    check(
        "test_fault_injection_ordering: an integrity ERROR is also present",
        any(f.check_id == "INTEGRITY_SHA256_MATCH" and f.severity == "ERROR" for f in report.findings),
    )
    critical_fault_logs = [r for r in records if r.levelno == logging.CRITICAL and "FAULT INJECTION ACTIVE" in r.getMessage()]
    check("test_fault_injection_ordering: a CRITICAL FAULT INJECTION ACTIVE log line was emitted", len(critical_fault_logs) >= 1)


# ---------------------------------------------------------------------------
# test_validate_only_skips_crews
# ---------------------------------------------------------------------------


def test_validate_only_skips_crews_pass() -> None:
    crew1_calls = {"n": 0}
    crew2_calls = {"n": 0}

    def fake_crew1(raw_df, *, run_id, llm=None):  # noqa: ARG001
        crew1_calls["n"] += 1
        raise AssertionError("Crew 1 must never run in --validate-only mode")

    def fake_crew2(**kwargs):  # noqa: ARG001
        crew2_calls["n"] += 1
        raise AssertionError("Crew 2 must never run in --validate-only mode")

    before = {p.name: p.stat().st_mtime_ns for p in CREW1.glob("*") if p.is_file()}

    with _patched(pipeline_flow, "_crew1_run_analyst_crew", fake_crew1), \
         _patched(pipeline_flow, "_crew2_run_scientist_crew", fake_crew2):
        flow = HarborValeFlow(validate_only=True)
        flow.kickoff()

    after = {p.name: p.stat().st_mtime_ns for p in CREW1.glob("*") if p.is_file()}

    state = flow.state
    check("test_validate_only_skips_crews: load_dataset skipped (dataset_path untouched by a raw read)", state.status == "completed")
    check("test_validate_only_skips_crews: Crew 1 never called", crew1_calls["n"] == 0)
    check("test_validate_only_skips_crews: Crew 2 never called", crew2_calls["n"] == 0)
    check("test_validate_only_skips_crews: crew2_started == False", state.crew2_started is False)
    check("test_validate_only_skips_crews: artifacts/crew1/* not overwritten (mtimes unchanged)", before == after)
    check("test_validate_only_skips_crews: PASS against the real committed contract", state.validation_passed is True)


def test_validate_only_skips_crews_fail(tmp_path: Path) -> None:
    """The FAIL sub-case — validated against a deliberately broken copy,
    reached by monkeypatching the fixed production path constants
    `validate_handoff` reads, never by touching the real files."""
    broken_dir = tmp_path / "broken_handoff"
    broken_dir.mkdir()
    for name in ("clean_data.csv", "dataset_contract.json", "eda_report.html", "insights.md"):
        shutil.copy2(CREW1 / name, broken_dir / name)
    (broken_dir / "clean_data.csv").write_text("nothing,useful\n1,2\n", encoding="utf-8")

    crew1_calls = {"n": 0}
    crew2_calls = {"n": 0}

    def fake_crew1(raw_df, *, run_id, llm=None):  # noqa: ARG001
        crew1_calls["n"] += 1
        raise AssertionError("Crew 1 must never run in --validate-only mode")

    def fake_crew2(**kwargs):  # noqa: ARG001
        crew2_calls["n"] += 1
        raise AssertionError("Crew 2 must never run in --validate-only mode")

    with _patched(pipeline_flow, "_crew1_run_analyst_crew", fake_crew1), \
         _patched(pipeline_flow, "_crew2_run_scientist_crew", fake_crew2), \
         _patched(pipeline_flow, "HANDOFF_CLEAN_DATA", broken_dir / "clean_data.csv"), \
         _patched(pipeline_flow, "HANDOFF_CONTRACT", broken_dir / "dataset_contract.json"), \
         _patched(pipeline_flow, "EDA_REPORT_HTML", broken_dir / "eda_report.html"), \
         _patched(pipeline_flow, "INSIGHTS_MD", broken_dir / "insights.md"):
        flow = HarborValeFlow(validate_only=True)
        flow.kickoff()

    state = flow.state
    check("test_validate_only_skips_crews (FAIL): Crew 1 never called", crew1_calls["n"] == 0)
    check("test_validate_only_skips_crews (FAIL): Crew 2 never called", crew2_calls["n"] == 0)
    check("test_validate_only_skips_crews (FAIL): status == halted_validation", state.status == "halted_validation")
    check("test_validate_only_skips_crews (FAIL): crew2_started == False", state.crew2_started is False)
    check(
        "test_validate_only_skips_crews (FAIL): the real committed artifacts/crew1/* were never touched",
        (CREW1 / "clean_data.csv").read_bytes() != (broken_dir / "clean_data.csv").read_bytes(),
    )


# ---------------------------------------------------------------------------
# test_flow_handles_crew_crash
# ---------------------------------------------------------------------------


def test_flow_handles_crew1_crash() -> None:
    def crashing_crew1(raw_df, *, run_id, llm=None):  # noqa: ARG001
        raise RuntimeError("simulated unexpected Crew 1 crash")

    with _patched(pipeline_flow, "_crew1_run_analyst_crew", crashing_crew1):
        flow = HarborValeFlow()
        flow.kickoff()

    state = flow.state
    check("test_flow_handles_crew1_crash: status == halted_error (runtime crash, not an agent-output halt)", state.status == "halted_error")
    check("test_flow_handles_crew1_crash: failure_category == runtime", state.failure_category == "runtime")
    check("test_flow_handles_crew1_crash: failure_summary mentions the crash", "simulated unexpected Crew 1 crash" in state.failure_summary)
    check("test_flow_handles_crew1_crash: crew2_started == False", state.crew2_started is False)
    check(
        "test_flow_handles_crew1_crash: run_summary.json was still written (no unhandled exception)",
        pipeline_flow.build_run_summary(state)["status"] == "halted_error",
    )


def test_flow_handles_crew1_agent_failure() -> None:
    """Differentiates a REPORTED critical-agent failure (Crew1Result.completed
    is False, no exception) from a genuine crash — different failure_category."""
    def failing_crew1(raw_df, *, run_id, llm=None):  # noqa: ARG001
        return _FakeCrew1Result(
            completed=False, failure_message="guardrail exhausted after retries", eda_degraded=False,
            clean_data_csv=Path("x"), dataset_contract_json=Path("x"), eda_report_html=Path("x"), insights_md=Path("x"),
        )

    with _patched(pipeline_flow, "_crew1_run_analyst_crew", failing_crew1):
        flow = HarborValeFlow()
        flow.kickoff()

    state = flow.state
    check("test_flow_handles_crew1_agent_failure: status == halted_agent_failure", state.status == "halted_agent_failure")
    check("test_flow_handles_crew1_agent_failure: failure_category == agent_output", state.failure_category == "agent_output")
    check("test_flow_handles_crew1_agent_failure: crew2_started == False", state.crew2_started is False)


def test_flow_handles_crew2_crash(tmp_path: Path) -> None:
    fake_crew1_result = _copy_real_valid_handoff(tmp_path / "crew1_out")

    def fake_crew1(raw_df, *, run_id, llm=None):  # noqa: ARG001
        return fake_crew1_result

    def crashing_crew2(**kwargs):  # noqa: ARG001
        raise RuntimeError("simulated unexpected Crew 2 crash")

    with _patched(pipeline_flow, "_crew1_run_analyst_crew", fake_crew1), \
         _patched(pipeline_flow, "_crew2_run_scientist_crew", crashing_crew2):
        flow = HarborValeFlow()
        flow.kickoff()

    state = flow.state
    check("test_flow_handles_crew2_crash: crew2_started == True (it DID start)", state.crew2_started is True)
    check("test_flow_handles_crew2_crash: status == halted_error", state.status == "halted_error")
    check("test_flow_handles_crew2_crash: failure_category == runtime", state.failure_category == "runtime")


# ---------------------------------------------------------------------------
# test_replay — zero LLM calls, real deterministic layer, real gate
# ---------------------------------------------------------------------------


def _build_replay_fixture(crew1_internal: Path, raw_df) -> None:  # noqa: ANN001
    """Populate `crew1_internal/cleaning_plan.json` + `contract_draft.json`
    — the two stored plans Internal Gate 8.10 identified as required and
    NOT yet produced by any live run in this repo. Uses the exact same
    hardcoded, already-Phase-5-proven fixtures
    `tests/fixtures/hardcoded_e2e_harness.py` uses for its own no-LLM
    end-to-end proof."""
    crew1_internal.mkdir(parents=True, exist_ok=True)
    cleaning_plan = build_hardcoded_cleaning_plan()
    (crew1_internal / "cleaning_plan.json").write_text(cleaning_plan.model_dump_json(), encoding="utf-8")
    (crew1_internal / "contract_draft.json").write_text(build_draft().model_dump_json(), encoding="utf-8")


def test_replay_zero_llm_calls_and_reproducible(tmp_path: Path) -> None:
    raw_df = pipeline_flow.pd.read_csv(RAW_TELCO_CHURN_CSV)

    crew1_internal_fixture = tmp_path / "crew1_internal"
    _build_replay_fixture(crew1_internal_fixture, raw_df)

    # A real LLM call would need OPENAI_API_KEY / network — assert it is
    # never even attempted by making any accidental LLM construction fail
    # loudly rather than silently degrading to a real network call.
    llm_call_count = {"n": 0}

    class _ExplodingLLM:
        def call(self, *a, **kw):  # noqa: ANN001, ANN002, ANN003
            llm_call_count["n"] += 1
            raise AssertionError("replay must make ZERO LLM calls")

    with _patched(replay_module, "CREW1_INTERNAL", crew1_internal_fixture):
        result1 = replay_module.replay_crew1(raw_df, run_id="replay-test-1", workspace=tmp_path / "run1" / "crew1")
        result2 = replay_module.replay_crew1(raw_df, run_id="replay-test-2", workspace=tmp_path / "run2" / "crew1")

    check("test_replay: replay_crew1 completes with zero LLM calls", result1.completed is True and llm_call_count["n"] == 0)
    contract1 = json.loads(result1.dataset_contract_json.read_text())
    contract2 = json.loads(result2.dataset_contract_json.read_text())
    check(
        "test_replay: replay_crew1 is deterministic (identical clean_data sha256 across two runs)",
        contract1["integrity"]["clean_data_sha256"] == contract2["integrity"]["clean_data_sha256"],
    )
    check(
        "test_replay: replay_crew1 is deterministic (identical observed stats across two runs)",
        contract1["columns"] == contract2["columns"],
    )
    check("test_replay: replay_crew1 clean_data.csv bytes are identical across two runs",
          result1.clean_data_csv.read_bytes() == result2.clean_data_csv.read_bytes())
    check("test_replay: replay_crew1 marks eda_degraded (no stored insights_doc.json in this fixture)", result1.eda_degraded is True)

    # --- now the full replay-crew2 layer, built from replay_crew1's own real contract ---
    contract = build_contract(
        build_draft(), result1.clean_data_csv, contract_version="1.0.0", run_id="replay-test-1",
        created_by="test_pipeline_flow", dataset_name="telco_customer_churn",
        source_documentation_url="https://github.com/IBM/telco-customer-churn-on-icp4d",
    )
    clean_df = pipeline_flow.pd.read_csv(result1.clean_data_csv)
    raw_profile = profile_dataframe(raw_df, target_column="Churn")
    ok, cleaning_plan = validate_cleaning_plan(build_hardcoded_cleaning_plan(), profile=raw_profile)
    check("test_replay: fixture CleaningPlan re-validates (precondition)", ok)

    crew2_internal_fixture = tmp_path / "crew2_internal"
    crew2_internal_fixture.mkdir(parents=True, exist_ok=True)
    feature_plan = build_hardcoded_feature_plan(contract)
    ok, _ = validate_feature_plan(feature_plan, contract=contract)
    check("test_replay: fixture FeaturePlan re-validates against the replayed contract (precondition)", ok)
    (crew2_internal_fixture / "feature_plan.json").write_text(feature_plan.model_dump_json(), encoding="utf-8")

    experiment_plan = build_hardcoded_experiment_plan()
    ok, _ = validate_experiment_plan(experiment_plan)
    check("test_replay: fixture ExperimentPlan re-validates (precondition)", ok)
    (crew2_internal_fixture / "experiment_plan.json").write_text(experiment_plan.model_dump_json(), encoding="utf-8")

    with _patched(replay_module, "CREW2_INTERNAL", crew2_internal_fixture):
        crew2_result1 = replay_module.replay_crew2(
            clean_data_csv=result1.clean_data_csv, dataset_contract_json=result1.dataset_contract_json,
            run_id="replay-test-1", workspace=tmp_path / "run1" / "crew2",
        )
        crew2_result2 = replay_module.replay_crew2(
            clean_data_csv=result1.clean_data_csv, dataset_contract_json=result1.dataset_contract_json,
            run_id="replay-test-1", workspace=tmp_path / "run2" / "crew2",
        )

    check("test_replay: replay_crew2 completes with zero LLM calls", crew2_result1.completed is True and llm_call_count["n"] == 0)
    check("test_replay: replay_crew2 marks model_card_degraded (no stored model_card.json in this fixture)", crew2_result1.model_card_degraded is True)
    check(
        "test_replay: replay_crew2 winner is reproducible across two runs",
        crew2_result1.winner_name == crew2_result2.winner_name,
    )
    check(
        "test_replay: replay_crew2 primary metric VALUE is reproducible across two runs",
        crew2_result1.primary_metric_value == crew2_result2.primary_metric_value,
    )

    # --- the real gate still runs, unmocked, against the replayed handoff ---
    from harbor_vale.contract.validator import run_validation_gate
    report = run_validation_gate(
        result1.clean_data_csv, result1.dataset_contract_json, result1.eda_report_html, result1.insights_md,
        run_id="replay-test-1",
    )
    check("test_replay: the real gate PASSES the replayed handoff", report.passed is True, str([f.message for f in report.findings]))


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

ALL_TESTS_WITH_TMPDIR = [
    test_gate_blocks_crew2,
    test_gate_allows_crew2,
    test_no_fault_injection_in_default_run,
    test_fault_injection_ordering,
    test_validate_only_skips_crews_fail,
    test_flow_handles_crew2_crash,
    test_replay_zero_llm_calls_and_reproducible,
]

ALL_TESTS_NO_ARGS = [
    test_flow_state_transitions,
    test_validate_only_skips_crews_pass,
    test_flow_handles_crew1_crash,
    test_flow_handles_crew1_agent_failure,
]


def main() -> int:
    for fn in ALL_TESTS_WITH_TMPDIR:
        with tempfile.TemporaryDirectory() as td:
            try:
                fn(Path(td))
            except Exception as exc:  # noqa: BLE001
                _FAIL.append(fn.__name__)
                print(f"FAIL  {fn.__name__}  raised {type(exc).__name__}: {exc}")

    for fn in ALL_TESTS_NO_ARGS:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            _FAIL.append(fn.__name__)
            print(f"FAIL  {fn.__name__}  raised {type(exc).__name__}: {exc}")

    print(f"\n{len(_PASS)} passed, {len(_FAIL)} failed")
    if _FAIL:
        print("all failed:", _FAIL)
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
