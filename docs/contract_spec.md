# The Dataset Contract — specification

> Scope: PROJECT_PLAN.md §E (Dataset Contract architecture), §D.3 (Data
> Contract Architect), §Phase 3. This is the human-readable reference for
> `src/harbor_vale/contract/schema.py`, `src/harbor_vale/contract/builder.py`,
> and `src/harbor_vale/plans/contract_draft.py`. Code and this document must
> stay in sync — if they disagree, treat that as a bug and fix the code or
> this doc, not the other way around by assumption.

## 1. Purpose — why Harbor & Vale needs a contract at all

Harbor & Vale's original incident (PROJECT_PLAN.md §A) happened because a
column's *scale* silently changed between two runs and nothing downstream
noticed — the pipeline kept working, the model kept scoring, and nobody knew
the numbers no longer meant what everyone assumed. A dataset contract is the
project's answer: a **machine-readable, versioned snapshot of what a dataset
is supposed to be**, written once by people/agents who understand the
business meaning, and checked automatically, every run, by deterministic
Python — without ever trusting a human (or an LLM) to notice a drift by eye.

The contract is the interface between:

- **Crew 1** (produces it, from a cleaned dataset), and
- **the validation gate** (Phase 4) and **Crew 2** (both consume it, and
  only it — never the raw data, never Crew 1's internal reasoning).

## 2. The central rule: `observed` != `constraints`

> **Observed facts describe what Python measured. Constraints are rules
> someone deliberately chose to enforce, with a reason.**

A dataset's maximum value *today* is a fact about today's data. It is not,
automatically, a rule about every future dataset. Confusing the two is
precisely the kind of mistake that hides a real change behind "well, it's
still within the range we've always seen" — when the range itself was never
supposed to be a hard ceiling.

Concretely:

- **`observed.*`** — every field is a measurement. Written only by
  `contract/builder.py`, directly from pandas, from the real CSV bytes. No
  agent, no LLM, no hand-edit ever sets these. They can never, by
  themselves, cause anything to fail.
- **`constraints.*`** — every field is optional (`None` = no enforcement)
  and, where PROJECT_PLAN.md requires it, carries a mandatory, non-empty
  `justification` explaining *why* this is a rule. Written by a validated
  `ContractDraft` (semantic judgement) and carried through the builder
  **unchanged** into the final contract. The builder never derives a
  constraint from an observation.

### BAD vs. GOOD, concretely

**BAD** — a measurement smuggled in as a rule:
```jsonc
// observed.max = 118.75
"business_range": { "min": 0, "max": 118.75, "justification": "the max we've seen so far" }
```
This looks reasonable and is exactly wrong: next month a legitimate premium
plan priced at 125.00 gets rejected, or — worse in the other direction — a
scale change to 11875.00 stays *inside* a range nobody actually reasoned
about, because the range was never a business decision in the first place.

**GOOD** — the actual output of this project's builder for the same column:
```jsonc
// observed.max = 118.75  (still recorded, as a fact)
"business_range": { "min": 0, "max": null,
                     "justification": "a recurring charge cannot be negative; no defensible upper bound exists — a future premium plan may legitimately exceed the observed maximum" }
```
`min: 0` **is** a real business rule (a recurring charge cannot be
negative) — that is a legitimate, justified constraint. `max: null` is the
honest statement that no such rule exists for the upper bound. Both facts
live in the same object; only one of them enforces anything.

A second example, for units (PROJECT_PLAN.md §Phase 2 criterion 11,
`data/README.md` §6.2):

**BAD:**
```jsonc
"unit": { "value": "USD", "evidence": "the dataset describes California customers" }
```
Geography is not currency documentation. This is metadata invented from an
inference, not evidence — exactly what PROJECT_PLAN.md §B and §E.1 rule 4
("אין מטא-דאטה בלי ראיה") forbid.

**GOOD** — what this project's contract actually says:
```jsonc
"unit": { "value": "currency_unspecified",
          "evidence": "the source documentation does not state a currency",
          "confidence": "low" }
```
Notice `evidence` is required even for the honest "unspecified" state — the
rule is not "provide evidence only when claiming something specific," it is
"every unit declaration must say what it's based on."

See `tests/unit/test_observed_not_enforced.py` for these claims proven
against a real, builder-produced contract — not asserted by hand.

## 3. Schema hierarchy

```
DatasetContract
├── contract_version, created_at, created_by, run_id      (deterministic metadata — builder-set)
├── dataset_name, source_documentation_url                (deterministic metadata — builder-set)
├── target: TargetContract
│   ├── name, task_type                                   (semantic — draft)
│   ├── constraints: TargetConstraints  { dtype?, closed_domain?, nullable? }
│   ├── observed: TargetObserved        { positive_rate, class_counts }   (measured — builder)
│   └── drift: TargetDriftConstraint?                      (semantic — draft, optional)
├── required_features: [str]                               (semantic — draft; must name declared columns)
├── excluded_features: [ExcludedFeature]                    (semantic — draft)
│   └── { name, exclusion_type, enforcement, justification }
├── primary_key: PrimaryKey
│   ├── columns: [str]
│   └── constraints: { unique: UniqueConstraint }
├── columns: [ColumnContract]                               (one entry per NON-target column)
│   └── { name, semantic_type,
│         observed: ColumnObserved       (measured — builder),
│         constraints: ColumnConstraints (semantic — draft, carried through unchanged) }
├── integrity: Integrity                                    (measured — builder)
│   └── { clean_data_sha256, row_count, column_count, column_order }
├── assumptions: [str]                                      (semantic — draft)
└── validation_policy: ValidationPolicy                     (Phase 4 gate policy knobs; declared, not executed, here)
```

`columns` covers every column **except** the target — the target has its
own section because its shape genuinely differs (`observed` is a positive
rate + class counts, not min/max/median; `constraints` cover dtype/domain/
nullable, not a business range). `DatasetContract` validates, on
construction, that `{target.name} ∪ {c.name for c in columns}` exactly
equals `integrity.column_order` — a contract that is internally
inconsistent about its own column list cannot be constructed at all.

## 4. Target

Binary classification only (`task_type: Literal["binary_classification"]`),
defined **exactly once** — a single field, not a list, so "exactly once" is
structural, not a rule that needs separate checking. Two further guardrails
enforce it can't be duplicated in spirit either: the target's name may not
also appear in `columns`, and it may not appear in `required_features`
(§Phase 3 required semantic rule #8).

`observed.positive_rate` is a measured fact about *this* dataset snapshot —
it is never hardcoded as a permanent invariant. If a drift policy on the
base rate is wanted, it is declared explicitly and separately, as
`target.drift` (`TargetDriftConstraint`: `positive_rate_tolerance_abs` +
`justification`) — e.g. Phase 2's measured 26.54% informs a sensible
*tolerance*, but the tolerance, and the reason for it, are what get
contracted, not the number itself.

## 5. Primary key

A semantic call (`ContractDraft.primary_key`), not something Python can
infer — "this column happens to be unique in the sample" and "this column
is the entity identifier" are different claims (a column could be unique by
accident). `primary_key.columns` must reference already-declared columns;
`unique` is a `UniqueConstraint` and, like every constraint here, requires a
non-empty justification.

## 6. Required / excluded features

- `required_features`: plain list of column names. Every name must resolve
  to a declared column (§Phase 3 rule #10); the target may never appear
  here.
- `excluded_features`: a list of `ExcludedFeature { name, exclusion_type,
  enforcement, justification }`. Every name must resolve to a declared
  column; a `hard`-enforcement exclusion may not simultaneously be listed in
  `required_features` (a direct logical conflict) — an `advisory` one may
  (the Feature Engineer is allowed to include it anyway, with their own
  justification, per §E.4).

### Exclusion types (PROJECT_PLAN.md §E.4 — closed enum, nothing invented)

| `exclusion_type` | Meaning | `enforcement` | Example |
|---|---|:---:|---|
| `identifier` | A unique key; no generalizable signal | `hard` | `customer_id` |
| `target_leakage` | Information not legitimately available at prediction time, or that exposes the label improperly | `hard` | a column derived from the label, or recorded after the churn event |
| `redundancy_collinearity` | Derivable from other features; collinear; model-simplification candidate | `advisory` | `total_charges ≈ tenure_months × monthly_charges` |
| `modeling_simplicity` | Too high-cardinality, single-valued, or noisy to be useful | `advisory` | a raw ZIP code |
| `ethical_sensitive` | A protected attribute or its proxy | `hard` | gender, race |

**`target_leakage` requires genuine temporal/semantic justification** — a
column being *correlated* with the target is never sufficient by itself
(that is `redundancy_collinearity`). This project's own worked example is
the correction that motivated the distinction: Phase 2 (`data/README.md`
§6.3) established, from source evidence, that `total_charges` is measured
at the **same** observation snapshot as `churn` and `tenure_months` — i.e.
it is genuinely available at prediction time. It is excluded here as
`redundancy_collinearity`, `enforcement: advisory`, **never**
`target_leakage`. Any future fixture/example that mislabels it as leakage is
a bug in that fixture, not a legitimate alternative reading of the evidence.

## 7. Units + evidence

`UnitConstraint { value, evidence, confidence? }`. `evidence` is **always**
required, non-empty — including for the honest `"currency_unspecified"`
state (§2 above). `confidence` (`"high" | "medium" | "low"`) is optional and
describes how strong the evidence is, not whether it exists.

## 8. Business ranges + justification

`BusinessRangeConstraint { min?, max?, justification }`. `justification` is
always required and non-empty; at least one of `min`/`max` must be given (an
empty range constrains nothing — use `business_range: null` instead of an
all-`None` object). Neither bound is ever derived from `observed.min` /
`observed.max` — see §2.

## 9. Closed domains

`ClosedDomainConstraint { values, justification, severity }`. Enforceable
only when a column *deliberately* declares closure (§Phase 3 rule #5) — an
undeclared domain (`closed_domain: null`) means a brand-new category value
shows up as a **Phase 4 WARN**, not an ERROR; a declared one defaults to
`severity: ERROR`, meaning a new value signals the product catalogue itself
changed underneath the model (§E.2's `contract_type` example).

## 10. Scale-drift declarations

`ScaleDriftConstraint { median_rel_tolerance, justification, severity }`.
Declared in full by the semantic layer (`ContractDraft`), exactly like every
other constraint — **not** derived from a bare boolean flag the builder
would then have to expand using a project-wide default, which would smuggle
a judgement call into "measured" code. `scale_drift` is explicitly **a
change detector, not a business rule** (§E.3, §Phase 3 rule #6): it declares
*how much the observed median may move, relative to this contract's own
snapshot*, before a Phase 4 gate run (`contract/validator.py`, not built in
this phase) would flag `SUSPECTED SCALE CHANGE`. This document does not
implement that runtime comparison — only the declaration it will read.

## 11. Integrity / SHA256

`Integrity { clean_data_sha256, row_count, column_count, column_order }`.
Every field here is computed by `contract/builder.py` directly from the
exact CSV bytes on disk (`hashlib.sha256` over the raw file, `pandas` for
shape/columns) — never from a DataFrame re-serialization, never supplied by
an agent. `clean_data_sha256` must be a 64-character hex digest;
`column_count` must equal `len(column_order)`; `column_order` may not
contain duplicates. Same bytes in → same hash out, proven directly in
`tests/unit/test_contract_builder.py` (`test_sha256_is_stable_across_repeated_builds`,
`test_identical_bytes_in_a_different_file_produce_the_same_hash`,
`test_sha256_changes_when_the_bytes_change`).

## 12. Assumptions

A plain `list[str]` of narrative statements the Contract Architect wants on
record (§E.2 example: "one row per customer," "churn refers to the
observation month; no future information is encoded"). Free text,
deliberately — this is documentation for a human reader, not something
Python enforces.

## 13. Builder responsibility — what only Python is allowed to measure

`contract/builder.py` (`build_contract(draft, csv_path, ...)`):

- SHA256 of the exact file bytes.
- Row count, column count, column order — from the real, loaded DataFrame.
- Per-column `observed`: dtype (as pandas loaded it), null count, unique
  count, and for numeric columns min/max/mean/median/p05/p95/std/
  decimal-places, or for lower-cardinality categorical columns a value
  distribution (columns with more than 50 distinct values simply get
  `value_distribution: null` — recording per-value shares for a
  near-identifier column adds noise, not signal; a fixed, documented
  threshold, not a per-dataset judgement call).
- Target `observed`: positive rate and class counts.
- **Cross-checks only Python can make**, because only Python read the file:
  every CSV column (other than the target) must have a matching declaration
  in the draft, and vice versa — a mismatch raises `ContractBuildError`
  (never silently drops or invents a column), and the target column
  declared in the draft must actually exist in the CSV.

**What the builder never does:** invent, upgrade, or infer a `constraints.*`
field from anything it measured. Every `ColumnContract.constraints` and
`TargetContract.constraints` in the output is copied, field-for-field,
unchanged, from the validated `ContractDraft` — see
`_carry_column_constraints` in `contract/builder.py`, which contains no
branch that reacts to an observed value.

## 14. `ContractDraft` responsibility — what only an agent (or a human) may decide

`plans/contract_draft.py` (`ContractDraft`, and eventually the Data Contract
Architect agent producing one, per PROJECT_PLAN.md §D.3 — not built in this
phase): every field that requires *judgement* — is this column monetary or
just numeric? Is its domain really closed, or could it grow? Is there a
defensible business floor/ceiling, and why? Is this the entity's primary
key? Should this feature be excluded, and under which of the five
`exclusion_type`s? What should the model be built to predict, and what
counts as a violation of that target's own shape?

**Structurally forbidden** in `ContractDraft` (enforced by
`model_config = ConfigDict(extra="forbid")` on every model in the module,
not merely "discouraged"): `min`, `max`, `median`, `row_count`, `sha256`, or
any other measured value. There is no field to put one in, and no way to
smuggle one in as an unrecognized extra key — pydantic rejects it
(`test_contract_draft_has_no_measurement_fields_to_override_with`,
`test_column_constraints_rejects_a_measured_looking_extra_field`).

Deliberately **excluded** from `ContractDraft` even though they appear in
the final `DatasetContract`: `dataset_name`, `source_documentation_url`,
`contract_version`, `created_at`, `created_by`, `run_id`. These are
deterministic facts the builder already knows without any LLM judgement
(§E.1 rule 5, "מדיד מעל מוצהר") — giving the draft a chance to declare (and
possibly disagree with) them would only create a spurious authority
conflict with no upside.

### The guardrail

`plans/contract_draft.validate_contract_draft(output) -> Tuple[bool, Any]`
is the Phase 3 guardrail — no CrewAI `Agent`/`Task`/`Crew` exists yet
(that's Phase 6), but this function is written to become a real
`Task(guardrail=...)` unchanged. It:

- Duck-types its input: a CrewAI `TaskOutput`-shaped object (anything with
  `.raw`), a raw JSON `str`/`bytes`, a plain `dict`, or an already-built
  `ContractDraft`.
- **Owns the parse** (`ContractDraft.model_validate_json` /
  `model_validate`) rather than assuming `output.pydantic` is already
  populated — the proven CrewAI 1.15.20 behaviour
  (`docs/architecture.md` §6) is that structural parsing happens
  **after** the guardrail on the first pass, so a guardrail that doesn't
  parse `output.raw` itself would approve garbage and let a bare
  `pydantic.ValidationError` escape later, uncaught.
- **Never raises.** Every failure — malformed JSON, a missing field, an
  empty justification, an invalid `exclusion_type`, an unresolved
  `required_features` reference, an attempted measured-field injection —
  surfaces as `(False, <message>)`, because `ContractDraft`'s own
  field/model validators already enforce every one of those rules; catching
  `pydantic.ValidationError` in one place is a complete check, not a partial
  one needing a second, divergent copy of the same logic.
- Returns `(True, ContractDraft)` on success.

A previously undocumented CrewAI 1.15.20 requirement, found wiring this
guardrail into a real `Task` in this phase: the return annotation must be
written *exactly* `Tuple[bool, Any]` (`from typing import Any, Tuple`), not
the modern `tuple[bool, Any]` — see `docs/architecture.md`'s Phase 3
addendum for the reproduction and the exact error.

## 15. What Phase 3 explicitly does NOT do

- **Does not validate a candidate dataset against a contract.** No PASS/FAIL,
  no `ValidationFinding`/`ValidationReport`, no scale-drift *runtime
  comparison* (§E.3's formula is documented here as the policy this contract
  carries, not executed). That is `contract/validator.py`, Phase 4.
- **Does not create any `Agent`/`Task`/`Crew`/`Flow`.** The guardrail above
  is plain, framework-free Python, ready to be wired into a `Task` once
  Phase 6 exists.
- **Does not read or write `artifacts/crew1/clean_data.csv`.** That file
  does not exist yet (Phase 5+ deterministic cleaning, Phase 6+ Crew 1).
  Every test in this phase reads a clearly-labeled fixture instead
  (`tests/fixtures/telco_contract_fixture.csv` — see
  `tests/fixtures/README.md`).

## 16. Examples

- `tests/fixtures/telco_contract_fixture.csv` — a 30-row, 21-column synthetic
  CSV, shaped like a plausible *cleaned* Telco handoff (canonical column
  names from `data/README.md` §6.5), used only to give the builder real
  bytes to hash and measure.
- `tests/fixtures/build_example_contract.py` — hand-written `ContractDraft`
  covering all 20 non-target columns + the target, playing the role a real
  Data Contract Architect agent output will play in Phase 6+. Regenerate its
  output with `python tests/fixtures/build_example_contract.py`.
- `tests/fixtures/contract_example.json` — the resulting `DatasetContract`,
  committed for reference. Validates against `DatasetContract` as-is; not a
  production artifact (see `tests/fixtures/README.md`).

## 17. Anti-patterns — a short, explicit list

1. **Observed → constraint auto-promotion.** `business_range.max =
   observed.max` (or any constraint field set from any `observed.*` value)
   without an independent, human/agent-authored justification. See §2.
2. **Inferring a unit/currency from context.** "It's California, so it must
   be USD." Evidence must be about the *column*, from the *source
   documentation* — not about the setting. See §2, `data/README.md` §6.2.
3. **Calling correlation "leakage."** `redundancy_collinearity` and
   `target_leakage` are different claims; only genuine temporal/semantic
   evidence justifies the latter. See §6.
4. **Silently dropping an undeclared column.** The builder raises
   `ContractBuildError` on any coverage mismatch between the draft and the
   real CSV — it never proceeds with a partial contract.
5. **Letting `scale_drift` become a de-facto range check.** It declares a
   *drift tolerance on the median relative to this contract's own
   snapshot*, not a hard floor/ceiling on individual values — that is what
   `business_range` is for, and the two are independent, separately
   justified constraints.
