"""Central, deterministic path layer for the whole project.

Every path used anywhere in the codebase — scripts, tests, the Flow, and the
Streamlit app — is derived here from :data:`PROJECT_ROOT`. No absolute,
machine-specific path is written anywhere in the project; this is the single
place path strings are defined. See PROJECT_PLAN.md §L (fix #13) and §W
("zero machine-specific absolute paths").

Importing this module has **no side effects**: nothing is created, read, or
written. Directory creation is an explicit call to :func:`ensure_runtime_dirs`.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Project root — derived from this file's location, never hardcoded.
# This file lives at  <root>/src/harbor_vale/io_paths.py
#   parents[0] = <root>/src/harbor_vale
#   parents[1] = <root>/src
#   parents[2] = <root>
# ---------------------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

# --- Top-level directories -------------------------------------------------
SRC = PROJECT_ROOT / "src"
CONFIG = PROJECT_ROOT / "config"
DATA = PROJECT_ROOT / "data"
DATA_RAW = DATA / "raw"
DATA_README = DATA / "README.md"
ARTIFACTS = PROJECT_ROOT / "artifacts"
RUNS = PROJECT_ROOT / "runs"
LOGS = PROJECT_ROOT / "logs"
TESTS = PROJECT_ROOT / "tests"
DOCS = PROJECT_ROOT / "docs"
SCRIPTS = PROJECT_ROOT / "scripts"
SPIKE = PROJECT_ROOT / "spike"

# --- Config files -------------------------------------------------------------
SETTINGS_YAML = CONFIG / "settings.yaml"

# --- Dataset (Phase 2, PROJECT_PLAN.md §J) ---------------------------------
# The selected dataset's raw file, at its deterministic acquisition filename.
# Written only by scripts/download_data.py; never committed (data/raw/ is
# git-ignored except .gitkeep). See data/README.md for provenance + SHA256.
RAW_TELCO_CHURN_CSV = DATA_RAW / "telco_customer_churn.csv"

# --- Crew 1 artifact locations ---------------------------------------------
CREW1 = ARTIFACTS / "crew1"
CREW1_INTERNAL = CREW1 / "_internal"
CREW1_FIGURES = CREW1 / "figures"

# The approved handoff — exactly these two files (PROJECT_PLAN.md §G.0).
HANDOFF_CLEAN_DATA = CREW1 / "clean_data.csv"
HANDOFF_CONTRACT = CREW1 / "dataset_contract.json"

# Crew 1 narrative artifacts — produced by Crew 1, blocked for Crew 2 (§G.0).
INSIGHTS_MD = CREW1 / "insights.md"
EDA_REPORT_HTML = CREW1 / "eda_report.html"

# --- Validation gate outputs ---------------------------------------------------
VALIDATION = ARTIFACTS / "validation"
VALIDATION_REPORT_JSON = VALIDATION / "validation_report.json"
VALIDATION_REPORT_MD = VALIDATION / "validation_report.md"

# --- Crew 2 artifact locations -------------------------------------------------
CREW2 = ARTIFACTS / "crew2"
CREW2_INTERNAL = CREW2 / "_internal"
FEATURES_CSV = CREW2 / "features.csv"
MODEL_JOBLIB = CREW2 / "model.joblib"
EXPERIMENTS_JSON = CREW2 / "experiments.json"
EVALUATION_REPORT_MD = CREW2 / "evaluation_report.md"
MODEL_CARD_MD = CREW2 / "model_card.md"

# --- Flow-level artifacts ----------------------------------------------------
RUN_SUMMARY_JSON = ARTIFACTS / "run_summary.json"
RUN_METADATA_JSON = ARTIFACTS / "run_metadata.json"
FLOW_DIAGRAM_HTML = DOCS / "flow_diagram.html"


def run_workspace(run_id: str) -> Path:
    """The gitignored, run-scoped scratch directory for one Flow run
    (``runs/<run_id>/``) — Internal Gate 8.4/8.10's home for the run-scoped
    handoff snapshot and the ``--replay-plans`` workspace. Never a location
    any committed artifact lives in permanently; `runs/` is git-ignored
    wholesale (see `.gitignore`)."""
    if not run_id:
        raise ValueError("run_id must be a non-empty string")
    return RUNS / run_id


def handoff_snapshot_dir(run_id: str) -> Path:
    """The run-scoped, exact-byte copy of Crew 1's four final artifacts
    (PROJECT_PLAN.md §H Internal Gate 8.4): the files the Phase 4 gate
    validates AND — if the gate passes — the exact files Crew 2 is bound to.
    Fault injection (Gate 8.5) mutates only the CSV inside this directory,
    never `artifacts/crew1/*`."""
    return run_workspace(run_id) / "handoff"


def replay_workspace(run_id: str) -> Path:
    """The run-scoped workspace `--replay-plans` (Gate 8.10) writes its
    rebuilt deterministic artifacts into. Never `artifacts/crew1/` or
    `artifacts/crew2/` — replay must never overwrite a real production run's
    committed output."""
    return run_workspace(run_id) / "replay"

# Directories the pipeline writes into. Source dirs are deliberately excluded —
# this helper only ever creates *output* locations.
_RUNTIME_DIRS: tuple[Path, ...] = (
    ARTIFACTS,
    CREW1,
    CREW1_INTERNAL,
    CREW1_FIGURES,
    VALIDATION,
    CREW2,
    CREW2_INTERNAL,
    RUNS,
    LOGS,
)


def ensure_runtime_dirs() -> tuple[Path, ...]:
    """Create the pipeline's output directories. Idempotent; safe to call anywhere.

    Never creates or mutates source directories. Returns the tuple of directories
    it ensured, for logging/inspection.
    """
    for directory in _RUNTIME_DIRS:
        directory.mkdir(parents=True, exist_ok=True)
    return _RUNTIME_DIRS


def log_file_for(run_id: str) -> Path:
    """Path of the per-run log file: ``logs/pipeline_<run_id>.log`` (PROJECT_PLAN.md §Q.1)."""
    if not run_id:
        raise ValueError("run_id must be a non-empty string")
    return LOGS / f"pipeline_{run_id}.log"


def relative_to_root(path: Path | str) -> str:
    """Render *path* relative to :data:`PROJECT_ROOT` as a POSIX string.

    Used for portable, machine-independent path reporting in logs, run metadata,
    and the UI. Paths outside the project are returned unchanged (still POSIX).
    """
    p = Path(path).resolve()
    try:
        return p.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return p.as_posix()
