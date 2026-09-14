"""Deterministic fault-injection helpers (PROJECT_PLAN.md §O.3, §P.1).

**For tests only, at this phase.** These functions build mutated *copies* of
a candidate CSV or a contract JSON on disk, for `contract/validator.py`'s
test suite to validate against. They are not wired into any CLI flag, Flow
injection point, or `run_pipeline.py` — that wiring is explicitly Phase 8/10
scope (PROJECT_PLAN.md §P.1 mechanism 1), not here.

Every helper:

- reads its source file, computes a mutated copy **in memory**, and writes
  the result to a caller-supplied `out_path` — never back onto `source_path`.
  A helper refuses to run if `out_path` resolves to the same file as
  `source_path`, so a committed fixture can never be corrupted by accident.
- is a pure function of its arguments: no randomness, no hidden global
  state, no timestamp-dependent behaviour. The same inputs always produce
  byte-identical output.
- returns the `Path` it wrote, so a test can immediately hand that path to
  `run_validation_gate`.

`scale_change` is the one PROJECT_PLAN.md §O.3 marks mandatory. The rest are
the representative, non-exhaustive scenarios §O.3 actually lists; nothing
beyond that list is invented here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


class FaultInjectionError(ValueError):
    """Raised when a fault-injection helper is asked to do something unsafe
    (most commonly: write back onto its own source file)."""


def _guard_distinct_paths(source_path: Path, out_path: Path) -> None:
    if source_path.resolve() == out_path.resolve():
        raise FaultInjectionError(
            f"refusing to write a fault-injected file back onto its source: {source_path}"
        )


def _read_csv(source_path: Path) -> pd.DataFrame:
    return pd.read_csv(source_path)


def _write_csv(df: pd.DataFrame, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return out_path


# ---------------------------------------------------------------------------
# §O.3 — mandatory
# ---------------------------------------------------------------------------


def scale_change(
    source_csv_path: Path | str, out_csv_path: Path | str, *, column: str, factor: float = 100.0
) -> Path:
    """Multiply `column` by `factor` in place, dtype unchanged (§O.3 mandatory scenario).

    The canonical incident reproduction: `monthly_charges *= 100`, still
    `float64`. Expected to be caught by `SCALE_DRIFT_MEDIAN` (and, because
    the bytes changed, `INTEGRITY_SHA256_MATCH`).
    """
    source_path, out_path = Path(source_csv_path), Path(out_csv_path)
    _guard_distinct_paths(source_path, out_path)
    df = _read_csv(source_path)
    if column not in df.columns:
        raise FaultInjectionError(f"column {column!r} not found in {source_path}")
    df[column] = df[column] * factor
    return _write_csv(df, out_path)


# ---------------------------------------------------------------------------
# §O.3 — representative scenarios
# ---------------------------------------------------------------------------


def rename_column(
    source_csv_path: Path | str, out_csv_path: Path | str, *, old_name: str, new_name: str
) -> Path:
    """Rename `old_name` to `new_name`. Expected: `SCHEMA_MISSING_COLUMN` for
    `old_name` (+ `SCHEMA_UNKNOWN_COLUMN` for `new_name`)."""
    source_path, out_path = Path(source_csv_path), Path(out_csv_path)
    _guard_distinct_paths(source_path, out_path)
    df = _read_csv(source_path)
    if old_name not in df.columns:
        raise FaultInjectionError(f"column {old_name!r} not found in {source_path}")
    return _write_csv(df.rename(columns={old_name: new_name}), out_path)


def drop_required_column(
    source_csv_path: Path | str, out_csv_path: Path | str, *, column: str
) -> Path:
    """Drop `column` entirely. Expected: `SCHEMA_MISSING_COLUMN` (severity
    depends on `validation_policy.on_missing_column` / whether `column` is
    advisory-excluded)."""
    source_path, out_path = Path(source_csv_path), Path(out_csv_path)
    _guard_distinct_paths(source_path, out_path)
    df = _read_csv(source_path)
    if column not in df.columns:
        raise FaultInjectionError(f"column {column!r} not found in {source_path}")
    return _write_csv(df.drop(columns=[column]), out_path)


def change_dtype(
    source_csv_path: Path | str, out_csv_path: Path | str, *, column: str, dtype: str
) -> Path:
    """Cast `column` to `dtype` (e.g. a numeric column to `str`). Expected:
    `SCHEMA_DTYPE_COMPATIBLE`, only if the target `dtype`'s logical family
    genuinely differs from the contract's declared expectation."""
    source_path, out_path = Path(source_csv_path), Path(out_csv_path)
    _guard_distinct_paths(source_path, out_path)
    df = _read_csv(source_path)
    if column not in df.columns:
        raise FaultInjectionError(f"column {column!r} not found in {source_path}")
    df[column] = df[column].astype(dtype)
    return _write_csv(df, out_path)


