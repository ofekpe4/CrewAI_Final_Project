"""Phase 8 — the real production Flow entrypoint
(PROJECT_PLAN.md §H, Phase 8 Internal Gate 8.11).

The Flow itself lives in `harbor_vale.flow.pipeline_flow.HarborValeFlow` —
this script is a thin CLI: parse flags, build the initial `PipelineState`,
`kickoff()`, print a structured secret-free summary, and return a
meaningful exit code. All orchestration logic (crew invocation, the
validation gate, fault injection, routing) lives in the Flow itself, never
here.

Usage:
    python scripts/run_pipeline.py                                # normal end-to-end run
    python scripts/run_pipeline.py --validate-only                # gate-only, against existing artifacts/crew1/*
    python scripts/run_pipeline.py --replay-plans                 # deterministic replay — zero LLM calls
    python scripts/run_pipeline.py --inject-failure scale_change  # demo: the gate blocks Crew 2
    python scripts/run_pipeline.py --replay-plans --inject-failure scale_change  # prove the fault route with zero LLM calls

Rejected combinations (clear CLI error, no surprising behaviour):
    --validate-only + --replay-plans     (two different skip-the-crews modes)
    --validate-only + --inject-failure   (validate-only has no run-scoped snapshot to mutate)

Never prints the API key or raw LLM prompts. Exit codes: `0` on
`status=completed`; `2` on `status=halted_validation`; `1` on any other
non-completed status.
"""

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from config.llm import require_api_key  # noqa: E402
from harbor_vale.flow import HarborValeFlow  # noqa: E402

_SUPPORTED_FAULTS = ("scale_change",)


def _parse_args(argv: "list[str] | None" = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Harbor & Vale — the production pipeline Flow.")
    parser.add_argument(
        "--validate-only", action="store_true",
        help="skip both crews; run the gate against the existing on-disk artifacts/crew1/* only.",
    )
    parser.add_argument(
        "--replay-plans", action="store_true",
        help="deterministic replay of stored, guardrail-accepted agent plans — zero LLM calls.",
    )
    parser.add_argument(
        "--inject-failure", metavar="SCENARIO", choices=_SUPPORTED_FAULTS, default=None,
        help=f"demo-only: inject a fault into a run-scoped copy of the Crew 1 handoff, before the gate. "
             f"Supported: {', '.join(_SUPPORTED_FAULTS)}.",
    )
    args = parser.parse_args(argv)

    if args.validate_only and args.replay_plans:
        parser.error("--validate-only and --replay-plans cannot be combined (two different skip-the-crews modes).")
    if args.validate_only and args.inject_failure:
        parser.error("--validate-only and --inject-failure cannot be combined (validate-only has no run-scoped snapshot to mutate).")
    return args


def main(argv: "list[str] | None" = None) -> int:
    args = _parse_args(argv)

    if not (args.validate_only or args.replay_plans):
        require_api_key()  # raises with a clear message if missing; never prints the value

    flow = HarborValeFlow(
        validate_only=args.validate_only,
        replay_plans=args.replay_plans,
        fault_injection=args.inject_failure,
    )

    print("=" * 70)
    print("Harbor & Vale — pipeline Flow")
    print(f"validate_only     : {args.validate_only}")
    print(f"replay_plans      : {args.replay_plans}")
    print(f"inject_failure    : {args.inject_failure}")
    print("=" * 70)

    flow.kickoff()
    final_state = flow.state

    print()
    print(f"run_id            : {final_state.run_id}")
    print(f"status            : {final_state.status}")
    print(f"execution_mode    : {final_state.execution_mode}")
    if final_state.failure_category:
        print(f"failure_category  : {final_state.failure_category}")
        print(f"failure_summary   : {final_state.failure_summary}")

    print()
    print(f"crew1_completed   : {final_state.crew1_completed}")
    print(
        f"validation_passed : {final_state.validation_passed} "
        f"({final_state.validation_errors} error(s), {final_state.validation_warnings} warning(s))"
    )
    print(f"crew2_started     : {final_state.crew2_started}")
    if final_state.crew2_started:
        print(f"crew2_completed   : {final_state.crew2_completed}")
        if final_state.crew2_completed:
            print(f"best_model        : {final_state.best_model_name}")
            print(f"{final_state.primary_metric or 'primary_metric':<18}: {final_state.primary_metric_value}")

    print()
    print(f"log_path          : {final_state.log_path}")
    print("run_summary       : artifacts/run_summary.json")
    print("run_metadata      : artifacts/run_metadata.json")

    if final_state.status == "completed":
        return 0
    if final_state.status == "halted_validation":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
