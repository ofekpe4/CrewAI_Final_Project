"""Phase 6 — Crew 1 (Analyst Crew) mocked/offline tests (PROJECT_PLAN.md §T
Phase 6). **No OPENAI_API_KEY required, no network call** — every LLM call
is served by a scripted `crewai.llms.base_llm.BaseLLM` subclass that returns
canned, already-known-valid-or-invalid JSON strings, exactly the same
technique `spike/task_1_2_guardrail_retry.py` proved against the real pinned
`crewai==1.15.20`. The *real* CrewAI `Agent`/`Task`/`Crew`/guardrail/
callback/retry machinery all run for real; only the LLM backend is fake.

Run directly: `python tests/unit/test_analyst_crew.py`
"""

import os
import shutil
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd  # noqa: E402
from crewai.llms.base_llm import BaseLLM  # noqa: E402

from harbor_vale.contract.schema import (  # noqa: E402
    BusinessRangeConstraint,
    ClosedDomainConstraint,
    DtypeConstraint,
    EnforcementLevel,
    ExcludedFeature,
    ExclusionType,
    NullableConstraint,
    SemanticType,
    UnitConstraint,
    UniqueConstraint,
)
from harbor_vale.crews.analyst_crew.analyst_crew import build_analyst_crew, run_analyst_crew  # noqa: E402
from harbor_vale.crews.analyst_crew.guardrails import GUARDRAIL_MAX_RETRIES  # noqa: E402
from harbor_vale.crews.analyst_crew.runtime import Crew1RunContext, crew1_run_context  # noqa: E402
from harbor_vale.plans.cleaning_plan import (  # noqa: E402
    CastOp,
    CleaningPlan,
    RenameOp,
    StandardizeCategoryOp,
)
from harbor_vale.plans.contract_draft import (  # noqa: E402
    ColumnSemanticDraft,
    ContractDraft,
    PrimaryKeyDraft,
    TargetDraft,
)
from harbor_vale.plans.insights_doc import Insight, InsightsDoc  # noqa: E402
from harbor_vale.tools.profiling_tools import profile_dataframe  # noqa: E402

_PASS = []
_FAIL = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        _PASS.append(name)
        print(f"PASS  {name}")
    else:
        _FAIL.append(name)
        print(f"FAIL  {name}  {detail}")


# ---------------------------------------------------------------------------
# A tiny, hand-controlled "raw Telco-shaped" fixture — small on purpose, so
# these tests run in well under a second each.
# ---------------------------------------------------------------------------


_N_ROWS = 24  # >= the Phase 4 gate's MODELING_MIN_ROWS threshold, so the "bonus"
# gate-pass check in test_contract_matches_clean_data is meaningful rather than
# vacuously failing on a too-small fixture.


def tiny_raw_df() -> "pd.DataFrame":
    contracts = ["Month-to-month", "One year", "Two year"]
    return pd.DataFrame(
        {
            "customerID": [f"c{i}" for i in range(_N_ROWS)],
            "Contract": [contracts[i % 3] for i in range(_N_ROWS)],
            "MonthlyCharges": [29.85 + i * 3.1 for i in range(_N_ROWS)],
            "Churn": ["Yes" if i % 4 == 0 else "No" for i in range(_N_ROWS)],
        }
    )


def valid_cleaning_plan() -> CleaningPlan:
    return CleaningPlan(
        operations=[
            RenameOp(old_name="customerID", new_name="customer_id", reason="canonical snake_case name"),
            RenameOp(old_name="Contract", new_name="contract_type", reason="canonical snake_case name"),
            RenameOp(old_name="MonthlyCharges", new_name="monthly_charges", reason="canonical snake_case name"),
            RenameOp(old_name="Churn", new_name="churn", reason="canonical snake_case name"),
            StandardizeCategoryOp(
                column="churn", mapping={"Yes": "1", "No": "0"}, reason="binary target label encoding"
            ),
            CastOp(column="churn", target_dtype="int64", reason="binary label as int64"),
        ]
    )


