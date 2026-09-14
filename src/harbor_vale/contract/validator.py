"""The deterministic Validation Gate (PROJECT_PLAN.md §F).

**The sole future authority for contract PASS/FAIL.** Zero LLM calls, zero
`Agent`/`Task`/`Crew`/`Flow` definitions — `import pandas, json, hashlib` and
nothing else. Any future Flow routing decision reads `ValidationReport.passed`
from this module; it never re-derives or second-guesses it.

**The decision rule (§F.2, exact):** ``passed = (errors == 0)``. `WARN`
findings never fail the gate. The gate runs **every** applicable check and
collects **every** finding — it does not stop at the first `ERROR`, because
the point of a real incident report is the complete failure picture, not the
first symptom.

**The central invariant carried over from Phase 3 (§E.1 rule 3, proven in
`tests/unit/test_observed_not_enforced.py`): `observed` != `constraints`.**
This module enforces only what a `ContractDraft` explicitly declared with a
justification — `column.observed.max` is descriptive history, never an
implicit ceiling. A candidate value above `observed.max` with no declared
`business_range.max` is not, and must never become, a violation.

## Check-family vocabulary (§F.1)

Exactly the seven families the Plan enumerates —
``artifacts | schema | target | constraints | scale_drift | integrity | modeling``
— no others invented.

## `check_id` vocabulary

The Plan specifies families, not exact IDs (§F.1 note: "היכן שהתוכנית
מציינת רק משפחות ולא IDs מדויקים, בחר שמות יציבים וברורים ותעד"). This module
defines the following **stable** identifiers. Future fault-injection /
integration tests are expected to assert against these exact strings.

| `check_id` | family | meaning |
|---|---|---|
| `ARTIFACTS_CONTRACT_FILE_EXISTS` | artifacts | `dataset_contract.json` exists on disk |
| `ARTIFACTS_CONTRACT_FILE_NOT_EMPTY` | artifacts | it has non-zero byte size |
| `ARTIFACTS_CONTRACT_JSON_PARSES` | artifacts | its bytes are valid JSON |
| `ARTIFACTS_CONTRACT_SCHEMA_VALID` | artifacts | the parsed JSON validates against `DatasetContract` |
| `ARTIFACTS_CSV_FILE_EXISTS` | artifacts | `clean_data.csv` (or the candidate CSV path given) exists |
| `ARTIFACTS_CSV_FILE_NOT_EMPTY` | artifacts | it has non-zero byte size |
| `ARTIFACTS_CSV_LOADS` | artifacts | `pandas.read_csv` succeeds on it |
| `ARTIFACTS_EDA_REPORT_EXISTS` | artifacts | `eda_report.html` exists on disk (existence/size ONLY — content never read) |
| `ARTIFACTS_EDA_REPORT_NOT_EMPTY` | artifacts | it has non-zero byte size |
| `ARTIFACTS_INSIGHTS_MD_EXISTS` | artifacts | `insights.md` exists on disk (existence/size ONLY — content never read) |
| `ARTIFACTS_INSIGHTS_MD_NOT_EMPTY` | artifacts | it has non-zero byte size |
| `SCHEMA_MISSING_COLUMN` | schema | a contract-declared (non-target) column is absent from the CSV |
| `SCHEMA_UNKNOWN_COLUMN` | schema | a CSV column the contract never declared |
| `SCHEMA_COLUMN_ORDER` | schema | the CSV's column order differs from `integrity.column_order` |
| `SCHEMA_DTYPE_COMPATIBLE` | schema | measured dtype vs. `constraints.dtype.expected`, only where declared |
| `TARGET_COLUMN_PRESENT` | target | the target column exists in the CSV |
| `TARGET_NO_NULLS` | target | zero nulls, only if `target.constraints.nullable.value is False` |
| `TARGET_CLOSED_DOMAIN` | target | every value ⊆ the declared set, only if declared |
| `TARGET_AT_LEAST_TWO_CLASSES` | target | the target has ≥2 distinct non-null values (unconditional) |
| `TARGET_POSITIVE_RATE_DRIFT` | target | candidate positive rate vs. contract snapshot, only if `target.drift` declared |
| `CONSTRAINTS_NULLABLE` | constraints | zero nulls, only if `constraints.nullable.value is False` |
| `CONSTRAINTS_BUSINESS_RANGE` | constraints | value within `[min, max]`, only where declared bounds exist |
| `CONSTRAINTS_CLOSED_DOMAIN` | constraints | every value ⊆ the declared set, only if declared |
| `CONSTRAINTS_PRIMARY_KEY_UNIQUE` | constraints | no duplicate `primary_key.columns` tuples, only if declared unique |
| `SCALE_DRIFT_MEDIAN` | scale_drift | §E.3 median-ratio check, only for columns with a declared `scale_drift` policy |
| `SCALE_DRIFT_ROW_COUNT` | scale_drift | informational: measured row count vs. `integrity.row_count` |
| `INTEGRITY_SHA256_MATCH` | integrity | sha256 of the **actual candidate CSV bytes** vs. `integrity.clean_data_sha256` |
| `MODELING_MIN_ROWS` | modeling | measured row count ≥ `_MIN_ROWS_FOR_MODELING` |
| `MODELING_MIN_FEATURES` | modeling | non-hard-excluded declared columns ≥ `_MIN_USABLE_FEATURES` |
| `MODELING_CONSTANT_REQUIRED_FEATURE` | modeling | a `required_features` column with ≤1 distinct observed value |

## Prerequisite gating (why family A can end the run early)

Families B–G all need a **successfully parsed** `DatasetContract` and a
**successfully loaded** `DataFrame` — there is no way to check "is column X's
dtype compatible" against a contract that failed to parse, or a CSV that
failed to load. So: **family A always runs to completion** (every artifact
check it can attempt, never stopping at the first artifact failure), and
**only if both the contract and the CSV came out usable** does the gate
proceed to B–G. This is a structural prerequisite, not the gate "stopping at
the first failure" — within every family that *does* run, every applicable
check still runs and every finding is still collected.

## The four Crew 1 artifacts, and the Crew 2 boundary (§F.1, §G.0)

§F.1 Family A requires all **four** Crew 1 artifacts present/non-empty —
`clean_data.csv`, `dataset_contract.json`, `eda_report.html`, `insights.md` —
not just the two the gate parses and validates semantically. `run_validation_gate`
therefore takes all four as explicit paths; the caller (eventually a Flow,
§H, not built yet) is expected to pass `io_paths.EDA_REPORT_HTML` /
`io_paths.INSIGHTS_MD` alongside the handoff pair.

**This does not widen the Crew 1 → Crew 2 handoff boundary (§G.0).** The two
narrative artifacts get **existence + non-empty size checks only** — their
*content* is never opened, parsed, or read into anything this module
returns (`ValidationFinding`/`ValidationReport` never carry their bytes or
text). The validation gate is Flow-layer Python, not Crew 2's tool surface —
it runs *between* Crew 1 and Crew 2, and already necessarily has filesystem
access to everything Crew 1 produced (it has to, to check the four artifacts
exist at all). The boundary this module must never cross is a different
one: handing Crew 2's own tools (Phase 5's `access/allowlist.py` /
`access/handoff.py`, not built yet) a path to `eda_report.html` or
`insights.md` — which nothing here does, has ever done, or takes as an
input to anything but these four `ARTIFACTS_*` checks.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from harbor_vale.contract.schema import DatasetContract, EnforcementLevel
from harbor_vale.logging_setup import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Deterministic, documented thresholds (§F.1 "כשירות מודלינג" gives no exact
# number — the Plan asks for "sufficient rows" / "≥2 features" without a
# figure). Chosen once, here, and never inferred per-dataset — the same
# discipline `builder.py`'s `_MAX_VALUE_DISTRIBUTION_CARDINALITY` documents.
# ---------------------------------------------------------------------------

_MIN_ROWS_FOR_MODELING = 20
"""Below this row count, a train/holdout split cannot be meaningful. The
Phase 3 test fixture (`tests/fixtures/telco_contract_fixture.csv`) has 30
rows specifically so it passes this with margin; `truncate_dataset` (§O.3)
truncates below it on purpose."""

_MIN_USABLE_FEATURES = 2
"""§F.1: "≥2 פיצ'רים". A usable feature = a declared (non-target) column that
is not `hard`-excluded. `advisory`-excluded columns still count — the Feature
Engineer (Phase 5+) may choose to use them."""

_SCALE_DRIFT_RATIO_HINT_TOLERANCE = 0.05
"""§E.3 pseudocode: `abs(ratio - h) / h < 0.05` — a candidate ratio within 5%
relative distance of a declared `scale_change_ratio_hints` value is reported
as that hint (e.g. "≈100×"), not just a raw uninterpreted ratio."""

CheckFamily = Literal[
    "artifacts", "schema", "target", "constraints", "scale_drift", "integrity", "modeling"
]
Severity = Literal["ERROR", "WARN", "INFO"]


# ---------------------------------------------------------------------------
# Output models (§F.2, Internal Gate 4A)
# ---------------------------------------------------------------------------


class ValidationFinding(BaseModel):
    """One check's result — only ever constructed for a non-passing check.

    A passing check is not represented as a `ValidationFinding` at all (there
    is no `severity="INFO, passed"` row for every one of the dozens of silent
    passes) — `ValidationReport.checks_run` is the count of everything
    evaluated; `findings` is the list of everything that was NOT a clean
    pass. `Severity` still includes `"INFO"` in case a future check family
    needs a non-blocking, non-warning informational entry; nothing in this
    module currently emits one.
    """

    model_config = ConfigDict(extra="forbid")

    check_id: str
    check_family: CheckFamily
    severity: Severity
    column: str | None = None
    message: str
    expected: Any = None
    observed: Any = None
    contract_justification: str | None = None


class ValidationReport(BaseModel):
    """§F.2. `passed`, `errors`, `warnings` are always derived from
    `findings` at construction time (`_finalize`, below) — never set
    independently, so the three numbers can never disagree with the list
    they summarize.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    passed: bool
    checks_run: int = Field(ge=0)
    errors: int = Field(ge=0)
    warnings: int = Field(ge=0)
    findings: list[ValidationFinding]
    contract_version: str | None
    fault_injection: str | None = None
    validated_at: datetime