def inject_nulls(
    source_csv_path: Path | str, out_csv_path: Path | str, *, column: str, count: int
) -> Path:
    """Null out the first `count` non-null values of `column` (deterministic —
    always the first `count` rows by position, not a random sample).
    Expected: `CONSTRAINTS_NULLABLE` (or `TARGET_NO_NULLS` for the target),
    only if `nullable.value is False` was declared for that column."""
    source_path, out_path = Path(source_csv_path), Path(out_csv_path)
    _guard_distinct_paths(source_path, out_path)
    df = _read_csv(source_path)
    if column not in df.columns:
        raise FaultInjectionError(f"column {column!r} not found in {source_path}")
    if count < 0 or count > len(df):
        raise FaultInjectionError(f"count={count} is out of range for {len(df)} row(s)")
    df.loc[df.index[:count], column] = None
    return _write_csv(df, out_path)


def unknown_category(
    source_csv_path: Path | str,
    out_csv_path: Path | str,
    *,
    column: str,
    new_value: str,
    row_index: int = 0,
) -> Path:
    """Overwrite one cell of `column` with `new_value`, a value the contract
    never declared. Expected: `CONSTRAINTS_CLOSED_DOMAIN` — but ONLY if
    `column` actually declares a `closed_domain` (§F.1: an undeclared domain
    means there is nothing for this mutation to violate; that is the
    documented, intentional non-finding case, not a bug)."""
    source_path, out_path = Path(source_csv_path), Path(out_csv_path)
    _guard_distinct_paths(source_path, out_path)
    df = _read_csv(source_path)
    if column not in df.columns:
        raise FaultInjectionError(f"column {column!r} not found in {source_path}")
    if row_index < 0 or row_index >= len(df):
        raise FaultInjectionError(f"row_index={row_index} is out of range for {len(df)} row(s)")
    # Widen to a generic dtype first: `new_value` (a str) may not fit the
    # column's current numeric dtype (e.g. an int64 target like `churn`),
    # and a plain `.loc` assignment would raise rather than inject the fault.
    widened = df[column].astype(object)
    widened.iloc[row_index] = new_value
    df[column] = widened
    return _write_csv(df, out_path)


def flip_target_encoding(
    source_csv_path: Path | str, out_csv_path: Path | str, *, target_column: str
) -> Path:
    """Swap a binary 0/1 target's labels (`0<->1`) for every row — the same
    dtype and the same closed domain, but the label's *meaning* is inverted.
    Expected: `TARGET_POSITIVE_RATE_DRIFT`, only if `target.drift` is
    declared (this mutation does not, by itself, change dtype or domain, so
    schema-level checks alone would not catch it — that is the point)."""
    source_path, out_path = Path(source_csv_path), Path(out_csv_path)
    _guard_distinct_paths(source_path, out_path)
    df = _read_csv(source_path)
    if target_column not in df.columns:
        raise FaultInjectionError(f"column {target_column!r} not found in {source_path}")
    observed = set(pd.Series(df[target_column]).dropna().unique().tolist())
    if not observed <= {0, 1}:
        raise FaultInjectionError(
            f"flip_target_encoding only supports a binary 0/1 target; observed values: {sorted(observed)}"
        )
    df[target_column] = df[target_column].map({0: 1, 1: 0})
    return _write_csv(df, out_path)