def invalid_cleaning_plan_json() -> str:
    # Structurally VALID CleaningPlan JSON, but SEMANTICALLY rejected:
    # impute on a column with zero measured nulls (MonthlyCharges has none
    # in this fixture). Deliberately not structurally broken — a
    # structurally-broken payload makes CrewAI's OWN `output_pydantic`
    # re-validation raise `pydantic.ValidationError` mid-retry-loop instead
    # of running the guardrail to full exhaustion (docs/architecture.md §6),
    # which would make the "exactly guardrail_max_retries+1 LLM calls"
    # assertion below fixture-dependent rather than testing the actual
    # guardrail-exhaustion halt path this test exists to prove.
    from harbor_vale.plans.cleaning_plan import ImputeOp

    return CleaningPlan(
        operations=[
            ImputeOp(column="MonthlyCharges", strategy="mean", reason="fabricated: this column has no real nulls")
        ]
    ).model_dump_json()


def valid_insights_doc() -> InsightsDoc:
    # "dataset.row_count"/"dataset.column_count" are ALWAYS real keys
    # (tools.eda_tools.compute_eda_stats always includes them), so this
    # fixture needs no knowledge of the fixture data's exact measured values.
    return InsightsDoc(
        headline="Contract length correlates with observed churn in this sample",
        insights=[
            Insight(
                title="Small sample, six accounts",
                observation="The cleaned dataset has a small, fixed number of rows for this test.",
                business_implication="Not statistically meaningful on its own; illustrative only.",
                recommended_action="Treat as a schema/wiring smoke test, not a business conclusion.",
                evidence_stat_key="dataset.row_count",
            )
        ],
        data_caveats=["This is a synthetic test fixture, not real Telco data."],
    )


def invalid_insights_doc_json() -> str:
    # Structurally valid InsightsDoc JSON, but the evidence_stat_key does
    # not exist -- a SEMANTIC rejection (anti-hallucination guardrail).
    doc = InsightsDoc(
        headline="Fabricated headline",
        insights=[
            Insight(
                title="Made up",
                observation="obs",
                business_implication="impl",
                recommended_action="act",
                evidence_stat_key="this_key_does_not_exist_anywhere",
            )
        ],
    )
    return doc.model_dump_json()


def valid_contract_draft() -> ContractDraft:
    return ContractDraft(
        target=TargetDraft(
            name="churn",
            task_type="binary_classification",
            dtype=DtypeConstraint(expected="int64", justification="binary label by construction"),
            closed_domain=ClosedDomainConstraint(values=["0", "1"], justification="binary label by construction"),
            nullable=NullableConstraint(value=False, justification="a row without a label is unusable"),
        ),
        required_features=["monthly_charges", "contract_type"],
        excluded_features=[
            ExcludedFeature(
                name="customer_id",
                exclusion_type=ExclusionType.IDENTIFIER,
                enforcement=EnforcementLevel.HARD,
                justification="a unique key carries no generalizable signal",
            )
        ],
        primary_key=PrimaryKeyDraft(
            columns=["customer_id"], unique=UniqueConstraint(value=True, justification="one row per customer")
        ),
        columns=[
            ColumnSemanticDraft(
                name="customer_id",
                semantic_type=SemanticType.IDENTIFIER,
                nullable=NullableConstraint(value=False, justification="every row identifies a customer"),
            ),
            ColumnSemanticDraft(
                name="contract_type",
                semantic_type=SemanticType.CATEGORICAL,
                nullable=NullableConstraint(value=False, justification="every account has a contract type"),
                closed_domain=ClosedDomainConstraint(
                    values=["Month-to-month", "One year", "Two year"],
                    justification="the provider offers exactly these three contract terms",
                ),
            ),
            ColumnSemanticDraft(
                name="monthly_charges",
                semantic_type=SemanticType.MONETARY,
                dtype=DtypeConstraint(expected="float64", justification="continuous monetary amount"),
                unit=UnitConstraint(
                    value="currency_unspecified",
                    evidence="the source documentation does not state a currency",
                    confidence="low",
                ),
                nullable=NullableConstraint(value=False, justification="every account has a recurring charge"),
                business_range=BusinessRangeConstraint(min=0, max=None, justification="a charge cannot be negative"),
            ),
        ],
        assumptions=["one row per customer; customer_id is unique"],
    )


def invalid_contract_draft_json() -> str:
    return '{"not": "a valid ContractDraft at all"}'