# ---------------------------------------------------------------------------
# Internal accumulator — not part of the public API.
# ---------------------------------------------------------------------------


class _Collector:
    """Accumulates findings and a `checks_run` counter across every family.

    `record(passed=True, ...)` counts the check but appends nothing.
    `record(passed=False, ...)` counts the check and appends a
    `ValidationFinding`. This is the only place `ValidationFinding` objects
    are constructed, so every check family goes through the identical
    accounting path.
    """

    def __init__(self) -> None:
        self.checks_run = 0
        self.findings: list[ValidationFinding] = []

    def record(
        self,
        passed: bool,
        *,
        check_id: str,
        check_family: CheckFamily,
        severity: Severity = "ERROR",
        column: str | None = None,
        message: str = "",
        expected: Any = None,
        observed: Any = None,
        contract_justification: str | None = None,
    ) -> None:
        self.checks_run += 1
        level = {"ERROR": 40, "WARN": 30, "INFO": 20}[severity]
        if passed:
            logger.info("PASS  %-32s column=%s", check_id, column)
        else:
            logger.log(
                level,
                "%-5s %-32s column=%s :: %s",
                severity,
                check_id,
                column,
                message,
            )
            self.findings.append(
                ValidationFinding(
                    check_id=check_id,
                    check_family=check_family,
                    severity=severity,
                    column=column,
                    message=message,
                    expected=expected,
                    observed=observed,
                    contract_justification=contract_justification,
                )
            )


