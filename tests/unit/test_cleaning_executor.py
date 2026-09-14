"""Unit tests — `CleaningPlan` guardrail + `tools/cleaning_tools.execute_plan`
(PROJECT_PLAN.md §D.1 points 6–8).

Covers every allowed operation (`drop_duplicates`, `impute`, `cast`,
`rename`, `drop_column`, `clip`, `standardize_category`), plus the invalid
cases: unknown operation, nonexistent column, bad cast, rename collision,
invalid mapping/params. Proves same input + plan -> same output.

Runnable two ways:
  * ``pytest tests/unit/test_cleaning_executor.py``
  * ``python tests/unit/test_cleaning_executor.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from harbor_vale.plans.cleaning_plan import (  # noqa: E402
    CastOp,
    CleaningPlan,
    ClipOp,
    DropColumnOp,
    DropDuplicatesOp,
    ImputeOp,
    RenameOp,
    StandardizeCategoryOp,
    validate_cleaning_plan,
)
from harbor_vale.tools.cleaning_tools import CleaningExecutionError, execute_plan  # noqa: E402
from harbor_vale.tools.profiling_tools import profile_dataframe  # noqa: E402


def _sample_df() -> "pd.DataFrame":
    return pd.DataFrame(
        {
            "a": [1, 1, 2, 3],
            "b": ["x", "x", "y", "z"],
            "money": ["10.5", "20.0", " ", "5.25"],
            "flag": ["Yes", "No", "Yes", "No"],
        }
    )


# --- drop_duplicates ----------------------------------------------------------

def test_drop_duplicates_removes_exact_row_duplicates() -> None:
    df = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})  # rows 0 and 1 are identical
    plan = CleaningPlan(operations=[DropDuplicatesOp(reason="remove exact duplicate rows")])
    profile = profile_dataframe(df)
    ok, validated = validate_cleaning_plan(plan, profile=profile)
    assert ok
    cleaned = execute_plan(df, validated)
    assert len(cleaned) == 2


def test_drop_duplicates_with_subset() -> None:
    df = _sample_df()
    plan = CleaningPlan(operations=[DropDuplicatesOp(subset=["a"], reason="one row per a-value")])
    ok, validated = validate_cleaning_plan(plan, profile=profile_dataframe(df))
    assert ok
    cleaned = execute_plan(df, validated)
    assert len(cleaned) == 3


# --- impute --------------------------------------------------------------------

def test_impute_constant_fills_coerced_nulls() -> None:
    df = _sample_df()
    profile = profile_dataframe(df)
    plan = CleaningPlan(
        operations=[
            CastOp(column="money", target_dtype="float64", reason="numeric coercion"),
            ImputeOp(column="money", strategy="constant", value=0.0, reason="blank placeholder rows"),
        ]
    )
    ok, validated = validate_cleaning_plan(plan, profile=profile)
    assert ok
    cleaned = execute_plan(df, validated)
    assert cleaned["money"].isnull().sum() == 0
    assert cleaned["money"].iloc[2] == 0.0


def test_impute_on_zero_null_column_is_rejected_by_the_guardrail() -> None:
    df = _sample_df()
    profile = profile_dataframe(df)
    plan = CleaningPlan(operations=[ImputeOp(column="a", strategy="constant", value=0, reason="x")])
    ok, msg = validate_cleaning_plan(plan, profile=profile)
    assert ok is False
    assert "zero measured nulls" in msg


def test_impute_mean_strategy() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, None, 4.0]})
    profile = profile_dataframe(df)
    plan = CleaningPlan(operations=[ImputeOp(column="n", strategy="mean", reason="fill with mean")])
    ok, validated = validate_cleaning_plan(plan, profile=profile)
    assert ok
    cleaned = execute_plan(df, validated)
    assert cleaned["n"].iloc[2] == (1.0 + 2.0 + 4.0) / 3


def test_impute_constant_without_value_is_a_structural_rejection() -> None:
    try:
        ImputeOp(column="n", strategy="constant", reason="x")
    except ValidationError as exc:
        assert "value" in str(exc)
    else:
        raise AssertionError("expected ValidationError: constant strategy requires value")


# --- cast ------------------------------------------------------------------------

def test_cast_to_float64() -> None:
    df = _sample_df()
    profile = profile_dataframe(df)
    plan = CleaningPlan(operations=[CastOp(column="a", target_dtype="float64", reason="make numeric")])
    ok, validated = validate_cleaning_plan(plan, profile=profile)
    assert ok
    cleaned = execute_plan(df, validated)
    assert str(cleaned["a"].dtype) == "float64"


def test_cast_to_int64_with_remaining_nulls_raises_execution_error() -> None:
    df = _sample_df()
    profile = profile_dataframe(df)
    plan = CleaningPlan(operations=[CastOp(column="money", target_dtype="int64", reason="bad: nulls remain")])
    ok, validated = validate_cleaning_plan(plan, profile=profile)
    assert ok  # structurally/semantically fine — the guardrail can't know coercion will leave nulls
    try:
        execute_plan(df, validated)
    except CleaningExecutionError as exc:
        assert "still has null values" in str(exc)
    else:
        raise AssertionError("expected CleaningExecutionError for int64 cast with remaining nulls")


def test_unsupported_cast_target_is_a_structural_rejection() -> None:
    try:
        CastOp(column="a", target_dtype="datetime64", reason="x")
    except ValidationError:
        pass
    else:
        raise AssertionError("expected ValidationError: datetime64 is not in CastTargetDtype")


# --- rename ----------------------------------------------------------------------

def test_rename_changes_the_column_name() -> None:
    df = _sample_df()
    profile = profile_dataframe(df)
    plan = CleaningPlan(operations=[RenameOp(old_name="a", new_name="a_renamed", reason="canonical name")])
    ok, validated = validate_cleaning_plan(plan, profile=profile)
    assert ok
    cleaned = execute_plan(df, validated)
    assert "a_renamed" in cleaned.columns and "a" not in cleaned.columns


def test_rename_collision_is_rejected_by_the_guardrail() -> None:
    df = _sample_df()
    profile = profile_dataframe(df)
    plan = CleaningPlan(operations=[RenameOp(old_name="a", new_name="b", reason="collides with existing column")])
    ok, msg = validate_cleaning_plan(plan, profile=profile)
    assert ok is False
    assert "collides" in msg


def test_rename_nonexistent_column_is_rejected_by_the_guardrail() -> None:
    df = _sample_df()
    profile = profile_dataframe(df)
    plan = CleaningPlan(operations=[RenameOp(old_name="not_a_column", new_name="x", reason="y")])
    ok, msg = validate_cleaning_plan(plan, profile=profile)
    assert ok is False
    assert "not found" in msg


# --- drop_column -------------------------------------------------------------------

def test_drop_column_removes_it() -> None:
    df = _sample_df()
    profile = profile_dataframe(df)
    plan = CleaningPlan(operations=[DropColumnOp(column="flag", reason="not needed")])
    ok, validated = validate_cleaning_plan(plan, profile=profile)
    assert ok
    cleaned = execute_plan(df, validated)
    assert "flag" not in cleaned.columns


def test_drop_nonexistent_column_is_rejected_by_the_guardrail() -> None:
    df = _sample_df()
    profile = profile_dataframe(df)
    plan = CleaningPlan(operations=[DropColumnOp(column="ghost", reason="x")])
    ok, msg = validate_cleaning_plan(plan, profile=profile)
    assert ok is False
    assert "not found" in msg


# --- clip ------------------------------------------------------------------------

def test_clip_bounds_values() -> None:
    df = pd.DataFrame({"n": [-5.0, 0.0, 10.0, 200.0]})
    profile = profile_dataframe(df)
    plan = CleaningPlan(operations=[ClipOp(column="n", min=0.0, max=100.0, reason="business range")])
    ok, validated = validate_cleaning_plan(plan, profile=profile)
    assert ok
    cleaned = execute_plan(df, validated)
    assert cleaned["n"].tolist() == [0.0, 0.0, 10.0, 100.0]


def test_clip_requires_at_least_one_bound() -> None:
    try:
        ClipOp(column="n", reason="x")
    except ValidationError as exc:
        assert "at least one" in str(exc)
    else:
        raise AssertionError("expected ValidationError: clip requires min or max")


# --- standardize_category ------------------------------------------------------------

def test_standardize_category_remaps_values() -> None:
    df = _sample_df()
    profile = profile_dataframe(df)
    plan = CleaningPlan(
        operations=[StandardizeCategoryOp(column="flag", mapping={"Yes": "1", "No": "0"}, reason="binary encoding")]
    )
    ok, validated = validate_cleaning_plan(plan, profile=profile)
    assert ok
    cleaned = execute_plan(df, validated)
    assert cleaned["flag"].tolist() == ["1", "0", "1", "0"]


def test_standardize_category_with_incomplete_mapping_raises_execution_error() -> None:
    df = _sample_df()
    profile = profile_dataframe(df)
    plan = CleaningPlan(
        operations=[StandardizeCategoryOp(column="flag", mapping={"Yes": "1"}, reason="missing 'No' mapping")]
    )
    ok, validated = validate_cleaning_plan(plan, profile=profile)
    assert ok  # structurally fine; the gap only shows up at execution
    try:
        execute_plan(df, validated)
    except CleaningExecutionError as exc:
        assert "not covered" in str(exc)
    else:
        raise AssertionError("expected CleaningExecutionError for an incomplete mapping")


def test_standardize_category_empty_mapping_is_a_structural_rejection() -> None:
    try:
        StandardizeCategoryOp(column="flag", mapping={}, reason="x")
    except ValidationError:
        pass
    else:
        raise AssertionError("expected ValidationError: empty mapping")


# --- unknown operation / no eval ------------------------------------------------------

def test_unknown_operation_is_a_structural_rejection() -> None:
    try:
        CleaningPlan.model_validate({"operations": [{"op": "eval_expression", "code": "os.system('rm -rf /')"}]})
    except ValidationError:
        pass
    else:
        raise AssertionError("expected ValidationError for an unsupported operation")


def test_arbitrary_extra_field_is_rejected() -> None:
    """`extra='forbid'` on every op model — an agent cannot smuggle in an
    unrecognised field (e.g. a hidden 'eval' key) alongside a valid op."""
    try:
        CleaningPlan.model_validate(
            {"operations": [{"op": "drop_column", "column": "a", "reason": "x", "eval": "danger"}]}
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("expected ValidationError for an extra field")


# --- determinism -----------------------------------------------------------------

def test_same_input_and_plan_produce_the_same_output() -> None:
    df = _sample_df()
    profile = profile_dataframe(df)
    plan = CleaningPlan(
        operations=[
            CastOp(column="money", target_dtype="float64", reason="numeric coercion"),
            ImputeOp(column="money", strategy="constant", value=0.0, reason="blank rows"),
            StandardizeCategoryOp(column="flag", mapping={"Yes": "1", "No": "0"}, reason="binary encoding"),
        ]
    )
    ok, validated = validate_cleaning_plan(plan, profile=profile)
    assert ok
    result1 = execute_plan(df, validated)
    result2 = execute_plan(df, validated)
    pd.testing.assert_frame_equal(result1, result2)


def test_execute_plan_never_mutates_the_original_dataframe() -> None:
    df = _sample_df()
    original = df.copy(deep=True)
    profile = profile_dataframe(df)
    plan = CleaningPlan(operations=[DropColumnOp(column="flag", reason="x")])
    ok, validated = validate_cleaning_plan(plan, profile=profile)
    assert ok
    execute_plan(df, validated)
    pd.testing.assert_frame_equal(df, original)


if __name__ == "__main__":
    _failures: list[str] = []
    for _name, _fn in sorted(
        (n, f) for n, f in dict(globals()).items() if n.startswith("test_") and callable(f)
    ):
        try:
            _fn()
        except Exception as exc:  # noqa: BLE001
            _failures.append(_name)
            print(f"FAIL  {_name}: {exc.__class__.__name__}: {exc}")
        else:
            print(f"PASS  {_name}")
    print(f"\n{len(_failures)} failed" if _failures else "\nall passed")
    sys.exit(1 if _failures else 0)