class ScriptedLLM(BaseLLM):
    """Returns one canned string per call, in order; raises if exhausted
    (so a test that under-supplies responses fails loudly instead of
    silently repeating the last one — the opposite default of the Phase 1
    spike's `ScriptedLLM`, deliberately, so a wrong retry-count assumption
    in one of these tests cannot hide behind an accidental repeat)."""

    responses: list = []
    calls: list = []

    def __init__(self, responses: list, **kwargs: Any) -> None:
        super().__init__(model="scripted/fake", temperature=0.0, **kwargs)
        self.responses = list(responses)
        self.calls = []

    def call(self, messages, tools=None, callbacks=None, available_functions=None,
              from_task=None, from_agent=None, response_model=None, **kwargs):
        idx = len(self.calls)
        if idx >= len(self.responses):
            raise AssertionError(
                f"ScriptedLLM exhausted after {idx} calls — test under-supplied canned responses"
            )
        resp = self.responses[idx]
        self.calls.append(resp)
        return resp

    def supports_function_calling(self) -> bool:
        return False

    def supports_stop_words(self) -> bool:
        return False


def run_with_scripts(raw_df, responses: list[str], *, workspace: Path):
    llm = ScriptedLLM(responses)
    result = run_analyst_crew(
        raw_df,
        run_id="test-run",
        dataset_name="telco_test_fixture",
        source_documentation_url="https://example.invalid/telco",
        workspace=workspace,
        llm=llm,
    )
    return result, llm


# ---------------------------------------------------------------------------
# Structural tests — no crew.kickoff() needed.
# ---------------------------------------------------------------------------


def test_pattern_a_structure(tmp_path: Path) -> None:
    df = tiny_raw_df()
    profile = profile_dataframe(df, target_column="Churn")
    ctx = Crew1RunContext(
        run_id="struct-test", dataset_name="x", source_documentation_url="https://x",
        business_context={}, source_documentation_excerpt="",
        clean_data_csv=tmp_path / "clean_data.csv", dataset_contract_json=tmp_path / "dataset_contract.json",
        eda_report_html=tmp_path / "eda_report.html", insights_md=tmp_path / "insights.md",
        internal_dir=tmp_path / "_internal", figures_dir=tmp_path / "figures",
        raw_df=df, raw_profile=profile,
    )
    from crewai import Process
    with crew1_run_context(ctx):
        crew = build_analyst_crew(ctx, llm=ScriptedLLM([]))
    check("test_pattern_a_structure: exactly 3 agents", len(crew.agents) == 3)
    check("test_pattern_a_structure: exactly 3 tasks", len(crew.tasks) == 3)
    check("test_pattern_a_structure: Process.sequential", crew.process == Process.sequential)
    t1, t2, t3 = crew.tasks
    check("test_pattern_a_structure: task1 output_pydantic == CleaningPlan", t1.output_pydantic is CleaningPlan)
    check("test_pattern_a_structure: task2 output_pydantic == InsightsDoc", t2.output_pydantic is InsightsDoc)
    check("test_pattern_a_structure: task3 output_pydantic == ContractDraft", t3.output_pydantic is ContractDraft)
    check("test_pattern_a_structure: task1 context == []", t1.context == [])
    check("test_pattern_a_structure: task2 context == [task1]", t2.context == [t1])
    check("test_pattern_a_structure: task3 context == [task1, task2]", t3.context == [t1, t2])
    for t in (t1, t2, t3):
        check(
            f"test_pattern_a_structure: {t.agent.role[:20]!r} guardrail_max_retries == {GUARDRAIL_MAX_RETRIES}",
            t.guardrail_max_retries == GUARDRAIL_MAX_RETRIES,
        )
        check(f"test_pattern_a_structure: {t.agent.role[:20]!r} guardrail is set", t.guardrail is not None)
        check(f"test_pattern_a_structure: {t.agent.role[:20]!r} callback is set", t.callback is not None)


# ---------------------------------------------------------------------------
# End-to-end (scripted LLM) — happy path.
# ---------------------------------------------------------------------------


