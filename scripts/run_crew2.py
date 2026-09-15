"""Phase 7 — the real, live Crew 2 (Data Scientist Crew) acceptance run
(PROJECT_PLAN.md §T Phase 7, Internal Gate 7.7 — "Standalone Gate Precheck").

**Not Phase 8's `Flow`.** This is a simple, trusted orchestration entry
point that (1) runs the existing Phase 4 validation gate against the
current final Crew 1 artifacts, (2) refuses to start Crew 2 if the gate
fails, and (3) on a PASS, runs Crew 2 against exactly the two approved
handoff files, injecting only minimal `handoff_status` metadata — never the
validation report itself (§G.0, §F.0). No router, no state machine.

Runs the actual 3-agent CrewAI Crew against the real OpenAI API. **This is
the only script in the project that spends real LLM tokens for Crew 2.**

Usage:
    python scripts/run_crew2.py

Prints a structured, secret-free summary. Never prints the API key or raw
LLM prompts.
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

from config.llm import load_llm_config, require_api_key  # noqa: E402
from harbor_vale.contract.validator import run_validation_gate  # noqa: E402
from harbor_vale.crews.scientist_crew import run_scientist_crew  # noqa: E402
from harbor_vale.io_paths import (  # noqa: E402
    CREW2,
    CREW2_INTERNAL,
    EDA_REPORT_HTML,
    HANDOFF_CLEAN_DATA,
    HANDOFF_CONTRACT,
    INSIGHTS_MD,
    ensure_runtime_dirs,
)


def main() -> int:
    require_api_key()  # raises with a clear message if missing; never prints the value

    for path in (HANDOFF_CLEAN_DATA, HANDOFF_CONTRACT, EDA_REPORT_HTML, INSIGHTS_MD):
        if not path.is_file():
            print(f"ERROR: required Crew 1 artifact not found at {path} — run scripts/run_crew1.py first.")
            return 1

    ensure_runtime_dirs()

    # Clean only Crew 2's own workspace before a fresh run — never touch
    # Crew 1's tree.
    for stale in CREW2.glob("*"):
        if stale.is_file() and stale.name != ".gitkeep":
            stale.unlink()
    if CREW2_INTERNAL.is_dir():
        for stale in CREW2_INTERNAL.glob("*"):
            if stale.is_file() and stale.name != ".gitkeep":
                stale.unlink()

    llm_config = load_llm_config()
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"

    print("=" * 70)
    print("Internal Gate 7.7 — Phase 4 validation gate (must PASS before Crew 2 starts)")
    print("=" * 70)
    gate_report = run_validation_gate(
        HANDOFF_CLEAN_DATA, HANDOFF_CONTRACT, EDA_REPORT_HTML, INSIGHTS_MD, run_id=run_id
    )
    print(f"gate passed       : {gate_report.passed}")
    print(f"errors            : {gate_report.errors}")
    print(f"warnings          : {gate_report.warnings}")
    if not gate_report.passed:
        for f in gate_report.findings:
            if f.severity == "ERROR":
                print(f"  [ERROR] {f.check_family} :: {f.message}")
        print()
        print("Gate FAILED. Crew 2 (Data Scientist Crew) was NOT started.")
        return 2

    print()
    print("=" * 70)
    print("Crew 2 (Data Scientist Crew) — LIVE run")
    print(f"run_id            : {run_id}")
    print(f"model / temperature: {llm_config.model} / {llm_config.temperature}")
    print("=" * 70)

    result = run_scientist_crew(
        clean_data_csv=HANDOFF_CLEAN_DATA,
        dataset_contract_json=HANDOFF_CONTRACT,
        run_id=run_id,
        contract_version=gate_report.contract_version,
        handoff_status="gate_passed",
        validation_warnings=gate_report.warnings,
    )

    print()
    print(f"status            : {result.status}")
    if result.status != "completed":
        print(f"failure_category  : {result.failure_category}")
        print(f"failure_message   : {result.failure_message}")
        return 1

    print(f"model_card_degraded: {result.model_card_degraded}")
    if result.model_card_degraded:
        print(f"degraded_reason    : {result.model_card_degraded_reason}")
    print(f"winner            : {result.winner_name}")

    print()
    print("Artifacts:")
    for p in (result.features_csv, result.model_joblib, result.evaluation_report_md, result.model_card_md):
        exists = p.is_file()
        size = p.stat().st_size if exists else 0
        print(f"  {p.relative_to(_ROOT)}  exists={exists}  size={size}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
