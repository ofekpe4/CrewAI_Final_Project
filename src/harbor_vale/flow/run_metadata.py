"""`run_metadata.json` — reproducibility metadata (PROJECT_PLAN.md §Q.4, §R).

Zero LLM calls, zero `Agent`/`Task`/`Crew`/`Flow` objects. Every value here
is either read directly from the running interpreter/environment/installed
packages, or computed from files already under version control — never a
stale, hand-typed example value. `config/llm.py` (Phase 0) is reused for the
LLM block rather than re-reading `settings.yaml` directly, so this module
stays consistent with whatever `config/llm.py` actually resolves at
execution time.

**Git commit semantics** (Phase 8, "GIT COMMIT METADATA NUANCE"):
`git_commit` is `git rev-parse HEAD` at the moment this module runs — the
commit the pipeline is executing FROM. It can never contain its own future
commit hash (this file, once written, becomes part of a LATER commit, if
any) — no circular commit rewriting is attempted here or anywhere else in
this project, per the permanent no-self-hash-amend rule
(`.claude/rules/task-workflow.md`).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

from config.llm import load_llm_config
from harbor_vale.io_paths import PROJECT_ROOT, RAW_TELCO_CHURN_CSV, RUN_METADATA_JSON
from harbor_vale.logging_setup import get_logger

logger = get_logger(__name__)

_PACKAGE_VERSION_NAMES = ("crewai", "pandas", "scikit-learn", "pydantic")
"""The Plan §Q.4-named packages plus `pydantic` (every structured agent
output/guardrail in this project is a pydantic model — its version is as
load-bearing as crewai's/pandas's/scikit-learn's own)."""


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in _PACKAGE_VERSION_NAMES:
        try:
            versions[name] = importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:  # pragma: no cover — every listed package is a pinned dependency
            versions[name] = "unknown"
    return versions


def _git_commit() -> str | None:
    """`None` (never a crash) if git is unavailable or this is not a git
    checkout — metadata must never block a run over an informational field."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return result.stdout.strip()
    except Exception:  # noqa: BLE001 — see docstring
        logger.warning("run_metadata: could not resolve git_commit")
        return None


def _dataset_sha256() -> str | None:
    """sha256 of the real raw dataset file, if present on disk. `None` for a
    `--validate-only` run against artifacts alone (no raw file necessarily
    touched this run) where the raw CSV also happens to be absent."""
    if not RAW_TELCO_CHURN_CSV.is_file():
        return None
    return hashlib.sha256(RAW_TELCO_CHURN_CSV.read_bytes()).hexdigest()


def _prompt_config_hash() -> str:
    """sha256 over every version-controlled ``crews/*/config/*.yaml`` file
    (every Crew 1/Crew 2 agent/task prompt), sorted by relative path for a
    stable, platform-independent ordering. Never touches `.env` or any
    secret — these are plain, already-committed YAML prompt files."""
    config_dir = PROJECT_ROOT / "src" / "harbor_vale" / "crews"
    files = sorted(config_dir.glob("*/config/*.yaml"))
    digest = hashlib.sha256()
    for f in files:
        digest.update(f.relative_to(PROJECT_ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(f.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def build_run_metadata(
    *,
    run_id: str,
    timestamp: str,
    contract_version: str | None,
    execution_mode: str,
    fault_injection: str | None,
    replay_plans: bool,
) -> dict[str, Any]:
    """Assemble the `run_metadata.json` document (§Q.4) for one run.

    Every field is either read live (interpreter/package/git) or passed in
    by the caller (`pipeline_flow.py`, from `PipelineState`) — this function
    itself makes no Flow/Crew calls and imports none.
    """
    llm_config = load_llm_config()
    return {
        "run_id": run_id,
        "timestamp": timestamp,
        "python_version": platform.python_version(),
        "package_versions": _package_versions(),
        "llm": llm_config.as_metadata(),
        "seeds": {
            "python_hash": 0,
            "python_hash_seed_actual": os.environ.get("PYTHONHASHSEED"),
            "numpy": 42,
            "sklearn_random_state": 42,
        },
        "prompt_config_hash": _prompt_config_hash(),
        "dataset_sha256": _dataset_sha256(),
        "contract_version": contract_version or None,
        "git_commit": _git_commit(),
        "execution_mode": execution_mode,
        "fault_injection": fault_injection,
        "replay_plans": replay_plans,
    }


def write_run_metadata(metadata: dict[str, Any], *, out_path: Path | None = None) -> Path:
    """Write `metadata` to `artifacts/run_metadata.json` (or `out_path`, for
    tests). No secret is ever a value in `metadata` — `build_run_metadata`
    never reads `OPENAI_API_KEY` or any other environment secret."""
    target = out_path or RUN_METADATA_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return target
