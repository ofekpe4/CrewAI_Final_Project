"""Unit tests — validation gate, check family A (artifacts).

PROJECT_PLAN.md §F.1: "4 הארטיפקטים קיימים ולא ריקים · החוזה JSON תקין ·
תואם ל-Pydantic · ה-CSV נטען". This file proves every one of those, plus the
"prerequisite gating" behaviour documented in `contract/validator.py`'s
module docstring: families B–G do not run at all when the contract or the
CSV never became usable, but family A itself always finishes.

Runnable two ways:
  * ``pytest tests/unit/test_validator_artifacts.py``
  * ``python tests/unit/test_validator_artifacts.py``
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale.contract.validator import run_validation_gate  # noqa: E402
from tests.fixtures.gate_fixtures import CONTRACT_JSON, EDA_REPORT_FIXTURE, FIXTURE_CSV, INSIGHTS_MD_FIXTURE  # noqa: E402


def _findings_by_id(report, check_id: str):
    return [f for f in report.findings if f.check_id == check_id]


# --- missing files -----------------------------------------------------------

def test_missing_csv_file_is_an_artifact_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = run_validation_gate(Path(tmp) / "does_not_exist.csv", CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert report.passed is False
    hits = _findings_by_id(report, "ARTIFACTS_CSV_FILE_EXISTS")
    assert len(hits) == 1 and hits[0].severity == "ERROR"


def test_missing_contract_file_is_an_artifact_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = run_validation_gate(FIXTURE_CSV, Path(tmp) / "does_not_exist.json", EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert report.passed is False
    hits = _findings_by_id(report, "ARTIFACTS_CONTRACT_FILE_EXISTS")
    assert len(hits) == 1 and hits[0].severity == "ERROR"


def test_missing_csv_and_missing_contract_are_both_reported_in_one_run() -> None:
    """Family A does not stop at the first missing artifact."""
    with tempfile.TemporaryDirectory() as tmp:
        report = run_validation_gate(
            Path(tmp) / "no.csv", Path(tmp) / "no.json",
            EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t"
        )
    assert report.passed is False
    assert _findings_by_id(report, "ARTIFACTS_CSV_FILE_EXISTS")
    assert _findings_by_id(report, "ARTIFACTS_CONTRACT_FILE_EXISTS")


# --- empty files ---------------------------------------------------------------

def test_empty_csv_file_is_an_artifact_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "empty.csv"
        empty.write_bytes(b"")
        report = run_validation_gate(empty, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert report.passed is False
    hits = _findings_by_id(report, "ARTIFACTS_CSV_FILE_NOT_EMPTY")
    assert len(hits) == 1 and hits[0].severity == "ERROR"


def test_empty_contract_file_is_an_artifact_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "empty.json"
        empty.write_bytes(b"")
        report = run_validation_gate(FIXTURE_CSV, empty, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert report.passed is False
    hits = _findings_by_id(report, "ARTIFACTS_CONTRACT_FILE_NOT_EMPTY")
    assert len(hits) == 1 and hits[0].severity == "ERROR"


# --- malformed / invalid contract JSON ------------------------------------------

def test_malformed_contract_json_fails_to_parse() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        report = run_validation_gate(FIXTURE_CSV, bad, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert report.passed is False
    hits = _findings_by_id(report, "ARTIFACTS_CONTRACT_JSON_PARSES")
    assert len(hits) == 1 and hits[0].severity == "ERROR"


def test_contract_json_that_parses_but_violates_the_schema_fails_schema_validation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad_schema.json"
        bad.write_text('{"this_is": "not a DatasetContract"}', encoding="utf-8")
        report = run_validation_gate(FIXTURE_CSV, bad, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert report.passed is False
    hits = _findings_by_id(report, "ARTIFACTS_CONTRACT_SCHEMA_VALID")
    assert len(hits) == 1 and hits[0].severity == "ERROR"


# --- unreadable CSV -------------------------------------------------------------

def test_unloadable_csv_fails_to_load() -> None:
    """A file pandas genuinely cannot parse as tabular data."""
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.csv"
        # A single unterminated quoted field is enough to break the C parser.
        bad.write_text('a,b,c\n"unterminated,1,2\n', encoding="utf-8")
        report = run_validation_gate(bad, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    assert report.passed is False
    assert _findings_by_id(report, "ARTIFACTS_CSV_LOADS")


# --- narrative artifacts: eda_report.html / insights.md (§F.1 Family A, all FOUR) --

def test_missing_eda_report_html_is_an_artifact_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = run_validation_gate(
            FIXTURE_CSV, CONTRACT_JSON, Path(tmp) / "does_not_exist.html", INSIGHTS_MD_FIXTURE, run_id="t"
        )
    assert report.passed is False
    hits = _findings_by_id(report, "ARTIFACTS_EDA_REPORT_EXISTS")
    assert len(hits) == 1 and hits[0].severity == "ERROR"


def test_empty_eda_report_html_is_an_artifact_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "empty.html"
        empty.write_bytes(b"")
        report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, empty, INSIGHTS_MD_FIXTURE, run_id="t")
    assert report.passed is False
    hits = _findings_by_id(report, "ARTIFACTS_EDA_REPORT_NOT_EMPTY")
    assert len(hits) == 1 and hits[0].severity == "ERROR"


def test_missing_insights_md_is_an_artifact_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = run_validation_gate(
            FIXTURE_CSV, CONTRACT_JSON, EDA_REPORT_FIXTURE, Path(tmp) / "does_not_exist.md", run_id="t"
        )
    assert report.passed is False
    hits = _findings_by_id(report, "ARTIFACTS_INSIGHTS_MD_EXISTS")
    assert len(hits) == 1 and hits[0].severity == "ERROR"


def test_empty_insights_md_is_an_artifact_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "empty.md"
        empty.write_bytes(b"")
        report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, EDA_REPORT_FIXTURE, empty, run_id="t")
    assert report.passed is False
    hits = _findings_by_id(report, "ARTIFACTS_INSIGHTS_MD_NOT_EMPTY")
    assert len(hits) == 1 and hits[0].severity == "ERROR"


def test_all_four_missing_narrative_artifacts_are_reported_together_with_the_other_two() -> None:
    """Family A does not stop at the first missing artifact, across all four."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        report = run_validation_gate(
            tmp_path / "no.csv", tmp_path / "no.json",
            tmp_path / "no.html", tmp_path / "no.md",
            run_id="t",
        )
    assert report.passed is False
    for check_id in (
        "ARTIFACTS_CSV_FILE_EXISTS", "ARTIFACTS_CONTRACT_FILE_EXISTS",
        "ARTIFACTS_EDA_REPORT_EXISTS", "ARTIFACTS_INSIGHTS_MD_EXISTS",
    ):
        assert _findings_by_id(report, check_id), f"{check_id} should have been reported"


