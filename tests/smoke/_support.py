"""Shared support code for the Phase 9 UI smoke tests (PROJECT_PLAN.md §O.4).

Not a `test_*.py` file itself — never collected/run directly. Provides:

- the same sys.path bootstrap every test/script in this repo does independently
- a context manager that points every `app/lib/ui_helpers` artifact path at a
  temporary directory for the duration of one test, so tests never depend on
  (or mutate) this developer machine's real `artifacts/` tree
- a small `AppTest` runner wrapper
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src"), str(_ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PROJECT_ROOT = _ROOT
APP_ROOT = _ROOT / "app"

from lib import ui_helpers as ui  # noqa: E402

_PATCHED_PATH_ATTRS = [
    "RUN_SUMMARY_JSON",
    "RUN_METADATA_JSON",
    "HANDOFF_CLEAN_DATA",
    "HANDOFF_CONTRACT",
    "EDA_REPORT_HTML",
    "INSIGHTS_MD",
    "CREW1_FIGURES",
    "VALIDATION_REPORT_JSON",
    "VALIDATION_REPORT_MD",
    "FEATURES_CSV",
    "EXPERIMENTS_JSON",
    "EVALUATION_REPORT_MD",
    "MODEL_CARD_MD",
]


@contextmanager
def isolated_artifacts(tmp_path: Path):
    """Redirects every artifact path `ui_helpers` knows about into
    `tmp_path` (which the caller may leave empty, or pre-populate with
    fixture files) and restores the real paths on exit.

    Every page imports `lib.ui_helpers as ui` and reads its path constants
    off that same, already-imported module object — patching the module's
    attributes here is visible to every page `AppTest` subsequently runs,
    exactly like `unittest.mock.patch` would be, without adding that
    dependency.
    """
    originals = {name: getattr(ui, name) for name in _PATCHED_PATH_ATTRS}
    try:
        setattr(ui, "RUN_SUMMARY_JSON", tmp_path / "run_summary.json")
        setattr(ui, "RUN_METADATA_JSON", tmp_path / "run_metadata.json")
        setattr(ui, "HANDOFF_CLEAN_DATA", tmp_path / "crew1" / "clean_data.csv")
        setattr(ui, "HANDOFF_CONTRACT", tmp_path / "crew1" / "dataset_contract.json")
        setattr(ui, "EDA_REPORT_HTML", tmp_path / "crew1" / "eda_report.html")
        setattr(ui, "INSIGHTS_MD", tmp_path / "crew1" / "insights.md")
        setattr(ui, "CREW1_FIGURES", tmp_path / "crew1" / "figures")
        setattr(ui, "VALIDATION_REPORT_JSON", tmp_path / "validation" / "validation_report.json")
        setattr(ui, "VALIDATION_REPORT_MD", tmp_path / "validation" / "validation_report.md")
        setattr(ui, "FEATURES_CSV", tmp_path / "crew2" / "features.csv")
        setattr(ui, "EXPERIMENTS_JSON", tmp_path / "crew2" / "experiments.json")
        setattr(ui, "EVALUATION_REPORT_MD", tmp_path / "crew2" / "evaluation_report.md")
        setattr(ui, "MODEL_CARD_MD", tmp_path / "crew2" / "model_card.md")
        yield tmp_path
    finally:
        for name, value in originals.items():
            setattr(ui, name, value)


ALL_PAGES = [
    APP_ROOT / "streamlit_app.py",
    APP_ROOT / "pages" / "1_Pipeline_Run.py",
    APP_ROOT / "pages" / "2_Crew1_Analysis.py",
    APP_ROOT / "pages" / "3_Dataset_Contract.py",
    APP_ROOT / "pages" / "4_Validation_Gate.py",
    APP_ROOT / "pages" / "5_Crew2_Modeling.py",
    APP_ROOT / "pages" / "6_Logs.py",
]


def run_page(script_path: Path):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(script_path), default_timeout=30)
    at.run()
    return at