def _dtype_family(dtype_name: str) -> str:
    """Logical-type bucket for a pandas dtype **name** (a string, e.g. from
    `str(series.dtype)` or a contract's `constraints.dtype.expected`).

    Exists because pandas 3.0.5 reports plain text columns as `str`, not the
    historical `object` (Phase 3, docs/architecture.md §Known Issues) — a
    brittle `expected == actual` string comparison would flag every text
    column as a dtype mismatch on this pandas version alone, which is not a
    real schema break. Two dtypes in the same family are treated as
    **fully compatible** (no finding at all), matching §F.1's own wording:
    "dtype תואם (עם המרות בטוחות)" — safe/equivalent conversions are a match,
    not merely a downgraded warning.
    """
    name = dtype_name.strip()
    integer = {"int8", "int16", "int32", "int64", "Int8", "Int16", "Int32", "Int64", "uint8", "uint16", "uint32", "uint64"}
    floating = {"float16", "float32", "float64", "Float32", "Float64"}
    boolean = {"bool", "boolean"}
    text = {"object", "str", "string"}
    for family in (integer, floating, boolean, text):
        if name in family:
            return next(iter(sorted(family)))  # a stable representative name
    return name  # unknown dtype: its own singleton family


def _positive_rate(target_series: "pd.Series", target_contract) -> float:  # noqa: ANN001
    """Exactly the convention `contract/builder.py` uses when it first
    measured `target.observed.positive_rate` — reused here so the candidate
    dataset's rate is computed the same way the contracted snapshot was, and
    the two numbers are actually comparable (§F.1 target drift check).
    """
    if pd.api.types.is_numeric_dtype(target_series):
        return float((target_series == target_series.max()).mean())
    closed = target_contract.constraints.closed_domain
    positive_label = closed.values[-1] if closed is not None else None
    return float((target_series == positive_label).mean())


# ---------------------------------------------------------------------------
# Family A — artifact presence / readability
# ---------------------------------------------------------------------------


def _check_presence_only(
    rpt: _Collector, path: Path, *, exists_check_id: str, not_empty_check_id: str, label: str
) -> None:
    """Existence + non-empty-size check for a narrative artifact whose
    *content* this module has no business reading (`eda_report.html`,
    `insights.md` — §F.1 Family A requires all four Crew 1 artifacts
    present/non-empty; it never says these two get parsed or semantically
    validated, unlike the CSV/contract pair). Never opens the file beyond a
    `stat()`-equivalent size check — no HTML/Markdown parsing, ever.
    """
    if not path.is_file():
        rpt.record(
            False, check_id=exists_check_id, check_family="artifacts",
            message=f"{label} not found: {path}",
            expected="file exists", observed="missing",
        )
        return
    rpt.record(True, check_id=exists_check_id, check_family="artifacts")
    if path.stat().st_size == 0:
        rpt.record(
            False, check_id=not_empty_check_id, check_family="artifacts",
            message=f"{label} is empty: {path}",
            expected="non-zero byte size", observed=0,
        )
    else:
        rpt.record(True, check_id=not_empty_check_id, check_family="artifacts")


