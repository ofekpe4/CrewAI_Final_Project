"""Deterministic Dataset Contract builder (PROJECT_PLAN.md §D.3 point 8, §E.1 rule 5).

    ContractDraft (semantics, agent-authored, guardrail-validated)
    + real CSV bytes
    + measured Python facts
    = DatasetContract

Every measured number in the resulting contract — SHA256, row/column counts,
column order, dtypes, null/unique counts, numeric statistics, target class
counts — is computed here, by pandas, from the actual file on disk. Nothing
in this module accepts a measured value as an argument from the semantic
layer, and nothing here invents or upgrades a `constraints` field: every
constraint in the output is copied, unchanged, from the already-validated
`ContractDraft` (see `_carry_column_constraints` / `_carry_target_constraints`
below — no "if scale-sensitive then invent a tolerance" branch exists).

This module builds contracts. It never validates a *candidate* dataset
against an existing contract — that comparison (§E.3 scale-drift detection,
PASS/FAIL) is `contract/validator.py`, Phase 4, explicitly out of scope here.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from harbor_vale.contract.schema import (
    ColumnConstraints,
    ColumnContract,
    ColumnObserved,
    DatasetContract,
    Integrity,
    PrimaryKey,
    PrimaryKeyConstraints,
    TargetConstraints,
    TargetContract,
    TargetObserved,
    ValidationPolicy,
)
from harbor_vale.plans.contract_draft import ContractDraft

# A categorical column's full observed distribution is recorded only up to
# this many distinct values — beyond that, dumping every value's share adds
# noise, not signal (e.g. a near-unique identifier column). A deterministic,
# documented threshold, not a judgement call the builder is making about the
# dataset's *meaning*.
_MAX_VALUE_DISTRIBUTION_CARDINALITY = 50


class ContractBuildError(ValueError):
    """Raised when the draft and the real CSV cannot be reconciled.

    Always a deterministic, explainable mismatch (missing/extra columns,
    target absent from the file, etc.) — never a semantic judgement call.
    """


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decimal_places(series: "pd.Series") -> int | None:
    """Max number of decimal digits actually present in a numeric series.

    Uses Python's shortest round-trip ``repr(float(...))`` — exact for the
    kind of 2-decimal monetary values this project's scale-sensitive column
    has (PROJECT_PLAN.md §E.2 example: `decimal_places_max: 2`). Values in
    scientific notation are skipped (rare for this project's data shapes).
    """
    non_null = series.dropna()
    if non_null.empty:
        return None
    places: list[int] = []
    for value in non_null:
        text = repr(float(value))
        if "e" in text or "E" in text:
            continue
        if "." not in text:
            places.append(0)
            continue
        places.append(len(text.split(".", 1)[1].rstrip("0")))
    return max(places) if places else None


def _measure_column(series: "pd.Series") -> ColumnObserved:
    dtype_name = str(series.dtype)
    null_count = int(series.isnull().sum())
    unique_count = int(series.nunique(dropna=True))

    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        non_null = series.dropna()
        return ColumnObserved(
            dtype=dtype_name,
            null_count=null_count,
            unique_count=unique_count,
            min=float(non_null.min()) if not non_null.empty else None,
            max=float(non_null.max()) if not non_null.empty else None,
            mean=float(non_null.mean()) if not non_null.empty else None,
            median=float(non_null.median()) if not non_null.empty else None,
            p05=float(non_null.quantile(0.05)) if not non_null.empty else None,
            p95=float(non_null.quantile(0.95)) if not non_null.empty else None,
            std=float(non_null.std()) if len(non_null) > 1 else None,
            decimal_places_max=_decimal_places(series),
            value_distribution=None,
        )

    value_distribution = None
    if 0 < unique_count <= _MAX_VALUE_DISTRIBUTION_CARDINALITY:
        counts = series.value_counts(normalize=True, dropna=True)
        value_distribution = {str(k): float(v) for k, v in counts.items()}

    return ColumnObserved(
        dtype=dtype_name,
        null_count=null_count,
        unique_count=unique_count,
        value_distribution=value_distribution,
    )


def _carry_column_constraints(draft_column) -> ColumnConstraints:  # noqa: ANN001
    """Copy the agent's constraint declarations through unchanged.

    No field is derived from anything measured — each is either the draft's
    own already-justified object, or absent (``None``, meaning "no
    enforcement"), exactly as the draft declared it.
    """
    return ColumnConstraints(
        dtype=draft_column.dtype,
        nullable=draft_column.nullable,
        unit=draft_column.unit,
        business_range=draft_column.business_range,
        closed_domain=draft_column.closed_domain,
        scale_drift=draft_column.scale_drift,
    )


def build_contract(
    draft: ContractDraft,
    csv_path: Path | str,
    *,
    contract_version: str,
    run_id: str,
    created_by: str,
    dataset_name: str,
    source_documentation_url: str,
    validation_policy: ValidationPolicy | None = None,
    created_at: str | None = None,
) -> DatasetContract:
    """Build the final `DatasetContract` from a validated draft + a real CSV file.

    Args:
        draft: an **already guardrail-validated** `ContractDraft` (call
            `harbor_vale.plans.contract_draft.validate_contract_draft` first —
            this function does not re-run that guardrail; it trusts its input
            is a real `ContractDraft` instance, exactly like a CrewAI task
            callback would receive one after the guardrail loop succeeds).
        csv_path: path to the exact CSV file being contracted. Its bytes are
            hashed and its content is read with pandas — this is the only
            source of every `observed`/`integrity` fact in the output.
        contract_version, run_id, created_by, dataset_name,
        source_documentation_url: deterministic run/dataset metadata the
            draft never carries (§E.1 rule 5 — measured/known facts, not LLM
            judgement).
        validation_policy: defaults to `ValidationPolicy()` (the schema's own
            defaults) if omitted.
        created_at: ISO-8601 timestamp; defaults to "now" (UTC) if omitted.

    Raises:
        ContractBuildError: if the draft's declared columns and the CSV's
            actual columns disagree (missing, extra, or the target column
            absent from the file) — a deterministic coverage check that only
            the builder can make, since only the builder has read the file.
    """
    path = Path(csv_path)
    if not path.is_file():
        raise ContractBuildError(f"CSV file not found: {path}")

    sha256 = _sha256_of_file(path)
    df = pd.read_csv(path)

    row_count, column_count = df.shape
    column_order = list(df.columns)
    csv_columns = set(column_order)

    target_name = draft.target.name
    if target_name not in csv_columns:
        raise ContractBuildError(
            f"target column {target_name!r} declared in the draft is not present "
            f"in the CSV (columns: {column_order})"
        )

    declared_feature_names = {c.name for c in draft.columns}
    csv_feature_names = csv_columns - {target_name}
    if declared_feature_names != csv_feature_names:
        missing = csv_feature_names - declared_feature_names
        extra = declared_feature_names - csv_feature_names
        detail = []
        if missing:
            detail.append(f"CSV columns with no draft declaration: {sorted(missing)}")
        if extra:
            detail.append(f"draft declares columns absent from the CSV: {sorted(extra)}")
        raise ContractBuildError(
            "ContractDraft column coverage does not match the CSV: " + "; ".join(detail)
        )

    draft_columns_by_name = {c.name: c for c in draft.columns}
    columns: list[ColumnContract] = []
    for name in column_order:
        if name == target_name:
            continue
        draft_column = draft_columns_by_name[name]
        columns.append(
            ColumnContract(
                name=name,
                semantic_type=draft_column.semantic_type,
                observed=_measure_column(df[name]),
                constraints=_carry_column_constraints(draft_column),
            )
        )

    target_series = df[target_name]
    class_counts = {str(k): int(v) for k, v in target_series.value_counts(dropna=False).items()}
    # "Positive" = the numerically larger of the two class labels' underlying
    # value where the series is already numeric (0/1); for a non-numeric
    # target this is the label the draft's closed_domain lists last, matching
    # the common "[negative, positive]" ordering convention (§E.2 example:
    # values=["0","1"]). Documented, deterministic — not a guess per row.
    if pd.api.types.is_numeric_dtype(target_series):
        positive_rate = float((target_series == target_series.max()).mean())
    else:
        positive_label = draft.target.closed_domain.values[-1]
        positive_rate = float((target_series == positive_label).mean())

    target = TargetContract(
        name=target_name,
        task_type=draft.target.task_type,
        constraints=TargetConstraints(
            dtype=draft.target.dtype,
            closed_domain=draft.target.closed_domain,
            nullable=draft.target.nullable,
        ),
        observed=TargetObserved(positive_rate=positive_rate, class_counts=class_counts),
        drift=draft.target.drift,
    )

    contract = DatasetContract(
        contract_version=contract_version,
        created_at=created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        created_by=created_by,
        run_id=run_id,
        dataset_name=dataset_name,
        source_documentation_url=source_documentation_url,
        target=target,
        required_features=list(draft.required_features),
        excluded_features=list(draft.excluded_features),
        primary_key=PrimaryKey(
            columns=list(draft.primary_key.columns),
            constraints=PrimaryKeyConstraints(unique=draft.primary_key.unique),
        ),
        columns=columns,
        integrity=Integrity(
            clean_data_sha256=sha256,
            row_count=int(row_count),
            column_count=int(column_count),
            column_order=column_order,
        ),
        assumptions=list(draft.assumptions),
        validation_policy=validation_policy or ValidationPolicy(),
    )
    return contract
