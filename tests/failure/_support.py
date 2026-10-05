"""Shared helpers for `tests/failure/*` (PROJECT_PLAN.md §O.3, §P, Phase 10).

**Not a test file itself.** Every scenario test in this directory proves the
same thing §O.3 requires for a blocking failure — `passed is False`, the
expected check family present in `ValidationReport.findings`, and
`state.crew2_started is False` — by running the REAL `HarborValeFlow`
(never re-implementing the gate's PASS/FAIL decision), with Crew 1 and
Crew 2 mocked exactly the way `tests/unit/test_pipeline_flow.py` already
does. **Zero LLM calls, zero `OPENAI_API_KEY`, zero network`, zero writes to
the real `artifacts/crew1/*`/`artifacts/crew2/*` trees** — every mutation
happens on a `tmp_path` copy.

Two ways to get a starting (unmutated) four-file handoff:

- :func:`copy_real_handoff` — the REAL, currently gate-passing committed
  `artifacts/crew1/*` (the live Phase 6/7/8 acceptance run). Used by every
  scenario whose target column/contract shape already exists there.
- :func:`build_fixture_handoff` — the Phase 3/4 synthetic fixture
  (`tests/fixtures/gate_fixtures.py`), optionally with a `target.drift`
  policy attached. Used only where the real committed contract does not
  declare something a scenario needs (`target.drift` for
  `flip_target_encoding`; an unreferenced, non-required column for
  `contract_only_change` — the real contract's `required_features` lists
  every non-key, non-target column, so no such column exists there).

Every fault_injection.py helper refuses to write back onto its own source
(`FaultInjectionError`) — :func:`mutate_csv_in_place`/
:func:`mutate_contract_in_place` honour that by mutating into a sibling
`*.faulted` file and then `Path.replace`-ing it over the copy, exactly the
two-step dance `pipeline_flow.inject_fault_if_requested` itself uses.
"""

from __future__ import annotations

import json
import shutil
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import harbor_vale.flow.pipeline_flow as pipeline_flow  # noqa: E402
from harbor_vale.contract.validator import ValidationReport  # noqa: E402
from harbor_vale.demo import fault_injection as fi  # noqa: E402
from harbor_vale.flow import HarborValeFlow  # noqa: E402
from harbor_vale.flow.state import PipelineState  # noqa: E402
from harbor_vale.io_paths import CREW1  # noqa: E402
from tests.fixtures.gate_fixtures import (  # noqa: E402
    EDA_REPORT_FIXTURE,
    INSIGHTS_MD_FIXTURE,
    build_contract_json,
)
from tests.fixtures.gate_fixtures import FIXTURE_CSV as _FIXTURE_CSV  # noqa: E402


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
def patched(module, name: str, value):  # noqa: ANN001
    original = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, original)


# ---------------------------------------------------------------------------
# Building an (unmutated) four-file handoff copy in a tmp directory
# ---------------------------------------------------------------------------


def copy_real_handoff(dest: Path) -> _FakeCrew1Result:
    """Copy the REAL, currently gate-passing committed `artifacts/crew1/*`
    into `dest` — never the originals. Requires those four files to exist
    (they do: the committed Phase 6/7/8 live-acceptance run)."""
    dest.mkdir(parents=True, exist_ok=True)
    names = ("clean_data.csv", "dataset_contract.json", "eda_report.html", "insights.md")
    for name in names:
        src = CREW1 / name
        assert src.is_file(), f"precondition failed: {src} must exist (a committed live-run artifact)"
        shutil.copy2(src, dest / name)
    return _FakeCrew1Result(
        completed=True, failure_message=None, eda_degraded=False,
        clean_data_csv=dest / "clean_data.csv", dataset_contract_json=dest / "dataset_contract.json",
        eda_report_html=dest / "eda_report.html", insights_md=dest / "insights.md",
    )


def build_fixture_handoff(dest: Path, *, with_target_drift: bool = False) -> _FakeCrew1Result:
    """Copy the Phase 3/4 synthetic fixture (`tests/fixtures/gate_fixtures.py`)
    into `dest`, optionally attaching a `target.drift` policy the real
    committed production contract does not declare."""
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_FIXTURE_CSV, dest / "clean_data.csv")
    built = build_contract_json(dest, with_target_drift=with_target_drift, filename="dataset_contract.json")
    assert built == dest / "dataset_contract.json"
    shutil.copy2(EDA_REPORT_FIXTURE, dest / "eda_report.html")
    shutil.copy2(INSIGHTS_MD_FIXTURE, dest / "insights.md")
    return _FakeCrew1Result(
        completed=True, failure_message=None, eda_degraded=False,
        clean_data_csv=dest / "clean_data.csv", dataset_contract_json=dest / "dataset_contract.json",
        eda_report_html=dest / "eda_report.html", insights_md=dest / "insights.md",
    )


# ---------------------------------------------------------------------------
# Mutating exactly one file of a copied handoff, in place
# ---------------------------------------------------------------------------


