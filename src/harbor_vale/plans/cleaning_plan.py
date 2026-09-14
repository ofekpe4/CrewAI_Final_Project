"""`CleaningPlan` — the Data Quality Inspector agent's output (PROJECT_PLAN.md
§D.1 point 6): a closed set of typed cleaning operations, each with a
required `reason`, never arbitrary code.

**What belongs here:** which operation, on which column(s), with what
parameters, and *why* (§D.1 point 2: "מנמק כל החלטה"). **What must NEVER
appear here:** a Python expression, an `eval`-able string, or any operation
outside the closed vocabulary below (§D.1 point 6 lists exactly seven —
`drop_duplicates`, `impute`, `cast`, `rename`, `drop_column`, `clip`,
`standardize_category` — nothing else is implemented; an unsupported
operation name is a Pydantic structural rejection, not a runtime surprise).

Deliberate omission: **no `from __future__ import annotations`** — the same
proven CrewAI 1.15.20 guardrail-annotation rule as
`plans/contract_draft.py` (docs/architecture.md, Sessions 17–18): a
stringized return annotation breaks `Task(guardrail=fn)` construction. The
corrected rule (Session 18) is: a REAL, non-stringized annotation, second
type argument literally `Any`; `tuple[bool, Any]` and `Tuple[bool, Any]`
are equally accepted. This module uses `Tuple[bool, Any]`.
"""

from typing import Any, Literal, Tuple

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from harbor_vale.tools.profiling_tools import DatasetProfile

# ---------------------------------------------------------------------------
# The closed operation vocabulary (§D.1 point 6) — one model per op, each
# discriminated by its own `op` Literal so a plan can never smuggle in an
# eighth kind of step. `reason` is required on every one (§D.1 point 2).
# ---------------------------------------------------------------------------