def _check_artifacts(
    rpt: _Collector,
    csv_path: Path,
    contract_path: Path,
    eda_report_html_path: Path,
    insights_md_path: Path,
) -> tuple["pd.DataFrame | None", DatasetContract | None, str | None]:
    """Returns `(df, contract, candidate_sha256)`, any of which may be `None`
    if its own artifact family checks failed. `candidate_sha256` is computed
    straight from the CSV's bytes on disk whenever the file exists and is
    non-empty — independent of whether `pandas.read_csv` later succeeds —
    because family F (integrity) must hash the **actual transferred file
    bytes**, never an in-memory re-serialization (§F.1 note).

    `eda_report_html_path`/`insights_md_path` get presence-only checks
    (`_check_presence_only`) — see the module docstring's "Crew 2 boundary"
    note for why this does not widen what Crew 2 may access.
    """
    df: "pd.DataFrame | None" = None
    contract: DatasetContract | None = None
    candidate_sha256: str | None = None

    # --- contract JSON ---
    if not contract_path.is_file():
        rpt.record(
            False, check_id="ARTIFACTS_CONTRACT_FILE_EXISTS", check_family="artifacts",
            message=f"contract JSON not found: {contract_path}",
            expected="file exists", observed="missing",
        )
    else:
        rpt.record(True, check_id="ARTIFACTS_CONTRACT_FILE_EXISTS", check_family="artifacts")
        contract_bytes = contract_path.read_bytes()
        if len(contract_bytes) == 0:
            rpt.record(
                False, check_id="ARTIFACTS_CONTRACT_FILE_NOT_EMPTY", check_family="artifacts",
                message=f"contract JSON is empty: {contract_path}",
                expected="non-zero byte size", observed=0,
            )
        else:
            rpt.record(True, check_id="ARTIFACTS_CONTRACT_FILE_NOT_EMPTY", check_family="artifacts")
            try:
                contract_dict = json.loads(contract_bytes)
            except json.JSONDecodeError as exc:
                rpt.record(
                    False, check_id="ARTIFACTS_CONTRACT_JSON_PARSES", check_family="artifacts",
                    message=f"contract JSON does not parse: {exc}",
                )
                contract_dict = None
            else:
                rpt.record(True, check_id="ARTIFACTS_CONTRACT_JSON_PARSES", check_family="artifacts")

            if contract_dict is not None:
                try:
                    contract = DatasetContract.model_validate(contract_dict)
                except ValidationError as exc:
                    rpt.record(
                        False, check_id="ARTIFACTS_CONTRACT_SCHEMA_VALID", check_family="artifacts",
                        message=f"contract JSON does not match DatasetContract: {str(exc)[:2000]}",
                    )
                else:
                    rpt.record(True, check_id="ARTIFACTS_CONTRACT_SCHEMA_VALID", check_family="artifacts")

    # --- candidate CSV ---
    if not csv_path.is_file():
        rpt.record(
            False, check_id="ARTIFACTS_CSV_FILE_EXISTS", check_family="artifacts",
            message=f"candidate CSV not found: {csv_path}",
            expected="file exists", observed="missing",
        )
    else:
        rpt.record(True, check_id="ARTIFACTS_CSV_FILE_EXISTS", check_family="artifacts")
        csv_bytes = csv_path.read_bytes()
        if len(csv_bytes) == 0:
            rpt.record(
                False, check_id="ARTIFACTS_CSV_FILE_NOT_EMPTY", check_family="artifacts",
                message=f"candidate CSV is empty: {csv_path}",
                expected="non-zero byte size", observed=0,
            )
        else:
            rpt.record(True, check_id="ARTIFACTS_CSV_FILE_NOT_EMPTY", check_family="artifacts")
            candidate_sha256 = hashlib.sha256(csv_bytes).hexdigest()
            try:
                df = pd.read_csv(csv_path)
            except Exception as exc:  # noqa: BLE001 — any parse failure is a finding, not a crash
                rpt.record(
                    False, check_id="ARTIFACTS_CSV_LOADS", check_family="artifacts",
                    message=f"candidate CSV could not be loaded by pandas: {exc}",
                )
                df = None
            else:
                rpt.record(True, check_id="ARTIFACTS_CSV_LOADS", check_family="artifacts")

    # --- narrative artifacts (presence/size only — never parsed) ---
    _check_presence_only(
        rpt, eda_report_html_path,
        exists_check_id="ARTIFACTS_EDA_REPORT_EXISTS",
        not_empty_check_id="ARTIFACTS_EDA_REPORT_NOT_EMPTY",
        label="eda_report.html",
    )
    _check_presence_only(
        rpt, insights_md_path,
        exists_check_id="ARTIFACTS_INSIGHTS_MD_EXISTS",
        not_empty_check_id="ARTIFACTS_INSIGHTS_MD_NOT_EMPTY",
        label="insights.md",
    )

    return df, contract, candidate_sha256


# ---------------------------------------------------------------------------
# Family B — schema
# ---------------------------------------------------------------------------