def test_crew1_produces_artifacts(tmp_path: Path) -> None:
    workspace = tmp_path / "crew1"
    responses = [
        valid_cleaning_plan().model_dump_json(),
        valid_insights_doc().model_dump_json(),
        valid_contract_draft().model_dump_json(),
    ]
    result, llm = run_with_scripts(tiny_raw_df(), responses, workspace=workspace)

    check("test_crew1_produces_artifacts: status == completed", result.status == "completed", result.failure_message or "")
    check("test_crew1_produces_artifacts: clean_data.csv exists+non-empty", result.clean_data_csv.is_file() and result.clean_data_csv.stat().st_size > 0)
    check("test_crew1_produces_artifacts: eda_report.html exists+non-empty", result.eda_report_html.is_file() and result.eda_report_html.stat().st_size > 0)
    check("test_crew1_produces_artifacts: insights.md exists+non-empty", result.insights_md.is_file() and result.insights_md.stat().st_size > 0)
    check("test_crew1_produces_artifacts: dataset_contract.json exists+non-empty", result.dataset_contract_json.is_file() and result.dataset_contract_json.stat().st_size > 0)
    check("test_crew1_produces_artifacts: not degraded on the happy path", result.eda_degraded is False)
    check("test_crew1_produces_artifacts: exactly 3 LLM calls (no retries needed)", len(llm.calls) == 3)

    doc = result.ctx.insights_doc
    check("test_crew1_produces_artifacts: every insight evidence key is real", all(
        i.evidence_stat_key in result.ctx.eda_stats for i in doc.insights
    ))
    shutil.rmtree(workspace, ignore_errors=True)


def test_contract_matches_clean_data(tmp_path: Path) -> None:
    import hashlib

    workspace = tmp_path / "crew1"
    responses = [
        valid_cleaning_plan().model_dump_json(),
        valid_insights_doc().model_dump_json(),
        valid_contract_draft().model_dump_json(),
    ]
    result, _ = run_with_scripts(tiny_raw_df(), responses, workspace=workspace)
    check("test_contract_matches_clean_data: completed", result.status == "completed", result.failure_message or "")

    actual_sha256 = hashlib.sha256(result.clean_data_csv.read_bytes()).hexdigest()
    contract_sha256 = result.ctx.final_contract.integrity.clean_data_sha256
    check("test_contract_matches_clean_data: sha256 matches the actual clean_data.csv bytes", actual_sha256 == contract_sha256)

    # Bonus: the generated contract also passes the real Phase 4 gate.
    from harbor_vale.contract.validator import run_validation_gate

    report = run_validation_gate(
        result.clean_data_csv, result.dataset_contract_json, result.eda_report_html, result.insights_md,
        run_id="gate-check",
    )
    check(
        "test_contract_matches_clean_data: generated contract passes the Phase 4 gate",
        report.passed,
        f"errors={[f.message for f in report.findings if f.severity == 'ERROR']}",
    )
    shutil.rmtree(workspace, ignore_errors=True)


# ---------------------------------------------------------------------------
# Critical-agent failure — Agent 1 (Inspector).
# ---------------------------------------------------------------------------


def test_critical_agent_failure_halts(tmp_path: Path) -> None:
    workspace = tmp_path / "crew1"
    responses = [invalid_cleaning_plan_json()] * (GUARDRAIL_MAX_RETRIES + 1)  # always invalid, every attempt
    result, llm = run_with_scripts(tiny_raw_df(), responses, workspace=workspace)

    check("test_critical_agent_failure_halts: status == halted_agent_failure", result.status == "halted_agent_failure")
    check("test_critical_agent_failure_halts: failure_category == halted_agent_failure", result.failure_category == "halted_agent_failure")
    check("test_critical_agent_failure_halts: clean_data.csv was NOT created", not result.clean_data_csv.is_file())
    check("test_critical_agent_failure_halts: dataset_contract.json was NOT created", not result.dataset_contract_json.is_file())
    check("test_critical_agent_failure_halts: eda_report.html was NOT created", not result.eda_report_html.is_file())
    check("test_critical_agent_failure_halts: exactly guardrail_max_retries+1 LLM calls", len(llm.calls) == GUARDRAIL_MAX_RETRIES + 1)
    rejected_path = workspace / "_internal" / "rejected_cleaning_plan.json"
    check("test_critical_agent_failure_halts: rejected_cleaning_plan.json preserved under _internal/", rejected_path.is_file())
    shutil.rmtree(workspace, ignore_errors=True)


