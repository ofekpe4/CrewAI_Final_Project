"""ContractDraft — the Data Contract Architect agent's output (PROJECT_PLAN.md §D.3).

Deliberate omission: **no `from __future__ import annotations` in this
module.** docs/architecture.md §5/§14.10 documents a proven CrewAI 1.15.20
gotcha — with that import active, an annotated guardrail return type
(`-> tuple[bool, Any]`) becomes a string at class-definition time and
`Task(guardrail=fn)` raises at construction. `X | Y` union syntax still works
fine at runtime without the future import on Python 3.10+, so nothing here
needs it.

**What belongs in `ContractDraft` (§D.3 point 6, "אסור" list):** semantic
judgement and justification only — `semantic_type`, unit/nullable/
closed_domain/business_range declarations *with justification*,
`scale_sensitive` flags, the target's semantic stance, required/excluded
feature lists, and narrative `assumptions`.

**What must NEVER appear here:** measured statistics. There is no `min`,
`max`, `median`, `row_count`, or `sha256` field anywhere in this module —
not "optional and usually empty," but structurally absent, and every model
below sets `extra="forbid"` so an agent cannot smuggle one in either. Those
numbers exist only in `contract.schema.ColumnObserved` /
`TargetObserved` / `Integrity`, written solely by `contract/builder.py`
(§D.3 point 5: "אסור ... להמציא מספרי min/max/median").
"""

from typing import Any, Literal, Tuple

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from harbor_vale.contract.schema import (
    BusinessRangeConstraint,
    ClosedDomainConstraint,
    DtypeConstraint,
    EnforcementLevel,
    ExcludedFeature,
    NullableConstraint,
    ScaleDriftConstraint,
    SemanticType,
    TargetDriftConstraint,
    UnitConstraint,
    UniqueConstraint,
)