def truncate_dataset(
    source_csv_path: Path | str, out_csv_path: Path | str, *, keep_rows: int
) -> Path:
    """Keep only the first `keep_rows` rows. Expected: `MODELING_MIN_ROWS`
    (if `keep_rows` falls below the modeling-readiness floor) and, because
    the bytes changed, `INTEGRITY_SHA256_MATCH`."""
    source_path, out_path = Path(source_csv_path), Path(out_csv_path)
    _guard_distinct_paths(source_path, out_path)
    df = _read_csv(source_path)
    if keep_rows < 0:
        raise FaultInjectionError(f"keep_rows must be >= 0, got {keep_rows}")
    return _write_csv(df.head(keep_rows), out_path)


def corrupt_contract_json(source_contract_path: Path | str, out_contract_path: Path | str) -> Path:
    """Truncate the contract JSON's bytes so it no longer parses. Expected:
    `ARTIFACTS_CONTRACT_JSON_PARSES` fails, and every downstream family is
    skipped (the documented "prerequisite gating" behaviour)."""
    source_path, out_path = Path(source_contract_path), Path(out_contract_path)
    _guard_distinct_paths(source_path, out_path)
    original = source_path.read_bytes()
    if len(original) < 2:
        raise FaultInjectionError(f"contract JSON too small to truncate meaningfully: {source_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(original[: len(original) // 2])  # cuts mid-structure, guaranteed invalid JSON
    return out_path


def contract_only_change(
    source_contract_path: Path | str, out_contract_path: Path | str, *, drop_column: str
) -> Path:
    """Remove `drop_column` from the contract's `columns` list AND from
    `integrity.column_order`/`column_count` — the CSV itself is untouched.

    Both removals are needed to keep the mutated JSON a *structurally valid*
    `DatasetContract` on its own (its cross-field validators reject
    `column_order` naming an undeclared column just as strictly as they
    reject `columns` under-declaring `column_order`) — the intended fault is
    "the contract quietly stopped knowing about this column", not "the
    contract is now self-contradictory", which would be caught by
    `ARTIFACTS_CONTRACT_SCHEMA_VALID` instead and prove nothing about
    `SCHEMA_UNKNOWN_COLUMN`.

    Refuses `drop_column` values referenced by `required_features`,
    `excluded_features`, or `primary_key` — removing those would also break
    the contract's own self-consistency validators for reasons unrelated to
    this scenario; pick a plain, unreferenced feature column instead.

    Expected: `SCHEMA_UNKNOWN_COLUMN` at whatever severity
    `validation_policy.on_unknown_column` declares (default `"warn"`) —
    proving a contract-only change does not automatically block the gate.
    """
    source_path, out_path = Path(source_contract_path), Path(out_contract_path)
    _guard_distinct_paths(source_path, out_path)
    data = json.loads(source_path.read_text(encoding="utf-8"))

    referenced = (
        set(data.get("required_features", []))
        | {f.get("name") for f in data.get("excluded_features", [])}
        | set(data.get("primary_key", {}).get("columns", []))
    )
    if drop_column in referenced:
        raise FaultInjectionError(
            f"column {drop_column!r} is referenced by required_features/excluded_features/"
            "primary_key — removing it would break the contract's own self-consistency "
            "rules for reasons unrelated to this scenario; choose an unreferenced column"
        )

    before = len(data.get("columns", []))
    data["columns"] = [c for c in data.get("columns", []) if c.get("name") != drop_column]
    if len(data["columns"]) == before:
        raise FaultInjectionError(f"column {drop_column!r} not found in contract columns")

    integrity = data.get("integrity", {})
    if drop_column in integrity.get("column_order", []):
        integrity["column_order"] = [c for c in integrity["column_order"] if c != drop_column]
        integrity["column_count"] = len(integrity["column_order"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path