def _check_schema(rpt: _Collector, df: "pd.DataFrame", contract: DatasetContract) -> None:
    csv_columns = set(df.columns)
    declared_names = {c.name for c in contract.columns}
    excluded_by_name = {f.name: f for f in contract.excluded_features}

    # --- missing declared (non-target) columns ---
    for column in contract.columns:
        if column.name in csv_columns:
            continue
        exclusion = excluded_by_name.get(column.name)
        if exclusion is not None and exclusion.enforcement == EnforcementLevel.ADVISORY:
            # §F.1: advisory-excluded columns missing from the candidate CSV
            # is expected/tolerable — the Feature Engineer never required it.
            rpt.record(
                False, check_id="SCHEMA_MISSING_COLUMN", check_family="schema", severity="WARN",
                column=column.name,
                message=(
                    f"column {column.name!r} is declared in the contract but absent from the "
                    f"candidate CSV — advisory-excluded ({exclusion.exclusion_type.value}), "
                    "so this is non-blocking."
                ),
                expected="present", observed="missing",
                contract_justification=exclusion.justification,
            )
        else:
            policy_severity: Severity = "ERROR" if contract.validation_policy.on_missing_column == "error" else "WARN"
            rpt.record(
                False, check_id="SCHEMA_MISSING_COLUMN", check_family="schema", severity=policy_severity,
                column=column.name,
                message=f"column {column.name!r} is declared in the contract but absent from the candidate CSV.",
                expected="present", observed="missing",
            )

    # --- unknown (undeclared) columns ---
    known_names = declared_names | {contract.target.name}
    policy_unknown = contract.validation_policy.on_unknown_column
    for name in sorted(csv_columns - known_names):
        if policy_unknown == "ignore":
            rpt.record(True, check_id="SCHEMA_UNKNOWN_COLUMN", check_family="schema", column=name)
            continue
        rpt.record(
            False, check_id="SCHEMA_UNKNOWN_COLUMN", check_family="schema",
            severity="ERROR" if policy_unknown == "error" else "WARN",
            column=name,
            message=f"column {name!r} is present in the candidate CSV but not declared anywhere in the contract.",
            expected="declared in contract", observed="undeclared",
        )

    # --- column order (§F.1: WARN, unconditional) ---
    actual_order = list(df.columns)
    expected_order = contract.integrity.column_order
    if actual_order == expected_order:
        rpt.record(True, check_id="SCHEMA_COLUMN_ORDER", check_family="schema")
    else:
        rpt.record(
            False, check_id="SCHEMA_COLUMN_ORDER", check_family="schema", severity="WARN",
            message="the candidate CSV's column order differs from the contract's integrity.column_order.",
            expected=expected_order, observed=actual_order,
        )

    # --- dtype compatibility, only where a dtype constraint was declared ---
    for column in contract.columns:
        if column.name not in csv_columns or column.constraints.dtype is None:
            continue
        expected_dtype = column.constraints.dtype.expected
        actual_dtype = str(df[column.name].dtype)
        if expected_dtype == actual_dtype or _dtype_family(expected_dtype) == _dtype_family(actual_dtype):
            rpt.record(True, check_id="SCHEMA_DTYPE_COMPATIBLE", check_family="schema", column=column.name)
        else:
            rpt.record(
                False, check_id="SCHEMA_DTYPE_COMPATIBLE", check_family="schema",
                column=column.name,
                message=(
                    f"column {column.name!r} has dtype {actual_dtype!r}, which is not compatible "
                    f"with the contract's declared {expected_dtype!r}."
                ),
                expected=expected_dtype, observed=actual_dtype,
                contract_justification=column.constraints.dtype.justification,
            )


# ---------------------------------------------------------------------------
# Family C — target
# ---------------------------------------------------------------------------


def _check_target(rpt: _Collector, df: "pd.DataFrame", contract: DatasetContract) -> None:
    target_name = contract.target.name
    if target_name not in df.columns:
        rpt.record(
            False, check_id="TARGET_COLUMN_PRESENT", check_family="target",
            column=target_name,
            message=f"target column {target_name!r} is absent from the candidate CSV.",
            expected="present", observed="missing",
        )
        return  # every remaining target check needs the column itself
    rpt.record(True, check_id="TARGET_COLUMN_PRESENT", check_family="target", column=target_name)

    series = df[target_name]
    target = contract.target

    nullable = target.constraints.nullable
    if nullable is not None and nullable.value is False:
        null_count = int(series.isnull().sum())
        if null_count == 0:
            rpt.record(True, check_id="TARGET_NO_NULLS", check_family="target", column=target_name)
        else:
            rpt.record(
                False, check_id="TARGET_NO_NULLS", check_family="target", column=target_name,
                message=f"target {target_name!r} declares nullable=false but has {null_count} null value(s).",
                expected=0, observed=null_count, contract_justification=nullable.justification,
            )

    closed = target.constraints.closed_domain
    if closed is not None:
        allowed = set(closed.values)
        observed_values = {str(v) for v in series.dropna().unique()}
        unexpected = sorted(observed_values - allowed)
        if not unexpected:
            rpt.record(True, check_id="TARGET_CLOSED_DOMAIN", check_family="target", column=target_name)
        else:
            rpt.record(
                False, check_id="TARGET_CLOSED_DOMAIN", check_family="target",
                severity=closed.severity.value, column=target_name,
                message=f"target {target_name!r} contains value(s) outside its declared closed domain: {unexpected}.",
                expected=sorted(allowed), observed=unexpected,
                contract_justification=closed.justification,
            )

    class_count = int(series.dropna().nunique())
    if class_count >= 2:
        rpt.record(True, check_id="TARGET_AT_LEAST_TWO_CLASSES", check_family="target", column=target_name)
    else:
        rpt.record(
            False, check_id="TARGET_AT_LEAST_TWO_CLASSES", check_family="target", column=target_name,
            message=f"target {target_name!r} has only {class_count} distinct non-null value(s); binary classification needs ≥2.",
            expected="≥2 classes", observed=class_count,
        )

    # §F.1: "positive_rate בתוך drift.tolerance" — ONLY if a drift policy was
    # explicitly declared. `observed.positive_rate` alone is never enforced
    # (§Phase 4 "NO AUTOMATIC ENFORCEMENT OF OBSERVED VALUES").
    if target.drift is not None:
        candidate_rate = _positive_rate(series, target)
        snapshot_rate = target.observed.positive_rate
        delta = abs(candidate_rate - snapshot_rate)
        if delta <= target.drift.positive_rate_tolerance_abs:
            rpt.record(True, check_id="TARGET_POSITIVE_RATE_DRIFT", check_family="target", column=target_name)
        else:
            rpt.record(
                False, check_id="TARGET_POSITIVE_RATE_DRIFT", check_family="target", column=target_name,
                message=(
                    f"target {target_name!r} positive rate drifted by {delta:.4f} "
                    f"(candidate {candidate_rate:.4f} vs. contract snapshot {snapshot_rate:.4f}), "
                    f"beyond the declared tolerance {target.drift.positive_rate_tolerance_abs}."
                ),
                expected=snapshot_rate, observed=candidate_rate,
                contract_justification=target.drift.justification,
            )