def _non_empty(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be empty")
    return stripped


class ColumnSemanticDraft(BaseModel):
    """One column's semantic judgement — no measurements (§D.3 point 6).

    Every constraint sub-field the Plan requires justification for
    (`business_range`, `unit`, `closed_domain`, `scale_drift`) reuses the
    exact same justification-enforcing models as the final `DatasetContract`
    (`contract.schema`), so an agent cannot produce a draft that would only
    fail justification checks later, at builder time — it fails immediately,
    at draft-parse time, in the guardrail. `scale_drift` is declared here in
    full (tolerance + justification), like every other constraint — not as a
    bare boolean the builder would then have to expand into a policy on its
    own judgement, which would smuggle a semantic decision into "measured"
    Python code (§E.1 rule 6, "נאכף ב-Python בלבד" — Python *enforces*, it
    does not *decide*).
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    semantic_type: SemanticType
    dtype: DtypeConstraint | None = None
    unit: UnitConstraint | None = None
    nullable: NullableConstraint
    closed_domain: ClosedDomainConstraint | None = None
    business_range: BusinessRangeConstraint | None = None
    scale_drift: ScaleDriftConstraint | None = None

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        return _non_empty(v, "column.name")


class TargetDraft(BaseModel):
    """The target's semantic stance (§D.3, §E.2 `target.constraints`).

    `dtype`, `closed_domain`, and `nullable` are required (not optional) —
    unlike a regular feature column, the target always needs an explicit
    stance on all three; there is no legitimate "no opinion" state for the
    single column the whole project measures success against. `drift` is
    optional: PROJECT_PLAN.md's example gives it a substantive justification
    ("a large shift in base rate implies the label's meaning changed"), so it
    is agent-declared like every other constraint, not builder-templated —
    and simply absent if the agent has no drift policy to declare.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    task_type: Literal["binary_classification"]
    dtype: DtypeConstraint
    closed_domain: ClosedDomainConstraint
    nullable: NullableConstraint
    drift: TargetDriftConstraint | None = None

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        return _non_empty(v, "target.name")


class PrimaryKeyDraft(BaseModel):
    """Which column(s) identify one row, and whether uniqueness is a
    constraint (§E.2 `primary_key`). This is a semantic call (Python cannot
    tell "the intended identifier" from "a column that happens to be
    unique") so it lives in the draft, not the builder.
    """

    model_config = ConfigDict(extra="forbid")

    columns: list[str]
    unique: UniqueConstraint

    @field_validator("columns")
    @classmethod
    def _columns_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("primary_key.columns must not be empty")
        return v


class ContractDraft(BaseModel):
    """The Data Contract Architect's full output (§D.3 point 6).

    Deliberately excludes `dataset_name`, `source_documentation_url`,
    `contract_version`, `created_at`, `created_by`, and `run_id` — those are
    deterministic run/dataset metadata the builder already knows without any
    LLM judgement (§E.1 rule 5, "מדיד מעל מוצהר"), so giving the draft a
    chance to declare (and disagree with) them would only create a spurious
    authority conflict.
    """

    model_config = ConfigDict(extra="forbid")

    target: TargetDraft
    required_features: list[str]
    excluded_features: list[ExcludedFeature]
    primary_key: PrimaryKeyDraft
    columns: list[ColumnSemanticDraft]
    assumptions: list[str]

    # --- structural self-consistency (§Phase 3 guardrail requirements) -----

    @model_validator(mode="after")
    def _column_names_unique(self) -> "ContractDraft":
        names = [c.name for c in self.columns]
        if len(set(names)) != len(names):
            raise ValueError("`columns` contains duplicate column names")
        return self

    @model_validator(mode="after")
    def _target_not_duplicated_as_a_column(self) -> "ContractDraft":
        if self.target.name in {c.name for c in self.columns}:
            raise ValueError(
                f"target {self.target.name!r} must not also appear in `columns` "
                "— the target is declared exactly once, in the `target` section"
            )
        return self

    @model_validator(mode="after")
    def _required_and_excluded_reference_declared_columns(self) -> "ContractDraft":
        declared = {c.name for c in self.columns}

        unresolved_required = [n for n in self.required_features if n not in declared]
        if unresolved_required:
            raise ValueError(
                f"required_features references undeclared column(s): {unresolved_required}"
            )
        if self.target.name in self.required_features:
            raise ValueError("target must not also appear in required_features")

        unresolved_excluded = [f.name for f in self.excluded_features if f.name not in declared]
        if unresolved_excluded:
            raise ValueError(
                f"excluded_features references undeclared column(s): {unresolved_excluded}"
            )

        hard_excluded = {
            f.name for f in self.excluded_features if f.enforcement == EnforcementLevel.HARD
        }
        conflict = hard_excluded & set(self.required_features)
        if conflict:
            raise ValueError(
                f"column(s) both hard-excluded and required_features: {sorted(conflict)}"
            )
        return self

    @model_validator(mode="after")
    def _primary_key_references_declared_columns(self) -> "ContractDraft":
        declared = {c.name for c in self.columns}
        unresolved = [n for n in self.primary_key.columns if n not in declared]
        if unresolved:
            raise ValueError(f"primary_key references undeclared column(s): {unresolved}")
        return self


# ---------------------------------------------------------------------------
# Guardrail — CrewAI Task guardrail contract (docs/architecture.md §5, §6,
# §14.1): takes exactly one positional argument, never raises
# `pydantic.ValidationError` itself, returns `(True, data)` or `(False, msg)`.
# Duck-typed so it also runs directly in tests today, with no CrewAI Task
# wired up yet (that is Phase 6 — no Agent/Task/Crew is created in Phase 3).
# ---------------------------------------------------------------------------


def validate_contract_draft(output) -> Tuple[bool, Any]:
    """Parse and validate a `ContractDraft` (§D.3 point 7).

    Accepts, in order of preference: a CrewAI `TaskOutput`-shaped object
    (anything exposing `.raw`), a raw JSON `str`/`bytes`, a plain `dict`, or
    an already-constructed `ContractDraft`. This guardrail **owns the parse**
    (docs/architecture.md §6 "Production rule") — it never assumes
    `output.pydantic` is already populated, and it never lets a bare
    `pydantic.ValidationError` escape.

    Every semantic rule the Plan requires — `business_range` needs
    justification, unit needs evidence, `exclusion_type` must be a real enum
    member, required/excluded features must reference declared columns,
    the target is declared exactly once, no measured-statistics field can be
    smuggled in (`extra="forbid"` everywhere) — is enforced by
    `ContractDraft`'s own field/model validators, so catching
    `pydantic.ValidationError` here is a complete, single-source-of-truth
    check rather than a second, divergent copy of the same rules.

    Returns:
        `(True, ContractDraft)` on success.
        `(False, str)` — a human-readable message — on any structural or
        semantic failure. Never raises.
    """
    raw = getattr(output, "raw", output)

    try:
        if isinstance(raw, ContractDraft):
            draft = raw
        elif isinstance(raw, (str, bytes, bytearray)):
            draft = ContractDraft.model_validate_json(raw)
        elif isinstance(raw, dict):
            draft = ContractDraft.model_validate(raw)
        else:
            return False, f"unsupported guardrail input type: {type(raw).__name__}"
    except ValidationError as exc:
        return False, f"ContractDraft failed schema validation: {exc}"
    except Exception as exc:  # noqa: BLE001 — a guardrail must never raise
        return False, f"ContractDraft could not be parsed: {exc}"

    return True, draft
