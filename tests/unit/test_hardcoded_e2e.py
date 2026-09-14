"""The Phase 5 mandatory proof: the entire deterministic execution layer,
end-to-end, on the REAL Telco data, with hardcoded (not agent-produced)
plans, and zero LLM/Agent/Crew/Flow (PROJECT_PLAN.md §T Phase 5 acceptance:
"פייפליין מלא רץ end-to-end עם תוכניות hardcoded, בלי LLM · הרצה כפולה עם
אותן תוכניות מייצרת ארטיפקטים זהים (מלבד timestamps)").

Uses `tests/fixtures/hardcoded_e2e_harness.py` — not a mock, not the
30-row synthetic Phase 3 fixture, the actual `data/raw/telco_customer_churn.csv`
(7,043 rows) `scripts/download_data.py` acquired in Phase 2.

Runnable two ways:
  * ``pytest tests/unit/test_hardcoded_e2e.py``   (once pytest is installed)
  * ``python tests/unit/test_hardcoded_e2e.py``   (no test dependency required)
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale.access.allowlist import HandoffAccessDenied  # noqa: E402
from harbor_vale.access.handoff import Crew2Handoff, build_crew2_handoff  # noqa: E402
from harbor_vale.io_paths import RAW_TELCO_CHURN_CSV  # noqa: E402
from tests.fixtures.hardcoded_e2e_harness import HardcodedE2EResult, run_hardcoded_e2e  # noqa: E402

_SKIP_REASON = (
    f"real raw dataset not found at {RAW_TELCO_CHURN_CSV} — run "
    "`python scripts/download_data.py` first (Phase 2 acquisition)."
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(tmp: Path, run_id: str) -> HardcodedE2EResult:
    return run_hardcoded_e2e(tmp / run_id, run_id=run_id)


# --- the single-run proof ---------------------------------------------------

def test_hardcoded_e2e_runs_on_the_real_telco_data_with_zero_llm() -> None:
    """The core mandatory proof: raw -> clean -> EDA -> insights -> contract
    -> gate PASS -> handoff -> features -> train -> evaluate -> winner ->
    experiments.json -> model.joblib, all on the real 7,043-row dataset,
    all hardcoded plans, zero LLM calls (no `crewai.Agent`/`Task`/`Crew`/
    `Flow` import appears anywhere in the harness — grep-verifiable)."""
    if not RAW_TELCO_CHURN_CSV.is_file():
        print(f"SKIP: {_SKIP_REASON}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        result = _run(Path(tmp), "single-run")

        assert result.gate_passed is True, "the Phase 4 gate must PASS for the hardcoded, evidence-based plans"
        assert result.clean_data_csv.is_file()
        assert result.dataset_contract_json.is_file()
        assert result.eda_report_html.is_file()
        assert result.insights_md.is_file()
        assert result.features_csv.is_file()
        assert result.experiments_json.is_file()
        assert result.model_joblib.is_file()

        assert result.winner_estimator in ("logistic_regression", "random_forest", "gradient_boosting")
        assert 0.5 < result.winner_test_roc_auc <= 1.0, (
            f"a churn model on real data should beat random guessing (0.5); "
            f"got {result.winner_test_roc_auc}"
        )

        experiments = json.loads(result.experiments_json.read_text(encoding="utf-8"))
        assert len(experiments["variants"]) >= 2, "at least 2 model variants must be trained/evaluated"
        assert experiments["winner"]["name"] == result.winner_name


def test_hardcoded_e2e_used_the_real_clean_data_not_the_synthetic_fixture() -> None:
    """The real Telco dataset has 7,043 rows — a completely different
    magnitude from the 30-row Phase 3 synthetic fixture. Proves this test
    did not quietly fall back to the small fixture."""
    if not RAW_TELCO_CHURN_CSV.is_file():
        print(f"SKIP: {_SKIP_REASON}")
        return
    import pandas as pd

    with tempfile.TemporaryDirectory() as tmp:
        result = _run(Path(tmp), "real-data-check")
        clean_df = pd.read_csv(result.clean_data_csv)
        assert len(clean_df) == 7043
        assert result.raw_csv == RAW_TELCO_CHURN_CSV


def test_hardcoded_e2e_never_touches_the_real_artifacts_directory() -> None:
    """Every artifact lands in an isolated temp workspace — never
    `artifacts/crew1/` or `artifacts/crew2/`, which would falsely present
    this harness's output as a real Crew execution."""
    if not RAW_TELCO_CHURN_CSV.is_file():
        print(f"SKIP: {_SKIP_REASON}")
        return
    from harbor_vale.io_paths import ARTIFACTS

    artifacts_before = set(ARTIFACTS.rglob("*")) if ARTIFACTS.exists() else set()
    with tempfile.TemporaryDirectory() as tmp:
        result = _run(Path(tmp), "isolation-check")
        assert str(result.workspace).startswith(tmp)
    artifacts_after = set(ARTIFACTS.rglob("*")) if ARTIFACTS.exists() else set()
    assert artifacts_before == artifacts_after, "the hardcoded harness must never write into the real artifacts/ tree"