# ---------------------------------------------------------------------------
# Family D — justified constraints (never `observed.*`)
# ---------------------------------------------------------------------------


def _check_constraints(rpt: _Collector, df: "pd.DataFrame", contract: DatasetContract) -> None:
    for column in contract.columns:
        if column.name not in df.columns:
            continue  # already reported by SCHEMA_MISSING_COLUMN; nothing further to check
        series = df[column.name]
        constraints = column.constraints

        if constraints.nullable is not None and constraints.nullable.value is False:
            null_count = int(series.isnull().sum())
            if null_count == 0:
                rpt.record(True, check_id="CONSTRAINTS_NULLABLE", check_family="constraints", column=column.name)
            else:
                rpt.record(
                    False, check_id="CONSTRAINTS_NULLABLE", check_family="constraints", column=column.name,
                    message=f"column {column.name!r} declares nullable=false but has {null_count} null value(s).",
                    expected=0, observed=null_count,
                    contract_justification=constraints.nullable.justification,
                )

        br = constraints.business_range
        if br is not None:
            numeric = pd.to_numeric(series, errors="coerce").dropna()
            below = numeric[numeric < br.min] if br.min is not None else numeric.iloc[0:0]
            above = numeric[numeric > br.max] if br.max is not None else numeric.iloc[0:0]
            total_violations = int(len(below) + len(above))
            if total_violations == 0:
                rpt.record(True, check_id="CONSTRAINTS_BUSINESS_RANGE", check_family="constraints", column=column.name)
            else:
                observed_extreme = float(below.min()) if len(below) else float(above.max())
                rpt.record(
                    False, check_id="CONSTRAINTS_BUSINESS_RANGE", check_family="constraints", column=column.name,
                    message=(
                        f"column {column.name!r} has {total_violations} value(s) outside the declared "
                        f"business_range [{br.min}, {br.max}]."
                    ),
                    expected=[br.min, br.max], observed=observed_extreme,
                    contract_justification=br.justification,
                )

        cd = constraints.closed_domain
        if cd is not None:
            allowed = set(cd.values)
            observed_values = {str(v) for v in series.dropna().unique()}
            unexpected = sorted(observed_values - allowed)
            if not unexpected:
                rpt.record(True, check_id="CONSTRAINTS_CLOSED_DOMAIN", check_family="constraints", column=column.name)
            else:
                rpt.record(
                    False, check_id="CONSTRAINTS_CLOSED_DOMAIN", check_family="constraints",
                    severity=cd.severity.value, column=column.name,
                    message=f"column {column.name!r} contains value(s) outside its declared closed domain: {unexpected}.",
                    expected=sorted(allowed), observed=unexpected,
                    contract_justification=cd.justification,
                )

    # --- primary key uniqueness ---
    pk = contract.primary_key
    if pk.constraints.unique.value:
        pk_columns = [c for c in pk.columns if c in df.columns]
        if len(pk_columns) == len(pk.columns):
            duplicate_count = int(df.duplicated(subset=pk_columns, keep=False).sum())
            if duplicate_count == 0:
                rpt.record(True, check_id="CONSTRAINTS_PRIMARY_KEY_UNIQUE", check_family="constraints")
            else:
                rpt.record(
                    False, check_id="CONSTRAINTS_PRIMARY_KEY_UNIQUE", check_family="constraints",
                    column=",".join(pk.columns),
                    message=f"primary key {pk.columns} has {duplicate_count} row(s) participating in a duplicate combination.",
                    expected=0, observed=duplicate_count,
                    contract_justification=pk.constraints.unique.justification,
                )
            # else: a primary-key column is itself missing — SCHEMA_MISSING_COLUMN already reported it.


# ---------------------------------------------------------------------------
# Family E — scale drift (§E.3, the mandatory incident detector)
# ---------------------------------------------------------------------------


