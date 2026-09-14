"""Builds tests/fixtures/contract_example.json from telco_contract_fixture.csv.

Run manually to regenerate the example (not part of any test run itself —
tests read the already-committed JSON, or call the builder directly on the
fixture CSV). This script plays the role a validated `ContractDraft` from
the (not-yet-built) Data Contract Architect agent would play in Phase 6+:
every semantic judgement below is hand-written here, with the same
justification requirements the real guardrail will enforce on an agent's
output.

Usage:
    python tests/fixtures/build_example_contract.py
"""

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale.contract.builder import build_contract  # noqa: E402
from harbor_vale.contract.schema import (  # noqa: E402
    BusinessRangeConstraint,
    ClosedDomainConstraint,
    DtypeConstraint,
    EnforcementLevel,
    ExcludedFeature,
    ExclusionType,
    NullableConstraint,
    ScaleDriftConstraint,
    SemanticType,
    UnitConstraint,
    UniqueConstraint,
)
from harbor_vale.plans.contract_draft import (  # noqa: E402
    ColumnSemanticDraft,
    ContractDraft,
    PrimaryKeyDraft,
    TargetDraft,
    validate_contract_draft,
)

FIXTURE_CSV = Path(__file__).parent / "telco_contract_fixture.csv"
OUTPUT_JSON = Path(__file__).parent / "contract_example.json"

_YES_NO = ["Yes", "No"]
_YES_NO_JUSTIFICATION = "every account has an explicit yes/no value for this attribute"


def _yes_no_column(name: str, semantic_type: SemanticType) -> ColumnSemanticDraft:
    return ColumnSemanticDraft(
        name=name,
        semantic_type=semantic_type,
        nullable=NullableConstraint(value=False, justification=_YES_NO_JUSTIFICATION),
        closed_domain=ClosedDomainConstraint(
            values=_YES_NO,
            justification="the source represents this attribute as a binary yes/no flag",
        ),
    )


def _tri_state_service_column(name: str, gate: str) -> ColumnSemanticDraft:
    """A column that reads Yes/No/'No {gate} service' (data/README.md §7.2)."""
    return ColumnSemanticDraft(
        name=name,
        semantic_type=SemanticType.CATEGORICAL,
        nullable=NullableConstraint(
            value=False, justification="every account has a value for this add-on, even if structurally N/A"
        ),
        closed_domain=ClosedDomainConstraint(
            values=["Yes", "No", f"No {gate} service"],
            justification=(
                f"the provider's catalogue defines exactly these three states for an "
                f"add-on that depends on {gate} service; a new value would mean the "
                f"product catalogue changed"
            ),
        ),
    )