def _non_empty(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be empty")
    return stripped


class DropDuplicatesOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["drop_duplicates"] = "drop_duplicates"
    subset: list[str] | None = Field(
        default=None, description="Columns defining a duplicate; None = every column."
    )
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason_not_empty(cls, v: str) -> str:
        return _non_empty(v, "drop_duplicates.reason")


ImputeStrategy = Literal["constant", "mean", "median", "mode"]


class ImputeOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["impute"] = "impute"
    column: str
    strategy: ImputeStrategy
    value: float | str | None = Field(
        default=None, description="Required when strategy == 'constant'; unused otherwise."
    )
    reason: str

    @field_validator("column", "reason")
    @classmethod
    def _not_empty(cls, v: str, info) -> str:  # noqa: ANN001
        return _non_empty(v, f"impute.{info.field_name}")

    @model_validator(mode="after")
    def _value_required_for_constant(self) -> "ImputeOp":
        # A plain field_validator would NOT fire here when `value` is
        # omitted and falls back to its own default (pydantic v2 skips
        # field validators on unvalidated defaults) — model_validator(mode
        # ="after") always runs, regardless of whether `value` was
        # explicitly supplied.
        if self.strategy == "constant" and self.value is None:
            raise ValueError("impute.value is required when strategy == 'constant'")
        return self


# The only dtypes a `cast` may target — deliberately closed, so an agent
# cannot request an exotic/unsafe pandas dtype string.
CastTargetDtype = Literal["int64", "float64", "str", "bool"]


class CastOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["cast"] = "cast"
    column: str
    target_dtype: CastTargetDtype
    reason: str

    @field_validator("column", "reason")
    @classmethod
    def _not_empty(cls, v: str, info) -> str:  # noqa: ANN001
        return _non_empty(v, f"cast.{info.field_name}")


class RenameOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["rename"] = "rename"
    old_name: str
    new_name: str
    reason: str

    @field_validator("old_name", "new_name", "reason")
    @classmethod
    def _not_empty(cls, v: str, info) -> str:  # noqa: ANN001
        return _non_empty(v, f"rename.{info.field_name}")


class DropColumnOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["drop_column"] = "drop_column"
    column: str
    reason: str

    @field_validator("column", "reason")
    @classmethod
    def _not_empty(cls, v: str, info) -> str:  # noqa: ANN001
        return _non_empty(v, f"drop_column.{info.field_name}")


class ClipOp(BaseModel):
    """Mirrors `contract.schema.BusinessRangeConstraint`'s own shape/rule
    (at least one bound; both optional individually) — deliberately, since
    both express the same underlying idea (a defensible numeric bound), one
    as a contract constraint, one as a cleaning action."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["clip"] = "clip"
    column: str
    min: float | None = None
    max: float | None = None
    reason: str

    @field_validator("column", "reason")
    @classmethod
    def _not_empty(cls, v: str, info) -> str:  # noqa: ANN001
        return _non_empty(v, f"clip.{info.field_name}")

    @model_validator(mode="after")
    def _at_least_one_bound(self) -> "ClipOp":
        if self.min is None and self.max is None:
            raise ValueError("clip requires at least one of min/max")
        return self


class StandardizeCategoryOp(BaseModel):
    """Remaps category *values* (string -> string) only — never a dtype
    change (that is `cast`'s job, applied afterward if needed). Used for
    the Telco `churn` column's `"Yes"/"No"` -> `"1"/"0"` remap, followed by
    a `cast` to `int64` (see `tests/fixtures/hardcoded_plans.py`)."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["standardize_category"] = "standardize_category"
    column: str
    mapping: dict[str, str]
    reason: str

    @field_validator("column", "reason")
    @classmethod
    def _not_empty(cls, v: str, info) -> str:  # noqa: ANN001
        return _non_empty(v, f"standardize_category.{info.field_name}")

    @field_validator("mapping")
    @classmethod
    def _mapping_not_empty(cls, v: dict[str, str]) -> dict[str, str]:
        if not v:
            raise ValueError("standardize_category.mapping must not be empty")
        return v


CleaningOperation = (
    DropDuplicatesOp | ImputeOp | CastOp | RenameOp | DropColumnOp | ClipOp | StandardizeCategoryOp
)


class CleaningPlan(BaseModel):
    """§D.1 point 6's full output: an ordered list of typed operations.
    Order matters — `cleaning_tools.execute_plan()` applies them strictly in
    list order (e.g. a `cast` that introduces nulls via coercion, followed
    by an `impute` that fills them, only makes sense in that order)."""

    model_config = ConfigDict(extra="forbid")

    operations: list[CleaningOperation]


# ---------------------------------------------------------------------------
# Guardrail — semantic cross-validation against a real DatasetProfile
# (§D.1 point 7: "כל col קיים בפרופיל + impute אסור על עמודה ללא nulls").
# ---------------------------------------------------------------------------


class CleaningPlanRejected(Exception):
    """Internal marker for `validate_cleaning_plan`'s semantic failures —
    caught inside the function; never escapes it (a guardrail must never
    raise)."""


def _validate_semantics(plan: CleaningPlan, profile: DatasetProfile) -> None:
    """Simulate the plan's effect on the column-name/null-count state,
    checking each operation against that RUNNING state (not just the
    original profile) — because a `rename` earlier in the plan changes what
    "exists" for a later operation, and a `cast` earlier in the plan can
    introduce nulls a later `impute` on that same column may need to fill,
    even though the ORIGINAL profile shows zero nulls for it (pandas'
    `isnull()` does not count whitespace-only strings — data/README.md
    §7.1's exact TotalCharges case). Raises `CleaningPlanRejected` with a
    human-readable message on the first violation found.
    """
    known_columns = {c.name for c in profile.columns}
    null_counts = {c.name: c.null_count for c in profile.columns}
    # Columns whose true post-cast null count cannot be known without
    # actually executing pandas — set to None (== "unknown, do not gate on
    # it") the moment a `cast` targets that column.
    nulls_uncertain: set[str] = set()

    for i, op in enumerate(plan.operations):
        where = f"operations[{i}] ({op.op})"

        if isinstance(op, DropDuplicatesOp):
            if op.subset is not None:
                unresolved = [c for c in op.subset if c not in known_columns]
                if unresolved:
                    raise CleaningPlanRejected(f"{where}: subset column(s) not found: {unresolved}")

        elif isinstance(op, ImputeOp):
            if op.column not in known_columns:
                raise CleaningPlanRejected(f"{where}: column {op.column!r} not found")
            if op.column not in nulls_uncertain and null_counts.get(op.column, 0) == 0:
                raise CleaningPlanRejected(
                    f"{where}: impute is not allowed on column {op.column!r}, which has zero "
                    "measured nulls in the profile (and no preceding cast on it in this plan "
                    "could have introduced any)"
                )

        elif isinstance(op, CastOp):
            if op.column not in known_columns:
                raise CleaningPlanRejected(f"{where}: column {op.column!r} not found")
            nulls_uncertain.add(op.column)  # coercion may introduce new nulls

        elif isinstance(op, RenameOp):
            if op.old_name not in known_columns:
                raise CleaningPlanRejected(f"{where}: old_name {op.old_name!r} not found")
            if op.new_name in known_columns and op.new_name != op.old_name:
                raise CleaningPlanRejected(
                    f"{where}: new_name {op.new_name!r} collides with an existing column"
                )
            known_columns.discard(op.old_name)
            known_columns.add(op.new_name)
            if op.old_name in null_counts:
                null_counts[op.new_name] = null_counts.pop(op.old_name)
            if op.old_name in nulls_uncertain:
                nulls_uncertain.discard(op.old_name)
                nulls_uncertain.add(op.new_name)

        elif isinstance(op, DropColumnOp):
            if op.column not in known_columns:
                raise CleaningPlanRejected(f"{where}: column {op.column!r} not found")
            known_columns.discard(op.column)

        elif isinstance(op, ClipOp):
            if op.column not in known_columns:
                raise CleaningPlanRejected(f"{where}: column {op.column!r} not found")

        elif isinstance(op, StandardizeCategoryOp):
            if op.column not in known_columns:
                raise CleaningPlanRejected(f"{where}: column {op.column!r} not found")

        else:  # pragma: no cover — unreachable: the discriminated union is closed
            raise CleaningPlanRejected(f"{where}: unsupported operation")


_CLEANING_PLAN_ADAPTER: TypeAdapter[CleaningPlan] = TypeAdapter(CleaningPlan)


def validate_cleaning_plan(output, *, profile: DatasetProfile | None = None) -> Tuple[bool, Any]:
    """Parse and validate a `CleaningPlan` (§D.1 point 7).

    Same guardrail contract as `plans/contract_draft.py.validate_contract_draft`:
    accepts a CrewAI `TaskOutput`-shaped object (`.raw`), raw JSON `str`/
    `bytes`, a `dict`, or an already-constructed `CleaningPlan`; never lets a
    bare `pydantic.ValidationError` (structural failure) or
    `CleaningPlanRejected` (semantic failure) escape; returns `(True,
    CleaningPlan)` or `(False, message)`. Never raises.

    Args:
        profile: the `DatasetProfile` the plan is validated against — the
            profile of the data the plan is ABOUT TO run against (raw data
            for the Inspector agent's plan), not a profile of an unrelated
            dataset. Defaults to `None` ONLY so this function's signature
            stays compatible with CrewAI's `Task.guardrail` constructor
            check ("must accept exactly one parameter" — verified empirically
            against the pinned `crewai==1.15.20`: a keyword parameter WITH a
            default does not count against that limit, only a required one
            would). A real caller must always pass a real `profile` — Phase
            6+ wraps this function in a one-argument closure per `Task`
            instance that supplies it, e.g.
            `lambda output: validate_cleaning_plan(output, profile=the_run's_profile)`.
    """
    if profile is None:
        return False, "validate_cleaning_plan: no profile supplied — this is a caller wiring error, not a plan defect"

    raw = getattr(output, "raw", output)

    try:
        if isinstance(raw, CleaningPlan):
            plan = raw
        elif isinstance(raw, (str, bytes, bytearray)):
            plan = CleaningPlan.model_validate_json(raw)
        elif isinstance(raw, dict):
            plan = CleaningPlan.model_validate(raw)
        else:
            return False, f"unsupported guardrail input type: {type(raw).__name__}"
    except ValidationError as exc:
        return False, f"CleaningPlan failed schema validation: {exc}"
    except Exception as exc:  # noqa: BLE001 — a guardrail must never raise
        return False, f"CleaningPlan could not be parsed: {exc}"

    try:
        _validate_semantics(plan, profile)
    except CleaningPlanRejected as exc:
        return False, f"CleaningPlan failed semantic validation: {exc}"

    return True, plan
