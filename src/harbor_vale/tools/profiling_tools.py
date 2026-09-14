"""Deterministic dataset profiling (PROJECT_PLAN.md §D.1 point 3: `profile_dataset()`).

Plain Python + pandas measurement, exposed as a typed Pydantic structure a
future Data Quality Inspector agent reads — never as something the agent
computes itself. No LLM interpretation happens here; this module only
*measures*. §I's responsibility matrix: "טעינה, פרופיילינג ... ✅ Python ...
חישוב טהור."

`profile_dataframe()` never mutates its input `DataFrame` and never writes
a file — it is read-only measurement, matching §D.1 point 5's explicit
prohibition on the Inspector agent writing anything ("אסור: לכתוב קובץ").
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

# A categorical column's full value-frequency table is recorded only up to
# this many distinct values, mirroring contract/builder.py's identical,
# identically-documented threshold for `ColumnObserved.value_distribution` —
# beyond this cardinality, a full breakdown is noise (e.g. a near-unique
# identifier column), not signal a cleaning-plan agent needs.
_MAX_TOP_VALUES_CARDINALITY = 50
_TOP_VALUES_SHOWN = 10


class ColumnProfile(BaseModel):
    """Per-column measured facts — everything a Cleaning Plan agent needs to
    decide what to do with one column, without ever seeing raw row data
    beyond what this profile (and `preview_sample`, not implemented here)
    exposes."""

    model_config = ConfigDict(extra="forbid")

    name: str
    dtype: str
    null_count: int = Field(ge=0)
    non_null_count: int = Field(ge=0)
    unique_count: int = Field(ge=0)
    blank_string_count: int = Field(
        ge=0,
        description=(
            "Non-null string values that are empty or whitespace-only — pandas' "
            "isnull() does NOT count these (data/README.md §7.1's exact issue: "
            "TotalCharges' 11 blank-placeholder rows measure null_count=0)."
        ),
    )
    is_numeric: bool
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    median: float | None = None
    top_values: dict[str, int] | None = Field(
        default=None,
        description="Value -> row count, most frequent first, top "
        f"{_TOP_VALUES_SHOWN} only, present only for non-numeric columns with "
        f"<= {_MAX_TOP_VALUES_CARDINALITY} distinct values.",
    )


class DatasetProfile(BaseModel):
    """The full deterministic profile of one DataFrame at one point in time
    (§D.1: "פרופיל JSON דטרמיניסטי"). `profile_dataframe()` is called twice
    in the hardcoded E2E — once on the raw data, once on the cleaned data —
    producing two independent `DatasetProfile` instances, never one mutated
    into the other.
    """

    model_config = ConfigDict(extra="forbid")

    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    columns: list[ColumnProfile]
    duplicate_row_count: int = Field(ge=0, description="Full-row duplicates (all columns).")
    target_distribution: dict[str, int] | None = Field(
        default=None, description="Value -> row count for `target_column`, if given."
    )

    def column(self, name: str) -> ColumnProfile:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(f"no column {name!r} in this profile")

    def has_column(self, name: str) -> bool:
        return any(c.name == name for c in self.columns)


def _profile_one_column(series: "pd.Series") -> ColumnProfile:
    name = str(series.name)
    dtype_name = str(series.dtype)
    null_count = int(series.isnull().sum())
    non_null_count = int(len(series) - null_count)
    unique_count = int(series.nunique(dropna=True))

    blank_string_count = 0
    if not pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        non_null = series.dropna()
        blank_string_count = int(
            non_null.apply(lambda v: isinstance(v, str) and v.strip() == "").sum()
        )

    is_numeric = bool(pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series))

    if is_numeric:
        non_null = series.dropna()
        return ColumnProfile(
            name=name, dtype=dtype_name, null_count=null_count, non_null_count=non_null_count,
            unique_count=unique_count, blank_string_count=blank_string_count, is_numeric=True,
            min=float(non_null.min()) if not non_null.empty else None,
            max=float(non_null.max()) if not non_null.empty else None,
            mean=float(non_null.mean()) if not non_null.empty else None,
            median=float(non_null.median()) if not non_null.empty else None,
        )

    top_values: dict[str, int] | None = None
    if 0 < unique_count <= _MAX_TOP_VALUES_CARDINALITY:
        counts = series.dropna().value_counts().head(_TOP_VALUES_SHOWN)
        top_values = {str(k): int(v) for k, v in counts.items()}

    return ColumnProfile(
        name=name, dtype=dtype_name, null_count=null_count, non_null_count=non_null_count,
        unique_count=unique_count, blank_string_count=blank_string_count, is_numeric=False,
        top_values=top_values,
    )


def profile_dataframe(df: "pd.DataFrame", *, target_column: str | None = None) -> DatasetProfile:
    """Measure `df` and return a `DatasetProfile`. Read-only: never mutates
    `df`, never writes a file.

    Args:
        target_column: if given and present in `df`, its value-frequency
            distribution is recorded on `DatasetProfile.target_distribution`
            (e.g. so a Cleaning Plan agent can see the class balance without
            a separate tool call). Silently omitted (stays `None`) if the
            column is absent — profiling never raises for a missing target,
            since the raw-data profile legitimately has none by that name
            yet if renaming hasn't happened.
    """
    columns = [_profile_one_column(df[col]) for col in df.columns]
    duplicate_row_count = int(df.duplicated(keep="first").sum())

    target_distribution: dict[str, int] | None = None
    if target_column is not None and target_column in df.columns:
        counts = df[target_column].value_counts(dropna=False)
        target_distribution = {str(k): int(v) for k, v in counts.items()}

    return DatasetProfile(
        row_count=int(len(df)),
        column_count=int(len(df.columns)),
        columns=columns,
        duplicate_row_count=duplicate_row_count,
        target_distribution=target_distribution,
    )


def preview_sample(df: "pd.DataFrame", n: int = 20) -> list[dict[str, Any]]:
    """§D.1 point 3's `preview_sample(n=20)` — the Inspector agent's only
    other read tool besides the profile itself. Returns the first `n` rows
    as JSON-safe records (never a `DataFrame`/CrewAI-unfriendly object)."""
    return df.head(n).to_dict(orient="records")