def _check_scale_drift(rpt: _Collector, df: "pd.DataFrame", contract: DatasetContract) -> None:
    for column in contract.columns:
        policy = column.constraints.scale_drift
        if policy is None or column.name not in df.columns:
            continue  # §F.1: only for columns that declared a scale_drift policy

        snap_median = column.observed.median
        if snap_median is None or snap_median == 0:
            # §E.3 pseudocode's own guard: `if policy and snap_median != 0`.
            # A zero/undeclared snapshot median makes a *ratio* meaningless —
            # skip rather than divide by zero or invent a substitute check.
            continue

        candidate_numeric = pd.to_numeric(df[column.name], errors="coerce").dropna()
        if candidate_numeric.empty:
            continue  # no numeric observations to compare — nothing to measure
        obs_median = float(candidate_numeric.median())

        ratio = obs_median / snap_median
        if abs(ratio - 1.0) <= policy.median_rel_tolerance:
            rpt.record(True, check_id="SCALE_DRIFT_MEDIAN", check_family="scale_drift", column=column.name)
            continue

        hint = next(
            (
                h
                for h in contract.validation_policy.scale_change_ratio_hints
                if h != 0 and abs(ratio - h) / abs(h) < _SCALE_DRIFT_RATIO_HINT_TOLERANCE
            ),
            None,
        )
        unit = column.constraints.unit
        if hint is not None:
            unit_clause = (
                f" The contract declares unit={unit.value!r} (evidence: {unit.evidence!r})."
                if unit is not None
                else ""
            )
            message = (
                f"SUSPECTED SCALE CHANGE: the observed median is ≈{hint:g}× the value "
                f"recorded in the contract snapshot (observed {obs_median} vs. contracted "
                f"{snap_median}).{unit_clause} A change of exactly this magnitude is "
                "characteristic of a unit or scale conversion."
            )
        else:
            message = (
                f"SCALE DRIFT: observed median {obs_median} vs. contracted snapshot {snap_median} "
                f"(ratio {ratio:.3f}), beyond tolerance {policy.median_rel_tolerance}."
            )
        rpt.record(
            False, check_id="SCALE_DRIFT_MEDIAN", check_family="scale_drift",
            severity=policy.severity.value, column=column.name,
            message=message, expected=snap_median, observed=obs_median,
            contract_justification=policy.justification,
        )

    # --- row-count visibility (§F.1: "row_count → WARN"; informational only,
    # never blocking on its own — the integrity/modeling families are the
    # ones that actually gate on a changed or truncated file) ---
    measured_rows = int(len(df))
    contracted_rows = contract.integrity.row_count
    if measured_rows == contracted_rows:
        rpt.record(True, check_id="SCALE_DRIFT_ROW_COUNT", check_family="scale_drift")
    else:
        rpt.record(
            False, check_id="SCALE_DRIFT_ROW_COUNT", check_family="scale_drift", severity="WARN",
            message=f"candidate row count ({measured_rows}) differs from the contract's row_count ({contracted_rows}).",
            expected=contracted_rows, observed=measured_rows,
        )


# ---------------------------------------------------------------------------
# Family F — integrity
# ---------------------------------------------------------------------------


def _check_integrity(rpt: _Collector, contract: DatasetContract, candidate_sha256: str | None) -> None:
    if candidate_sha256 is None:
        return  # the CSV never loaded far enough to be hashed; family A already reported it
    expected = contract.integrity.clean_data_sha256
    if candidate_sha256 == expected:
        rpt.record(True, check_id="INTEGRITY_SHA256_MATCH", check_family="integrity")
    else:
        rpt.record(
            False, check_id="INTEGRITY_SHA256_MATCH", check_family="integrity",
            message="the candidate CSV's bytes do not match the contract's integrity.clean_data_sha256 — the file has changed since the contract was written.",
            expected=expected, observed=candidate_sha256,
        )


# ---------------------------------------------------------------------------
# Family G — modeling readiness
# ---------------------------------------------------------------------------