# --- the happy path --------------------------------------------------------------

def test_a_real_valid_set_passes_every_artifact_check() -> None:
    """All four required Crew 1 artifacts present/non-empty (§F.1 Family A)."""
    report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    for check_id in (
        "ARTIFACTS_CSV_FILE_EXISTS", "ARTIFACTS_CSV_FILE_NOT_EMPTY", "ARTIFACTS_CSV_LOADS",
        "ARTIFACTS_CONTRACT_FILE_EXISTS", "ARTIFACTS_CONTRACT_FILE_NOT_EMPTY",
        "ARTIFACTS_CONTRACT_JSON_PARSES", "ARTIFACTS_CONTRACT_SCHEMA_VALID",
        "ARTIFACTS_EDA_REPORT_EXISTS", "ARTIFACTS_EDA_REPORT_NOT_EMPTY",
        "ARTIFACTS_INSIGHTS_MD_EXISTS", "ARTIFACTS_INSIGHTS_MD_NOT_EMPTY",
    ):
        assert not _findings_by_id(report, check_id), f"{check_id} should not have failed"


# --- Crew 2 handoff boundary is NOT widened by checking the narrative artifacts ----

def test_narrative_artifact_content_never_appears_in_the_report() -> None:
    """Family A checks eda_report.html/insights.md exist and are non-empty —
    it must never read, quote, or otherwise surface their CONTENT anywhere
    in the ValidationReport. This is the concrete proof that adding these
    two presence checks does not widen what any downstream consumer of a
    ValidationReport (a future Flow, a future UI) effectively gets to see;
    §G.0's boundary is about who gets the file *content*, and this function
    never even opens these two files beyond a size check."""
    marker = "SECRET_MARKER_THAT_MUST_NEVER_LEAK_INTO_A_FINDING_9f2a4c"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        eda = tmp_path / "eda_report.html"
        eda.write_text(f"<html>{marker}</html>", encoding="utf-8")
        insights = tmp_path / "insights.md"
        insights.write_text(f"# insights\n{marker}\n", encoding="utf-8")
        report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, eda, insights, run_id="t")

    dumped = report.model_dump_json()
    assert marker not in dumped
    for finding in report.findings:
        assert marker not in (finding.message or "")
        assert marker not in str(finding.expected)
        assert marker not in str(finding.observed)


def test_run_validation_gate_never_reads_narrative_artifact_bytes() -> None:
    """A stronger, more direct version of the boundary proof: a file that is
    not even valid UTF-8/text (would raise if `.read_text()`/`.open('r')`
    were ever called on it) must still validate cleanly as long as it is
    non-empty — proving the implementation truly never opens these two
    files for anything beyond an existence/size check."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        eda = tmp_path / "binary.html"
        eda.write_bytes(b"\xff\xfe\x00\x01not valid utf-8 at all\xff")
        insights = tmp_path / "binary.md"
        insights.write_bytes(b"\x00\x01\x02\x03binary garbage\xfe\xff")
        report = run_validation_gate(FIXTURE_CSV, CONTRACT_JSON, eda, insights, run_id="t")

    assert not _findings_by_id(report, "ARTIFACTS_EDA_REPORT_EXISTS")
    assert not _findings_by_id(report, "ARTIFACTS_EDA_REPORT_NOT_EMPTY")
    assert not _findings_by_id(report, "ARTIFACTS_INSIGHTS_MD_EXISTS")
    assert not _findings_by_id(report, "ARTIFACTS_INSIGHTS_MD_NOT_EMPTY")


# --- prerequisite gating: B-G do not run without a usable contract + CSV --------

def test_families_b_through_g_do_not_run_when_the_contract_fails_to_parse() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        report = run_validation_gate(FIXTURE_CSV, bad, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    families = {f.check_family for f in report.findings}
    assert families == {"artifacts"}


def test_families_b_through_g_do_not_run_when_the_csv_fails_to_load() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.csv"
        bad.write_text('a,b,c\n"unterminated,1,2\n', encoding="utf-8")
        report = run_validation_gate(bad, CONTRACT_JSON, EDA_REPORT_FIXTURE, INSIGHTS_MD_FIXTURE, run_id="t")
    families = {f.check_family for f in report.findings}
    assert families <= {"artifacts", "integrity"}
    assert "schema" not in families and "target" not in families and "modeling" not in families


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