def build_draft() -> ContractDraft:
    columns = [
        ColumnSemanticDraft(
            name="customer_id",
            semantic_type=SemanticType.IDENTIFIER,
            nullable=NullableConstraint(value=False, justification="every row must identify a customer"),
        ),
        ColumnSemanticDraft(
            name="gender",
            semantic_type=SemanticType.CATEGORICAL,
            nullable=NullableConstraint(value=False, justification="every account records a gender"),
            closed_domain=ClosedDomainConstraint(
                values=["Male", "Female"],
                justification="the source represents gender as exactly these two values",
            ),
        ),
        _yes_no_column("partner", SemanticType.BINARY),
        _yes_no_column("dependents", SemanticType.BINARY),
        ColumnSemanticDraft(
            name="senior_citizen",
            semantic_type=SemanticType.BINARY,
            dtype=DtypeConstraint(expected="int64", justification="source encodes this flag as 0/1, not Yes/No"),
            nullable=NullableConstraint(value=False, justification="every account states this demographic flag"),
            closed_domain=ClosedDomainConstraint(
                values=["0", "1"], justification="binary flag by construction"
            ),
        ),
        ColumnSemanticDraft(
            name="tenure_months",
            semantic_type=SemanticType.NUMERIC,
            dtype=DtypeConstraint(expected="int64", justification="a whole number of months"),
            unit=UnitConstraint(
                value="months",
                evidence="IBM Community documentation states this column is 'Tenure in Months' (data/README.md §6.1)",
                confidence="high",
            ),
            nullable=NullableConstraint(value=False, justification="every account has a tenure, including 0 for brand-new customers"),
            business_range=BusinessRangeConstraint(
                min=0, max=None,
                justification="tenure cannot be negative; no defensible upper bound exists as the business relationship continues",
            ),
        ),
        _yes_no_column("phone_service", SemanticType.BINARY),
        ColumnSemanticDraft(
            name="multiple_lines",
            semantic_type=SemanticType.CATEGORICAL,
            nullable=NullableConstraint(value=False, justification="every account has a value for this attribute"),
            closed_domain=ClosedDomainConstraint(
                values=["Yes", "No", "No phone service"],
                justification="depends structurally on phone_service; the provider's catalogue defines exactly these three states",
            ),
        ),
        ColumnSemanticDraft(
            name="internet_service",
            semantic_type=SemanticType.CATEGORICAL,
            nullable=NullableConstraint(value=False, justification="every account has an internet service state"),
            closed_domain=ClosedDomainConstraint(
                values=["DSL", "Fiber optic", "No"],
                justification="the provider offers exactly these three internet service tiers",
            ),
        ),
        _tri_state_service_column("online_security", "internet"),
        _tri_state_service_column("online_backup", "internet"),
        _tri_state_service_column("device_protection", "internet"),
        _tri_state_service_column("tech_support", "internet"),
        _tri_state_service_column("streaming_tv", "internet"),
        _tri_state_service_column("streaming_movies", "internet"),
        ColumnSemanticDraft(
            name="contract_type",
            semantic_type=SemanticType.CATEGORICAL,
            nullable=NullableConstraint(value=False, justification="every account has a contract type"),
            closed_domain=ClosedDomainConstraint(
                values=["Month-to-month", "One year", "Two year"],
                justification="the provider offers exactly these three contract terms; a new value means the product catalogue changed",
            ),
        ),
        _yes_no_column("paperless_billing", SemanticType.BINARY),
        ColumnSemanticDraft(
            name="payment_method",
            semantic_type=SemanticType.CATEGORICAL,
            nullable=NullableConstraint(value=False, justification="every account has a payment method on file"),
            closed_domain=ClosedDomainConstraint(
                values=[
                    "Electronic check", "Mailed check",
                    "Bank transfer (automatic)", "Credit card (automatic)",
                ],
                justification="the provider supports exactly these four payment channels",
            ),
        ),
        ColumnSemanticDraft(
            name="monthly_charges",
            semantic_type=SemanticType.MONETARY,
            dtype=DtypeConstraint(expected="float64", justification="continuous monetary-like amount"),
            unit=UnitConstraint(
                value="currency_unspecified",
                evidence="the source documentation does not state a currency (data/README.md §6.2)",
                confidence="low",
            ),
            nullable=NullableConstraint(value=False, justification="every active account has a recurring charge"),
            business_range=BusinessRangeConstraint(
                min=0, max=None,
                justification="a recurring charge cannot be negative; no defensible upper bound exists — a future premium plan may legitimately exceed the observed maximum",
            ),
            scale_drift=ScaleDriftConstraint(
                median_rel_tolerance=0.25,
                justification="this column is scale-sensitive; a large shift in central tendency indicates a unit or scale change rather than natural variation",
            ),
        ),
        ColumnSemanticDraft(
            name="total_charges",
            semantic_type=SemanticType.MONETARY,
            dtype=DtypeConstraint(expected="float64", justification="continuous cumulative monetary amount"),
            unit=UnitConstraint(
                value="currency_unspecified",
                evidence="same undocumented-currency source as monthly_charges (data/README.md §6.2)",
                confidence="low",
            ),
            nullable=NullableConstraint(value=False, justification="every account has an accumulated total, 0 for brand-new customers"),
            business_range=BusinessRangeConstraint(
                min=0, max=None,
                justification="cumulative billing cannot be negative; no upper bound is defensible",
            ),
        ),
    ]

    target = TargetDraft(
        name="churn",
        task_type="binary_classification",
        dtype=DtypeConstraint(expected="int64", justification="binary label by construction"),
        closed_domain=ClosedDomainConstraint(values=["0", "1"], justification="binary label by construction"),
        nullable=NullableConstraint(value=False, justification="a row without a label is unusable for training"),
    )

    return ContractDraft(
        target=target,
        required_features=["tenure_months", "monthly_charges", "contract_type", "internet_service"],
        excluded_features=[
            ExcludedFeature(
                name="customer_id",
                exclusion_type=ExclusionType.IDENTIFIER,
                enforcement=EnforcementLevel.HARD,
                justification="a unique key carries no generalizable signal",
            ),
            ExcludedFeature(
                name="total_charges",
                exclusion_type=ExclusionType.REDUNDANCY_COLLINEARITY,
                enforcement=EnforcementLevel.ADVISORY,
                justification=(
                    "approximately tenure_months x monthly_charges (r=0.9996 on the real "
                    "Phase 2 dataset, data/README.md §6.3). It IS available at prediction "
                    "time, so this is NOT leakage — it is redundancy. The Feature Engineer "
                    "may include it with justification."
                ),
            ),
        ],
        primary_key=PrimaryKeyDraft(
            columns=["customer_id"],
            unique=UniqueConstraint(value=True, justification="one row per customer"),
        ),
        columns=columns,
        assumptions=[
            "one row per customer; customer_id is unique",
            "the currency of monetary columns is NOT documented in the source; only relative scale is contracted",
            "churn refers to the observation snapshot; no future information is encoded",
            "total_charges is a redundant, non-leakage snapshot feature (data/README.md §6.3)",
        ],
    )


def main() -> int:
    draft = build_draft()
    ok, result = validate_contract_draft(draft)
    if not ok:
        print(f"ERROR: draft failed the guardrail: {result}", file=sys.stderr)
        return 1

    contract = build_contract(
        result,
        FIXTURE_CSV,
        contract_version="1.0.0",
        run_id="example-fixture-run",
        created_by="tests.fixtures.build_example_contract",
        dataset_name="telco_customer_churn",
        source_documentation_url="https://github.com/IBM/telco-customer-churn-on-icp4d",
    )

    OUTPUT_JSON.write_text(
        json.dumps(json.loads(contract.model_dump_json()), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(f"OK: wrote {OUTPUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