# --- the Crew 2 boundary, exercised inside a real E2E run -------------------

def test_hardcoded_e2e_crew2_handoff_is_exactly_the_two_approved_files() -> None:
    if not RAW_TELCO_CHURN_CSV.is_file():
        print(f"SKIP: {_SKIP_REASON}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        result = _run(Path(tmp), "handoff-check")
        allowlist = build_crew2_handoff(result.clean_data_csv, result.dataset_contract_json)
        handoff = Crew2Handoff(allowlist)

        assert handoff.read_handoff("clean_data")  # succeeds, non-empty
        assert handoff.read_handoff("dataset_contract")  # succeeds, non-empty

        try:
            allowlist.read_path(result.insights_md)
        except HandoffAccessDenied:
            pass
        else:
            raise AssertionError("expected HandoffAccessDenied for insights.md through the E2E's own handoff")

        try:
            allowlist.read_path(result.eda_report_html)
        except HandoffAccessDenied:
            pass
        else:
            raise AssertionError("expected HandoffAccessDenied for eda_report.html through the E2E's own handoff")


# --- double-run reproducibility (§T Phase 5 acceptance, mandatory) ---------

def test_double_run_reproducibility_byte_identical_artifacts() -> None:
    """Run the ENTIRE hardcoded pipeline twice — identical raw input data,
    identical hardcoded plans, identical pinned seeds/dependency versions,
    identical `run_id` — into two separate workspaces, and compare actual
    file bytes (never "same metrics" hand-waving).

    **Verified empirically byte-identical** (not merely claimed): `clean_data.csv`,
    `dataset_contract.json`, `eda_report.html`, `insights.md`, `features.csv`,
    `experiments.json`, `validation_report.md`, every generated figure PNG,
    and — checked explicitly, not assumed — `model.joblib` itself (this
    environment's sklearn estimators are single-threaded by default with a
    fixed `random_state`, so their fitted parameters, and therefore their
    pickled bytes, come out identical; a different environment with forced
    parallelism could break this, which is exactly why this test checks the
    real bytes rather than asserting it as an architectural guarantee).

    **The one field allowed, and expected, to differ:**
    `validation_report.json`'s `validated_at` — `contract/validator.py`
    always stamps real wall-clock time by design (a validation report should
    honestly record when it ran). Handled explicitly below: compared with
    that one field removed, not ignored by omission.
    """
    if not RAW_TELCO_CHURN_CSV.is_file():
        print(f"SKIP: {_SKIP_REASON}")
        return
    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
        r1 = _run(Path(tmp1), "reproducibility-run")
        r2 = _run(Path(tmp2), "reproducibility-run")  # SAME run_id on purpose

        byte_identical_pairs = [
            (r1.clean_data_csv, r2.clean_data_csv),
            (r1.dataset_contract_json, r2.dataset_contract_json),
            (r1.eda_report_html, r2.eda_report_html),
            (r1.insights_md, r2.insights_md),
            (r1.features_csv, r2.features_csv),
            (r1.experiments_json, r2.experiments_json),
            (r1.validation_report_md, r2.validation_report_md),
            (r1.model_joblib, r2.model_joblib),
        ]
        for p1, p2 in byte_identical_pairs:
            h1, h2 = _sha256(p1), _sha256(p2)
            assert h1 == h2, f"{p1.name} differed between runs: {h1} != {h2}"

        figures1 = sorted((r1.workspace / "figures").glob("*.png"))
        figures2 = sorted((r2.workspace / "figures").glob("*.png"))
        assert [p.name for p in figures1] == [p.name for p in figures2]
        for f1, f2 in zip(figures1, figures2):
            assert _sha256(f1) == _sha256(f2), f"figure {f1.name} differed between runs"

        # validation_report.json: identical except the one honestly-dynamic field.
        j1 = json.loads(r1.validation_report_json.read_text(encoding="utf-8"))
        j2 = json.loads(r2.validation_report_json.read_text(encoding="utf-8"))
        j1_no_ts = {k: v for k, v in j1.items() if k != "validated_at"}
        j2_no_ts = {k: v for k, v in j2.items() if k != "validated_at"}
        assert j1_no_ts == j2_no_ts, "validation_report.json differed in a field other than validated_at"
        assert j1["validated_at"] != j2["validated_at"], (
            "validated_at unexpectedly identical across two separate runs — "
            "either a clock-resolution coincidence or a real bug; investigate before trusting this test"
        )

        # Same experiment inputs -> same winner (argmax is deterministic).
        assert r1.winner_name == r2.winner_name
        assert r1.winner_estimator == r2.winner_estimator
        assert r1.winner_test_roc_auc == r2.winner_test_roc_auc


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