def test_critical_agent_failure_contract_architect_halts(tmp_path: Path) -> None:
    workspace = tmp_path / "crew1"
    responses = (
        [valid_cleaning_plan().model_dump_json()]
        + [valid_insights_doc().model_dump_json()]
        + [invalid_contract_draft_json()] * (GUARDRAIL_MAX_RETRIES + 1)
    )
    result, _ = run_with_scripts(tiny_raw_df(), responses, workspace=workspace)

    check("test_critical_agent_failure_contract_architect_halts: status == halted_agent_failure", result.status == "halted_agent_failure")
    check("test_critical_agent_failure_contract_architect_halts: dataset_contract.json was NOT created", not result.dataset_contract_json.is_file())
    check("test_critical_agent_failure_contract_architect_halts: clean_data.csv WAS created (Task 1 succeeded)", result.clean_data_csv.is_file())
    check("test_critical_agent_failure_contract_architect_halts: eda_report.html WAS created (Task 2 succeeded)", result.eda_report_html.is_file())
    rejected_path = workspace / "_internal" / "rejected_contract_draft.json"
    check("test_critical_agent_failure_contract_architect_halts: rejected_contract_draft.json preserved under _internal/", rejected_path.is_file())
    shutil.rmtree(workspace, ignore_errors=True)


# ---------------------------------------------------------------------------
# Narrative fallback — Agent 2 (EDA & Insights Analyst).
# ---------------------------------------------------------------------------


def test_narrative_fallback_is_visible(tmp_path: Path) -> None:
    workspace = tmp_path / "crew1"
    responses = (
        [valid_cleaning_plan().model_dump_json()]
        + [invalid_insights_doc_json()] * (GUARDRAIL_MAX_RETRIES + 1)  # always semantically invalid
        + [valid_contract_draft().model_dump_json()]
    )
    result, llm = run_with_scripts(tiny_raw_df(), responses, workspace=workspace)

    check("test_narrative_fallback_is_visible: status == completed (NOT halted)", result.status == "completed", result.failure_message or "")
    check("test_narrative_fallback_is_visible: eda_degraded == True", result.eda_degraded is True)
    check("test_narrative_fallback_is_visible: eda_degraded_reason is set", bool(result.eda_degraded_reason))

    eda_html = result.eda_report_html.read_text(encoding="utf-8")
    insights_md = result.insights_md.read_text(encoding="utf-8")
    banner = "Narrative unavailable"
    check("test_narrative_fallback_is_visible: degraded banner visible in eda_report.html", banner in eda_html)
    check("test_narrative_fallback_is_visible: degraded banner visible in insights.md", banner in insights_md)
    # The rejected insight's own TITLE must never render as if it were
    # accepted content — the degraded banner's "Reason:" line legitimately
    # quotes the guardrail's rejection message (which names the fabricated
    # key), but the fabricated insight's narrative body must never appear.
    check(
        "test_narrative_fallback_is_visible: fabricated insight content NOT rendered as accepted narrative",
        "## Made up" not in insights_md,
    )

    check(
        "test_narrative_fallback_is_visible: Agent 3 (Contract Architect) still ran",
        result.dataset_contract_json.is_file() and result.dataset_contract_json.stat().st_size > 0,
    )
    check(
        "test_narrative_fallback_is_visible: exactly 3 + (guardrail_max_retries+1) LLM calls",
        len(llm.calls) == 1 + (GUARDRAIL_MAX_RETRIES + 1) + 1,
    )
    shutil.rmtree(workspace, ignore_errors=True)


