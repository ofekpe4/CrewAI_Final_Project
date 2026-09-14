"""Deterministic execution of a validated `CleaningPlan` (PROJECT_PLAN.md §D.1 point 8).

`execute_plan()` is the ONLY thing that ever mutates a DataFrame on the
cleaning path. It accepts an already-`validate_cleaning_plan`-approved
`CleaningPlan` — never raw agent output, never a free-form transform — and
applies its operations strictly in list order using nothing but pandas'
own typed, closed operation set (`.drop_duplicates`, `.fillna`, `.astype`,
`.rename`, `.drop`, `.clip`, `.map`). **No `eval`, no `exec`, no arbitrary
Python string is ever executed.**

An agent never touches the DataFrame directly (§I: "ביצוע הניקוי ... ✅
Python ... בר-שחזור ובר-ביקורת"); it only ever produces a `CleaningPlan`,
which this module — and only this module — turns into actual pandas calls.
"""

from __future__ import annotations

import pandas as pd

from harbor_vale.plans.cleaning_plan import (
    CastOp,
    CleaningOperation,
    CleaningPlan,
    ClipOp,
    DropColumnOp,
    DropDuplicatesOp,
    ImputeOp,
    RenameOp,
    StandardizeCategoryOp,
)


class CleaningExecutionError(ValueError):
    """Raised when a validated plan still cannot be executed against the
    ACTUAL DataFrame handed to `execute_plan` (e.g. the DataFrame passed in
    doesn't match the profile the plan was validated against). This should
    never happen for a plan validated against a profile of the very same
    DataFrame — it exists as a defensive check, not an expected code path.
    """


def _apply_drop_duplicates(df: "pd.DataFrame", op: DropDuplicatesOp) -> "pd.DataFrame":
    return df.drop_duplicates(subset=op.subset, keep="first").reset_index(drop=True)


def _apply_impute(df: "pd.DataFrame", op: ImputeOp) -> "pd.DataFrame":
    if op.column not in df.columns:
        raise CleaningExecutionError(f"impute: column {op.column!r} not present in the DataFrame")
    series = df[op.column]
    if op.strategy == "constant":
        fill_value = op.value
    elif op.strategy == "mean":
        fill_value = series.mean()
    elif op.strategy == "median":
        fill_value = series.median()
    elif op.strategy == "mode":
        mode = series.mode(dropna=True)
        if mode.empty:
            raise CleaningExecutionError(f"impute: column {op.column!r} has no mode to impute with")
        fill_value = mode.iloc[0]
    else:  # pragma: no cover — CleaningPlan's own Literal already closes this
        raise CleaningExecutionError(f"impute: unsupported strategy {op.strategy!r}")
    df[op.column] = series.fillna(fill_value)
    return df


_CAST_DTYPE_MAP = {"int64": "int64", "float64": "float64", "str": "str", "bool": "bool"}


def _apply_cast(df: "pd.DataFrame", op: CastOp) -> "pd.DataFrame":
    if op.column not in df.columns:
        raise CleaningExecutionError(f"cast: column {op.column!r} not present in the DataFrame")
    target = _CAST_DTYPE_MAP[op.target_dtype]
    if op.target_dtype in ("int64", "float64"):
        # Coerces non-numeric text (including whitespace-only placeholders —
        # data/README.md §7.1) to NaN rather than raising, matching the
        # CleaningPlan guardrail's own reasoning about a cast that may
        # introduce nulls for a subsequent `impute` to fill.
        df[op.column] = pd.to_numeric(df[op.column], errors="coerce")
        if op.target_dtype == "int64":
            # Only safe to force int64 once no NaNs remain (int64 cannot
            # hold NaN) — if the plan intends int64 with nulls still
            # present, that is a plan-ordering error the executor surfaces
            # clearly rather than silently producing a float column.
            if df[op.column].isnull().any():
                raise CleaningExecutionError(
                    f"cast: column {op.column!r} still has null values; "
                    "impute before casting to int64"
                )
            df[op.column] = df[op.column].astype("int64")
        else:
            # pd.to_numeric alone leaves an already-integral column as
            # int64 (e.g. [1, 1, 2, 3] has no fractional/NaN value to force
            # float inference) — an explicit cast is required so a
            # `target_dtype="float64"` request is actually honoured.
            df[op.column] = df[op.column].astype("float64")
    else:
        df[op.column] = df[op.column].astype(target)
    return df


def _apply_rename(df: "pd.DataFrame", op: RenameOp) -> "pd.DataFrame":
    if op.old_name not in df.columns:
        raise CleaningExecutionError(f"rename: column {op.old_name!r} not present in the DataFrame")
    return df.rename(columns={op.old_name: op.new_name})


def _apply_drop_column(df: "pd.DataFrame", op: DropColumnOp) -> "pd.DataFrame":
    if op.column not in df.columns:
        raise CleaningExecutionError(f"drop_column: column {op.column!r} not present in the DataFrame")
    return df.drop(columns=[op.column])


def _apply_clip(df: "pd.DataFrame", op: ClipOp) -> "pd.DataFrame":
    if op.column not in df.columns:
        raise CleaningExecutionError(f"clip: column {op.column!r} not present in the DataFrame")
    df[op.column] = df[op.column].clip(lower=op.min, upper=op.max)
    return df


def _apply_standardize_category(df: "pd.DataFrame", op: StandardizeCategoryOp) -> "pd.DataFrame":
    if op.column not in df.columns:
        raise CleaningExecutionError(
            f"standardize_category: column {op.column!r} not present in the DataFrame"
        )
    series = df[op.column]
    unmapped = set(series.dropna().astype(str).unique()) - set(op.mapping)
    if unmapped:
        raise CleaningExecutionError(
            f"standardize_category: column {op.column!r} has value(s) not covered by "
            f"the mapping: {sorted(unmapped)}"
        )
    df[op.column] = series.astype(str).map(op.mapping)
    return df


_DISPATCH = {
    DropDuplicatesOp: _apply_drop_duplicates,
    ImputeOp: _apply_impute,
    CastOp: _apply_cast,
    RenameOp: _apply_rename,
    DropColumnOp: _apply_drop_column,
    ClipOp: _apply_clip,
    StandardizeCategoryOp: _apply_standardize_category,
}


def execute_plan(df: "pd.DataFrame", plan: CleaningPlan) -> "pd.DataFrame":
    """Apply every operation in `plan.operations`, strictly in list order,
    to a COPY of `df` (the caller's original DataFrame is never mutated).

    `plan` must already be `validate_cleaning_plan`-approved — this
    function performs no semantic re-validation of its own (that would be a
    second, divergent copy of the guardrail's rules); it only executes what
    was already approved, and raises `CleaningExecutionError` for the
    narrow set of things that can only be discovered by actually running
    pandas against the real data (e.g. a `standardize_category` mapping
    that turns out not to cover every observed value).
    """
    result = df.copy(deep=True)
    for op in plan.operations:
        handler = _DISPATCH.get(type(op))
        if handler is None:  # pragma: no cover — CleaningPlan's union is closed
            raise CleaningExecutionError(f"unsupported operation: {op!r}")
        result = handler(result, op)
    return result


__all__ = ["CleaningExecutionError", "execute_plan"]
