"""Hardcoded, defensible plans for the Phase 5 no-LLM end-to-end proof
(PROJECT_PLAN.md §T Phase 5 acceptance: "פייפליין מלא רץ end-to-end עם
תוכניות hardcoded, בלי LLM").

**Not agent output.** Every plan here is hand-written, exactly the role a
real, already-guardrail-approved agent output would play once Phase 6+
exists — this module plays that role today, deterministically, so the
Phase 5 deterministic execution layer can be proven end-to-end before any
agent is connected.

Every cleaning decision is grounded in `data/README.md`'s Phase 2 measured
evidence (§6, §7) — nothing invented merely to exercise an operation. The
canonical column names reuse the exact set `tests/fixtures/build_example_contract.py`'s
`build_draft()` already declares, so the SAME already-tested `ContractDraft`
serves as this module's hardcoded contract draft too — no second, divergent
draft was written.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale.plans.cleaning_plan import (  # noqa: E402
    CastOp,
    CleaningPlan,
    ImputeOp,
    RenameOp,
    StandardizeCategoryOp,
)
from harbor_vale.plans.experiment_plan import ExperimentPlan, ExperimentVariant  # noqa: E402
from harbor_vale.plans.feature_plan import (  # noqa: E402
    ContractAcknowledgment,
    EncoderSpec,
    FeaturePlan,
    TransformSpec,
)
from harbor_vale.plans.insights_doc import Insight, InsightsDoc  # noqa: E402

# The raw Telco source column -> canonical snake_case name mapping
# (data/README.md §6.5) — reused verbatim by both the hardcoded
# CleaningPlan and by anything that needs to know the mapping.
RAW_TO_CANONICAL_COLUMN_MAP: dict[str, str] = {
    "customerID": "customer_id",
    "SeniorCitizen": "senior_citizen",
    "Partner": "partner",
    "Dependents": "dependents",
    "tenure": "tenure_months",
    "PhoneService": "phone_service",
    "MultipleLines": "multiple_lines",
    "InternetService": "internet_service",
    "OnlineSecurity": "online_security",
    "OnlineBackup": "online_backup",
    "DeviceProtection": "device_protection",
    "TechSupport": "tech_support",
    "StreamingTV": "streaming_tv",
    "StreamingMovies": "streaming_movies",
    "Contract": "contract_type",
    "PaperlessBilling": "paperless_billing",
    "PaymentMethod": "payment_method",
    "MonthlyCharges": "monthly_charges",
    "TotalCharges": "total_charges",
    "Churn": "churn",
    # "gender" is already canonical (lower-case, single word) — no rename.
}


def build_hardcoded_cleaning_plan() -> CleaningPlan:
    """The real Telco cleaning plan, grounded entirely in
    `data/README.md`'s measured Phase 2 evidence:

    - Every column renamed to its documented canonical name (§6.5) —
      including `Contract` -> `contract_type` (this project's own
      established naming precedent from the already-merged Phase 3
      `ContractDraft` fixture, chosen there to avoid a column literally
      named `contract`, which would collide with this project's own
      "dataset contract" terminology; §6.5's generic "snake_case of the
      original name" rule alone would have given plain `contract`).
    - `total_charges` cast to `float64` then imputed with `0.0` — §7.1's
      exact documented issue: 11 blank-placeholder rows (`tenure_months
      == 0`, brand-new customers with no completed billing cycle),
      which `pd.to_numeric(errors="coerce")` turns into `NaN` for the
      subsequent `impute` to fill.
    - `churn` remapped `"Yes"/"No"` -> `"1"/"0"` then cast to `int64` — a
      binary target encoding, matching the already-built Phase 3 contract's
      declared `dtype=int64, closed_domain=["0","1"]` for the target.

    Deliberately does NOT touch the seven "No {gate} service" tri-state
    columns (§7.2) or `senior_citizen`'s int64 encoding (§7.3) — the
    already-merged Phase 3 `ContractDraft` treats both as legitimate,
    declared states (a 3-value closed domain; an explicit `int64` dtype
    constraint), not defects to clean away. Collapsing them here would
    silently change Phase 2/3's semantic conclusions, which this task is
    explicitly not allowed to do.
    """
    operations = [
        RenameOp(old_name=old, new_name=new, reason="canonical name per data/README.md §6.5")
        for old, new in RAW_TO_CANONICAL_COLUMN_MAP.items()
    ]
    operations += [
        CastOp(
            column="total_charges",
            target_dtype="float64",
            reason=(
                "TotalCharges loads as text because of 11 blank-placeholder rows "
                "(data/README.md §7.1); numeric coercion turns those into NaN"
            ),
        ),
        ImputeOp(
            column="total_charges",
            strategy="constant",
            value=0.0,
            reason=(
                "the 11 blank rows are brand-new customers with tenure_months == 0 and "
                "no completed billing cycle yet (data/README.md §7.1) — 0 is the correct value"
            ),
        ),
        StandardizeCategoryOp(
            column="churn",
            mapping={"Yes": "1", "No": "0"},
            reason="binary target label encoding, matching the contract's declared int64/closed_domain",
        ),
        CastOp(
            column="churn",
            target_dtype="int64",
            reason="binary label as int64, matching the contract's declared dtype",
        ),
    ]
    return CleaningPlan(operations=operations)


def build_hardcoded_insights_doc(eda_stats: dict) -> InsightsDoc:
    """A defensible `InsightsDoc`, every `evidence_stat_key` a REAL key
    `compute_eda_stats()` produces on the real cleaned Telco data (verified
    directly against a real run before being hardcoded here — see
    `working flow/` Phase 5 session record for the exact keys/values
    observed). Content mirrors data/README.md's own already-documented
    observations (month-to-month churn risk, the undocumented-currency
    caveat) — nothing invented beyond what Phase 2 already established.
    """
    return InsightsDoc(
        headline="Contract type is the strongest observed churn signal in the Telco data",
        insights=[
            Insight(
                title="Month-to-month customers churn at roughly 4x the rate of two-year customers",
                observation=(
                    "The measured churn rate for month-to-month customers is far higher than "
                    "for one-year or two-year contract customers in this dataset."
                ),
                business_implication=(
                    "Contract length is a strong retention lever — locking customers into "
                    "longer terms correlates with much lower observed churn."
                ),
                recommended_action=(
                    "Prioritize incentives that move month-to-month customers toward annual "
                    "or two-year contracts before pursuing more expensive retention offers."
                ),
                evidence_stat_key="contract_type.target_rate_by_category.Month-to-month",
            ),
            Insight(
                title="Electronic check payers churn more than customers on other payment methods",
                observation=(
                    "Customers paying by electronic check show a measurably higher churn rate "
                    "than those on automatic bank transfer, automatic credit card, or mailed check."
                ),
                business_implication=(
                    "Payment friction (a manual, non-automatic payment method) co-occurs with "
                    "higher churn — plausibly a proxy for lower engagement with the service overall."
                ),
                recommended_action=(
                    "Consider incentivizing enrollment in automatic payment methods as a "
                    "low-cost retention signal to monitor, not a proven causal lever."
                ),
                evidence_stat_key="payment_method.target_rate_by_category.Electronic check",
            ),
        ],
        data_caveats=[
            "monthly_charges' currency is not documented in the source data "
            "(data/README.md §6.2/§11) — all monetary comparisons here are relative, not "
            "denominated in any specific currency.",
            "These are observed associations, not causal claims — no experiment was run.",
        ],
    )


def build_hardcoded_feature_plan(contract) -> FeaturePlan:  # noqa: ANN001 — DatasetContract, avoids an import cycle in type-checking-only contexts
    """A defensible `FeaturePlan` for the real, cleaned Telco data. Uses
    every `required_features` entry, adds a modest set of additional
    signal columns, log-transforms the right-skewed `monthly_charges`
    column (§G.1 point 2: "log על מוטה"), one-hot encodes the categorical
    columns it uses, and takes `total_charges` under an explicit advisory
    override (data/README.md §6.3: redundant with `tenure_months` ×
    `monthly_charges`, r=0.9996, but legitimately available at prediction
    time — not leakage)."""
    use_features = list(contract.required_features) + [
        "senior_citizen",
        "partner",
        "dependents",
        "payment_method",
        "paperless_billing",
        "total_charges",
    ]
    return FeaturePlan(
        contract_acknowledgment=ContractAcknowledgment(
            contract_version=contract.contract_version,
            target_confirmed=True,
            required_features_confirmed=True,
            excluded_features_respected=["customer_id"],
            constraints_relied_upon=[
                "monthly_charges.constraints.scale_drift (relied upon indirectly via the gate)",
                "total_charges is redundancy_collinearity, not target_leakage (data/README.md §6.3)",
            ],
        ),
        use_features=use_features,
        transforms=[TransformSpec(column="monthly_charges", kind="log1p")],
        encoders=[
            EncoderSpec(column="contract_type", kind="onehot"),
            EncoderSpec(column="internet_service", kind="onehot"),
            EncoderSpec(column="payment_method", kind="onehot"),
            EncoderSpec(column="partner", kind="onehot"),
            EncoderSpec(column="dependents", kind="onehot"),
            EncoderSpec(column="paperless_billing", kind="onehot"),
        ],
        advisory_overrides=[
            {
                "column": "total_charges",
                "justification": (
                    "redundant with tenure_months x monthly_charges (r=0.9996) but legitimately "
                    "available at prediction time — not leakage (data/README.md §6.3)"
                ),
            }
        ],
    )


def build_hardcoded_experiment_plan() -> ExperimentPlan:
    """The Plan's intentionally frozen 3-variant set (§G.2): logistic
    regression (interpretable baseline, `class_weight='balanced'`),
    random forest, gradient boosting. No hyperparameter tuning — every
    param value here is a plain, defensible default, not a searched
    optimum."""
    return ExperimentPlan(
        primary_metric="roc_auc",
        metric_rationale=(
            "churn is imbalanced (~26.5% positive, data/README.md §6.4); accuracy would be "
            "misleading, and missing a genuine churner is costlier than a false alarm — "
            "ROC-AUC measures ranking quality independent of the classification threshold"
        ),
        cv_folds=5,
        variants=[
            ExperimentVariant(
                name="logistic_regression_baseline",
                estimator="logistic_regression",
                params={"C": 1.0, "class_weight": "balanced", "max_iter": 1000},
                rationale="interpretable linear baseline, class-weighted for the imbalance",
            ),
            ExperimentVariant(
                name="random_forest_default",
                estimator="random_forest",
                params={"n_estimators": 200, "max_depth": 10, "class_weight": "balanced"},
                rationale="captures non-linear feature interactions without manual engineering",
            ),
            ExperimentVariant(
                name="gradient_boosting_default",
                estimator="gradient_boosting",
                params={"n_estimators": 150, "learning_rate": 0.1, "max_depth": 3},
                rationale="often strong on tabular data; compares boosting against bagging (random forest)",
            ),
        ],
    )