def _check_modeling(rpt: _Collector, df: "pd.DataFrame", contract: DatasetContract) -> None:
    measured_rows = int(len(df))
    if measured_rows >= _MIN_ROWS_FOR_MODELING:
        rpt.record(True, check_id="MODELING_MIN_ROWS", check_family="modeling")
    else:
        rpt.record(
            False, check_id="MODELING_MIN_ROWS", check_family="modeling",
            message=f"the candidate dataset has only {measured_rows} row(s); modeling needs at least {_MIN_ROWS_FOR_MODELING}.",
            expected=f">= {_MIN_ROWS_FOR_MODELING}", observed=measured_rows,
        )

    hard_excluded = {f.name for f in contract.excluded_features if f.enforcement == EnforcementLevel.HARD}
    usable_features = {c.name for c in contract.columns} - hard_excluded
    if len(usable_features) >= _MIN_USABLE_FEATURES:
        rpt.record(True, check_id="MODELING_MIN_FEATURES", check_family="modeling")
    else:
        rpt.record(
            False, check_id="MODELING_MIN_FEATURES", check_family="modeling",
            message=f"only {len(usable_features)} non-hard-excluded feature(s) are declared; modeling needs at least {_MIN_USABLE_FEATURES}.",
            expected=f">= {_MIN_USABLE_FEATURES}", observed=len(usable_features),
        )

    for name in contract.required_features:
        if name not in df.columns:
            continue  # SCHEMA_MISSING_COLUMN already reported this
        distinct = int(df[name].nunique(dropna=True))
        if distinct > 1:
            rpt.record(True, check_id="MODELING_CONSTANT_REQUIRED_FEATURE", check_family="modeling", column=name)
        else:
            rpt.record(
                False, check_id="MODELING_CONSTANT_REQUIRED_FEATURE", check_family="modeling",
                severity="WARN", column=name,
                message=f"required feature {name!r} has only {distinct} distinct observed value(s) in the candidate data.",
                expected="> 1 distinct value", observed=distinct,
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_validation_gate(
    candidate_csv_path: Path | str,
    contract_json_path: Path | str,
    eda_report_html_path: Path | str,
    insights_md_path: Path | str,
    *,
    run_id: str,
    fault_injection: str | None = None,
) -> ValidationReport:
    """Validate one candidate `clean_data.csv` against one `dataset_contract.json`
    — and confirm all **four** required Crew 1 artifacts are present/non-empty
    (§F.1 Family A; §G.0 for why the latter two do not widen Crew 2's access).

    Zero LLM calls. `passed = (errors == 0)`; every applicable check across
    every family is run and every finding collected — the gate never stops
    at the first `ERROR` (see the module docstring's "Prerequisite gating"
    note for the one legitimate early-exit: families B–G cannot run without
    a parsed contract and a loaded CSV).

    Args:
        candidate_csv_path: the CSV being validated (a fixture in tests
            today; `artifacts/crew1/clean_data.csv` once Phase 5+/6+ exist).
        contract_json_path: the `DatasetContract` JSON to validate against.
        eda_report_html_path: path to the EDA & Insights Analyst's HTML
            report (`artifacts/crew1/eda_report.html` in production, once
            Phase 6+ exists). Existence/non-empty size checked ONLY — its
            content is never opened, parsed, or returned by this function;
            see the module docstring's "Crew 2 boundary" note.
        insights_md_path: path to the narrative insights file
            (`artifacts/crew1/insights.md` in production). Same
            existence/non-empty-only treatment as `eda_report_html_path`.
        run_id: caller-supplied run identifier, stamped onto the report.
            This module deliberately does not invent one — a `Flow` (future
            phase) is the natural owner of run identity, not the gate.
        fault_injection: an optional label naming a deliberately-injected
            fault (`src/harbor_vale/demo/fault_injection.py`), carried
            through to the report for visibility. `None` on every real run.

    Returns:
        A `ValidationReport`. Always returned, never raised, for any
        artifact/data problem the gate itself is designed to detect — a
        raised exception here would mean an unanticipated bug, not a normal
        validation failure.
    """
    csv_path = Path(candidate_csv_path)
    contract_path = Path(contract_json_path)
    eda_path = Path(eda_report_html_path)
    insights_path = Path(insights_md_path)
    rpt = _Collector()

    df, contract, candidate_sha256 = _check_artifacts(rpt, csv_path, contract_path, eda_path, insights_path)

    if df is not None and contract is not None:
        _check_schema(rpt, df, contract)
        _check_target(rpt, df, contract)
        _check_constraints(rpt, df, contract)
        _check_scale_drift(rpt, df, contract)
        _check_integrity(rpt, contract, candidate_sha256)
        _check_modeling(rpt, df, contract)
    elif contract is not None and candidate_sha256 is not None:
        # The CSV's bytes exist and were hashed even though pandas could not
        # parse them (e.g. a genuinely malformed CSV) — integrity can still
        # be meaningfully checked; schema/target/etc. cannot.
        _check_integrity(rpt, contract, candidate_sha256)

    errors = sum(1 for f in rpt.findings if f.severity == "ERROR")
    warnings = sum(1 for f in rpt.findings if f.severity == "WARN")

    return ValidationReport(
        run_id=run_id,
        passed=(errors == 0),
        checks_run=rpt.checks_run,
        errors=errors,
        warnings=warnings,
        findings=rpt.findings,
        contract_version=contract.contract_version if contract is not None else None,
        fault_injection=fault_injection,
        validated_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# §F.3 — human-readable rendering (Internal Gate 4E)
# ---------------------------------------------------------------------------


def render_validation_report_markdown(report: ValidationReport) -> str:
    """Render `report` as the failure-report style shown in PROJECT_PLAN.md §F.3.

    Deliberately does **not** say "Data Scientist Crew was NOT started" —
    that is a Flow-level fact (`PipelineState.crew2_started`, a later phase);
    a standalone Phase 4 renderer only knows whether validation itself
    passed or failed, and this function stays honest about that boundary
    (§Phase 4 "IMPORTANT STAGED O.3 INTERPRETATION").
    """
    lines: list[str] = []
    bar = "=" * 64
    lines.append(bar)
    status = "DATA CONTRACT VALIDATION PASSED" if report.passed else "DATA CONTRACT VALIDATION FAILED"
    lines.append(f"  {status}")
    lines.append(f"  run_id: {report.run_id} · contract v{report.contract_version or 'unknown'}")
    if report.fault_injection:
        lines.append(f"  ⚠️  fault_injection: {report.fault_injection}  (DEMO MODE)")
    lines.append(f"  {report.errors} error(s) · {report.warnings} warning(s) · {report.checks_run} check(s) run")
    lines.append(bar)
    lines.append("")

    if not report.findings:
        lines.append("No findings. Every applicable check passed cleanly.")
    for finding in report.findings:
        lines.append(f"[{finding.severity}] {finding.check_family} · check_id: {finding.check_id}" + (
            f" · column: {finding.column}" if finding.column else ""
        ))
        lines.append(f"  {finding.message}")
        if finding.expected is not None or finding.observed is not None:
            lines.append(f"  expected: {finding.expected!r}  observed: {finding.observed!r}")
        if finding.contract_justification:
            lines.append(f"  Contract justification for this check:")
            lines.append(f"    \"{finding.contract_justification}\"")
        lines.append("")

    lines.append("─" * 64)
    if report.passed:
        lines.append("  Validation gate: PASS. Candidate dataset matches the contract.")
    else:
        lines.append("  Validation gate: FAIL. Pipeline halted at the validation gate.")
        lines.append(
            "  (Whether a downstream crew is started or skipped is a Flow-level "
            "decision made later, not a claim this standalone report makes.)"
        )
    lines.append(f"  Full report: artifacts/validation/validation_report.md")
    lines.append(bar)
    return "\n".join(lines) + "\n"