def mutate_csv_in_place(dest_dir: Path, fi_fn: Callable, **kwargs) -> None:  # noqa: ANN001
    """Apply a `demo/fault_injection.py` helper to `dest_dir/clean_data.csv`,
    in place — never touching any other file in `dest_dir`."""
    csv_path = dest_dir / "clean_data.csv"
    tmp_path = dest_dir / "clean_data.csv.faulted"
    fi_fn(csv_path, tmp_path, **kwargs)
    tmp_path.replace(csv_path)


def mutate_contract_in_place(dest_dir: Path, fi_fn: Callable, **kwargs) -> None:  # noqa: ANN001
    """Apply a `demo/fault_injection.py` helper to
    `dest_dir/dataset_contract.json`, in place — never touching any other
    file in `dest_dir`."""
    contract_path = dest_dir / "dataset_contract.json"
    tmp_path = dest_dir / "dataset_contract.json.faulted"
    fi_fn(contract_path, tmp_path, **kwargs)
    tmp_path.replace(contract_path)


# ---------------------------------------------------------------------------
# A minimal, self-consistent Crew 2 success stand-in (for the one scenario
# that must prove CONTINUATION, not blocking: contract_only_change).
# ---------------------------------------------------------------------------


def fake_crew2_success(dest: Path) -> _FakeCrew2Result:
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


# ---------------------------------------------------------------------------
# The one entrypoint every scenario test calls
# ---------------------------------------------------------------------------


def run_flow_with_handoff(
    tmp_path: Path,
    fake_crew1_result: _FakeCrew1Result,
    *,
    expect_crew2_runs: bool = False,
) -> tuple[PipelineState, dict, "ValidationReport | None"]:
    """Run the REAL `HarborValeFlow` end to end with Crew 1 mocked to return
    `fake_crew1_result` (already pointing at a mutated or unmutated tmp-dir
    copy) and Crew 2 mocked to either:

    - refuse to run at all (default) — raises `AssertionError` from inside
      the mock if ever called, so a bug that lets Crew 2 start on a FAILED
      gate fails the test loudly, not silently; or
    - (``expect_crew2_runs=True``) succeed exactly once — for the one
      non-blocking, WARN-only scenario (`contract_only_change`) that must
      prove the gate does NOT block every contract change.

    Returns `(state, crew2_calls, validation_report)` — `crew2_calls["n"]`
    is the real call count the §O.3/Phase 10 acceptance criteria ask for.
    The validation gate itself is NEVER mocked.
    """
    crew2_calls = {"n": 0}

    def fake_crew1(raw_df, *, run_id, llm=None):  # noqa: ARG001
        return fake_crew1_result

    if expect_crew2_runs:
        crew2_dir = tmp_path / "crew2_out"

        def fake_crew2(**kwargs):  # noqa: ARG001
            crew2_calls["n"] += 1
            return fake_crew2_success(crew2_dir)
    else:

        def fake_crew2(**kwargs):  # noqa: ARG001
            crew2_calls["n"] += 1
            raise AssertionError("Crew 2 must never be invoked when the gate fails")

    with patched(pipeline_flow, "_crew1_run_analyst_crew", fake_crew1), \
         patched(pipeline_flow, "_crew2_run_scientist_crew", fake_crew2):
        flow = HarborValeFlow()
        flow.kickoff()

    return flow.state, crew2_calls, flow._validation_report


def findings(report: "ValidationReport", check_id: str) -> list:
    return [f for f in report.findings if f.check_id == check_id]


def run_flow_with_fault_injection(
    tmp_path: Path,
    fake_crew1_result: _FakeCrew1Result,
    fault_injection: str,
) -> tuple[PipelineState, dict, "ValidationReport | None"]:
    """The OTHER entrypoint (Internal Gate 10.1): exercises the Flow's OWN
    `--inject-failure`/`HarborValeFlow(fault_injection=...)` mechanism — the
    ONE injection point `inject_fault_if_requested` is (§P.1 mechanism 1) —
    rather than a test pre-mutating the fake Crew 1 result's files itself.

    Crew 1 is mocked to return `fake_crew1_result` UNMUTATED (the real,
    gate-passing committed handoff); the Flow builds its own run-scoped
    snapshot from it and mutates ONLY that snapshot, strictly after Crew 1
    and strictly before the gate — exactly the production code path
    `scripts/run_pipeline.py --inject-failure <fault_injection>` runs.
    Crew 2 is mocked to refuse to run (this helper exists only for
    scenarios that must block).
    """
    crew2_calls = {"n": 0}

    def fake_crew1(raw_df, *, run_id, llm=None):  # noqa: ARG001
        return fake_crew1_result

    def fake_crew2(**kwargs):  # noqa: ARG001
        crew2_calls["n"] += 1
        raise AssertionError("Crew 2 must never start after a fault-injected gate failure")

    with patched(pipeline_flow, "_crew1_run_analyst_crew", fake_crew1), \
         patched(pipeline_flow, "_crew2_run_scientist_crew", fake_crew2):
        flow = HarborValeFlow(fault_injection=fault_injection)
        flow.kickoff()

    return flow.state, crew2_calls, flow._validation_report