def test_contract_architect_prompt_covers_feature_curation(tmp_path: Path) -> None:  # noqa: ARG001
    """Phase 6 quality close-out (Session 24): protects the PROMPT CONTRACT
    text itself, not LLM reasoning quality — a canned "the agent got it
    right" fixture would prove nothing about a real run. This only asserts
    that `config/tasks.yaml`'s Contract Architect task actually contains
    the guidance a live run relies on: that an identifier must be
    hard-excluded and never required, that `required_features` is a
    curated subset (not every non-target column), and that redundancy is
    not automatically leakage — grounded in the real Run 1/Run 2 evidence
    (`working flow/2026-09-15_session-23.md`, session 24's own record)."""
    from harbor_vale.crews.analyst_crew.analyst_crew import _TASKS_YAML, _load_yaml

    raw = _load_yaml(_TASKS_YAML)["contract_architect_task"]["description"]
    # YAML's `>` folding does not fold newlines inside a more-indented block
    # (this task's numbered list) — normalize whitespace so this test
    # checks CONTENT, not incidental line-wrapping.
    description = " ".join(raw.split())

    check(
        "prompt: identifier must be hard-excluded, per this run's ACTUAL column name",
        "identifier" in description.lower() and "hard" in description,
    )
    check(
        "prompt: identifier must NOT also appear in required_features",
        "MUST NOT" in description and "required_features" in description,
    )
    check(
        "prompt: required_features framed as a curated subset, not every non-target column",
        "curated subset" in description.lower(),
    )
    check(
        "prompt: redundancy/correlation explicitly distinguished from leakage",
        "redundancy_collinearity" in description and "never leakage" in description,
    )
    # `customer_id` may appear ONLY as STEP 3's explicit negative example
    # ("do NOT invent `customer_id` merely because...") — never asserted
    # elsewhere as if it were the expected/correct spelling.
    check(
        "prompt: `customer_id` appears at most once, and only as a forbidden-guess example",
        description.count("customer_id") <= 1
        and ("customer_id" not in description or "invent `customer_id`" in description),
    )

    # --- Session 25 (final Phase 6 verification): the grounding rule ----
    check(
        "prompt: explicit rule that every column name must be grounded in the ACTUAL profile",
        "character-for-character" in description and "profile_clean_dataset" in description,
    )
    check(
        "prompt: explicit two-case identifier handling (present -> hard exclude; absent -> do not mention)",
        "Case A" in description and "Case B" in description,
    )
    check(
        "prompt: Case B explicitly forbids inventing/recreating a dropped identifier anywhere",
        "do NOT invent or recreate" in raw,
    )

    # --- Session 26 (Contract Architect grounding, second corrective iteration) ---
    check(
        "prompt: STEP 1 requires reading the accepted CleaningPlan to find drop_column'd columns",
        "STEP 1" in description and "drop_column" in description and "CleaningPlan" in description,
    )
    check(
        "prompt: STEP 2 names profile_clean_dataset as the SOLE authoritative vocabulary",
        "STEP 2" in description and "ONE AND ONLY authoritative vocabulary" in description,
    )
    check(
        "prompt: STEP 3 explicitly bans reconstructing snake_case from a raw/PascalCase name",
        "reconstruct a snake_case spelling from a raw" in description,
    )
    check(
        "prompt: STEP 3 explicitly bans reconstructing PascalCase/raw from a canonical name",
        "reconstruct a PascalCase/raw spelling from a canonical name" in description,
    )
    check(
        "prompt: STEP 3 explicitly bans reusing a source-documentation name cleaning removed",
        "reuse a name from `read_source_documentation`" in description,
    )
    check(
        "prompt: primary_key given honest-not-unique guidance for Case B, not a forced fabrication",
        "unique.value" in description and "fabricated identifier" in description,
    )


def test_eda_figure_resolution_is_naming_agnostic(tmp_path: Path) -> None:  # noqa: ARG001
    """Phase 6 quality close-out (Session 24): the deterministic EDA-figure
    column resolution (`callbacks.py`) must find the right columns whether
    the Inspector agent renamed them to canonical snake_case, left them in
    raw PascalCase (the real Run 2 behavior), or used some other casing —
    never silently produce zero figures the way the original Run 2 render
    did (root-caused and fixed this session)."""
    from harbor_vale.crews.analyst_crew.callbacks import (
        _DISTRIBUTION_FIGURE_CANDIDATES,
        _TARGET_RATE_FIGURE_CANDIDATES,
        _resolve_column,
    )

    for columns, expected in (
        (["Contract", "PaymentMethod", "MonthlyCharges", "churn"], {"Contract", "PaymentMethod", "MonthlyCharges"}),
        (
            ["contract_type", "payment_method", "monthly_charges", "churn"],
            {"contract_type", "payment_method", "monthly_charges"},
        ),
    ):
        resolved = {
            c for c in (_resolve_column(columns, *slot) for slot in _TARGET_RATE_FIGURE_CANDIDATES) if c
        }
        resolved |= {_resolve_column(columns, *_DISTRIBUTION_FIGURE_CANDIDATES)}
        check(
            f"figure resolution finds all 3 real columns regardless of naming style ({columns[:2]})",
            resolved == expected,
            f"resolved={resolved}",
        )


ALL_TESTS = [
    test_pattern_a_structure,
    test_crew1_produces_artifacts,
    test_contract_matches_clean_data,
    test_critical_agent_failure_halts,
    test_critical_agent_failure_contract_architect_halts,
    test_narrative_fallback_is_visible,
    test_contract_architect_prompt_covers_feature_curation,
    test_eda_figure_resolution_is_naming_agnostic,
]


def main() -> int:
    import tempfile

    for fn in ALL_TESTS:
        with tempfile.TemporaryDirectory() as td:
            try:
                fn(Path(td))
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
