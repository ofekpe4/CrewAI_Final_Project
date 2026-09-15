"""Phase 6 — the real, live Crew 1 (Data Analyst Crew) acceptance run
(PROJECT_PLAN.md §T Phase 6, Internal Gate 6.8).

Runs the actual 3-agent CrewAI Crew against the real OpenAI API and the real
7,043-row Telco Customer Churn dataset, writing the four required artifacts
into the real `artifacts/crew1/` tree. **This is the only script in the
project that spends real LLM tokens for Crew 1.**

Usage:
    python scripts/run_crew1.py

Prints a structured, secret-free summary: status, retry/degradation info,
artifact paths, and (if the run completed) whether the generated contract
passes the Phase 4 gate. Never prints the API key or raw LLM prompts.
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import pandas as pd  # noqa: E402

from config.llm import load_llm_config, require_api_key  # noqa: E402
from harbor_vale.contract.validator import render_validation_report_markdown, run_validation_gate  # noqa: E402
from harbor_vale.crews.analyst_crew import run_analyst_crew  # noqa: E402
from harbor_vale.io_paths import (  # noqa: E402
    ARTIFACTS,
    CREW1,
    CREW1_INTERNAL,
    RAW_TELCO_CHURN_CSV,
    VALIDATION,
    ensure_runtime_dirs,
)


def main() -> int:
    require_api_key()  # raises with a clear message if missing; never prints the value

    if not RAW_TELCO_CHURN_CSV.is_file():
        print(f"ERROR: raw dataset not found at {RAW_TELCO_CHURN_CSV} — run scripts/download_data.py first.")
        return 1

    ensure_runtime_dirs()

    # Clean only Crew 1's own workspace before a fresh run — never touch
    # data/raw/* (source of truth) or any other crew's tree, and never
    # delete a tracked `.gitkeep` placeholder (`Path.glob("*")`, unlike a
    # POSIX shell glob, DOES match dotfiles).
    for stale in CREW1.glob("*"):
        if stale.is_file() and stale.name != ".gitkeep":
            stale.unlink()
    if CREW1_INTERNAL.is_dir():
        for stale in CREW1_INTERNAL.glob("*"):
            if stale.is_file() and stale.name != ".gitkeep":
                stale.unlink()

    llm_config = load_llm_config()
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"

    print("=" * 70)
    print("Crew 1 (Data Analyst Crew) — LIVE run")
    print(f"run_id            : {run_id}")
    print(f"model / temperature: {llm_config.model} / {llm_config.temperature}")
    print(f"dataset           : {RAW_TELCO_CHURN_CSV.name}")
    print("=" * 70)

    raw_df = pd.read_csv(RAW_TELCO_CHURN_CSV)
    result = run_analyst_crew(raw_df, run_id=run_id, raw_target_column="Churn")

    print()
    print(f"status            : {result.status}")
    if result.status != "completed":
        print(f"failure_category  : {result.failure_category}")
        print(f"failure_message   : {result.failure_message}")
        return 1

    print(f"eda_degraded      : {result.eda_degraded}")
    if result.eda_degraded:
        print(f"eda_degraded_reason: {result.eda_degraded_reason}")

    print()
    print("Artifacts:")
    for p in (result.clean_data_csv, result.eda_report_html, result.insights_md, result.dataset_contract_json):
        exists = p.is_file()
        size = p.stat().st_size if exists else 0
        print(f"  {p.relative_to(_ROOT)}  exists={exists}  size={size}")

    print()
    print("Running the Phase 4 validation gate against the final Crew 1 artifacts...")
    report = run_validation_gate(
        result.clean_data_csv, result.dataset_contract_json, result.eda_report_html, result.insights_md,
        run_id=run_id,
    )
    VALIDATION.mkdir(parents=True, exist_ok=True)
    (VALIDATION / "validation_report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (VALIDATION / "validation_report.md").write_text(render_validation_report_markdown(report), encoding="utf-8")

    print(f"gate passed       : {report.passed}")
    print(f"errors            : {report.errors}")
    print(f"warnings          : {report.warnings}")
    if not report.passed:
        for f in report.findings:
            if f.severity == "ERROR":
                print(f"  [ERROR] {f.check_family} :: {f.message}")

    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
