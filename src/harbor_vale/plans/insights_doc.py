"""`InsightsDoc` — the EDA & Insights Analyst agent's output (PROJECT_PLAN.md
§D.2 point 6).

**The anti-hallucination design (§D.2 point 7):** every insight carries an
`evidence_stat_key` that MUST resolve to a real key in the deterministic EDA
statistics dictionary (`tools/eda_tools.compute_eda_stats()`). An insight
whose key does not exist in that dictionary is rejected outright — the
future LLM may *interpret* a number Python already measured; it may never
*invent* one. This is the exact companion mechanism to
`contract_draft.py`'s `business_range`/`unit` justification requirements:
a different field, the same architectural discipline (§E.1 rule 3/4).

Deliberate omission: no `from __future__ import annotations` (the proven
CrewAI 1.15.20 guardrail-annotation rule, Sessions 17–18 — see
`plans/contract_draft.py`'s docstring for the full explanation).
"""

from typing import Any, Tuple

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


def _non_empty(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be empty")
    return stripped


class Insight(BaseModel):
    """One narrative insight (§D.2 point 6): what was observed, why it
    matters, what to do about it — each backed by exactly one measured
    statistic."""

    model_config = ConfigDict(extra="forbid")

    title: str
    observation: str
    business_implication: str
    recommended_action: str
    evidence_stat_key: str

    @field_validator("title", "observation", "business_implication", "recommended_action", "evidence_stat_key")
    @classmethod
    def _not_empty(cls, v: str, info) -> str:  # noqa: ANN001
        return _non_empty(v, f"insight.{info.field_name}")


class InsightsDoc(BaseModel):
    """§D.2 point 6's full output: `headline`, `insights[]`, `data_caveats[]`."""

    model_config = ConfigDict(extra="forbid")

    headline: str
    insights: list[Insight]
    data_caveats: list[str] = []

    @field_validator("headline")
    @classmethod
    def _headline_not_empty(cls, v: str) -> str:
        return _non_empty(v, "headline")

    @field_validator("insights")
    @classmethod
    def _at_least_one_insight(cls, v: list[Insight]) -> list[Insight]:
        if not v:
            raise ValueError("insights must not be empty")
        return v


# ---------------------------------------------------------------------------
# Guardrail — every evidence_stat_key must exist in the real eda_stats dict.
# ---------------------------------------------------------------------------


class InsightsDocRejected(Exception):
    """Internal marker for `validate_insights_doc`'s semantic failures —
    caught inside the function; never escapes it."""


def _validate_semantics(doc: InsightsDoc, eda_stats: dict[str, Any]) -> None:
    known_keys = set(eda_stats)
    for i, insight in enumerate(doc.insights):
        if insight.evidence_stat_key not in known_keys:
            raise InsightsDocRejected(
                f"insights[{i}] ({insight.title!r}): evidence_stat_key "
                f"{insight.evidence_stat_key!r} does not exist in the measured EDA "
                "statistics — an insight without measurable backing is rejected "
                "(PROJECT_PLAN.md §D.2 point 7's anti-hallucination rule)"
            )


def validate_insights_doc(output, *, eda_stats: dict[str, Any] | None = None) -> Tuple[bool, Any]:
    """Parse and validate an `InsightsDoc` (§D.2 point 7).

    Same guardrail contract as every other `plans/*` validator in this
    project: accepts a `TaskOutput`-shaped object (`.raw`), raw JSON
    `str`/`bytes`, a `dict`, or an already-constructed `InsightsDoc`; never
    raises; returns `(True, InsightsDoc)` or `(False, message)`.

    Args:
        eda_stats: the flat `dict[str, Any]` `compute_eda_stats()` produced
            for the SAME dataset this doc claims to interpret — the single
            source of truth every `evidence_stat_key` is checked against.
            Defaults to `None` only so this function's own signature stays
            constructible as a bare `Task(guardrail=...)` — verified
            empirically that CrewAI 1.15.20 only counts REQUIRED parameters
            against its "exactly one parameter" rule, so a defaulted keyword
            parameter is fine on the function itself; a real caller (Phase
            6+, via a one-argument closure per `Task`) must always supply a
            real `eda_stats` dict.
    """
    if eda_stats is None:
        return False, "validate_insights_doc: no eda_stats supplied — this is a caller wiring error, not a doc defect"

    raw = getattr(output, "raw", output)

    try:
        if isinstance(raw, InsightsDoc):
            doc = raw
        elif isinstance(raw, (str, bytes, bytearray)):
            doc = InsightsDoc.model_validate_json(raw)
        elif isinstance(raw, dict):
            doc = InsightsDoc.model_validate(raw)
        else:
            return False, f"unsupported guardrail input type: {type(raw).__name__}"
    except ValidationError as exc:
        return False, f"InsightsDoc failed schema validation: {exc}"
    except Exception as exc:  # noqa: BLE001 — a guardrail must never raise
        return False, f"InsightsDoc could not be parsed: {exc}"

    try:
        _validate_semantics(doc, eda_stats)
    except InsightsDocRejected as exc:
        return False, f"InsightsDoc failed semantic validation: {exc}"

    return True, doc
