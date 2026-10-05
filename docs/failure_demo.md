# Failure demonstration — defense script (Phase 10)

**Purpose of this document:** the exact 90-second sequence for presenting
the Validation Gate's blocking behavior, plus the reasoning behind it. See
`PROJECT_PLAN.md` §P for the full strategy this script implements, and
`tests/failure/` for the automated, zero-LLM-call proof of every claim
made here.

---

## The 90-second sequence

### Step 1 — SUCCESS (`make run`)

```bash
make run
```

**What the presenter says:** "A normal run: Crew 1 analyzes the raw Telco
customer-churn data and produces four artifacts — the cleaned CSV, its
Dataset Contract, an EDA report, and a business-insights document. The
deterministic Validation Gate checks the handoff against the contract.
Zero errors, so Crew 2 starts, trains several model variants, and the best
one is selected — by Python argmax, never by the LLM's own opinion."

**What the audience should notice:**
- Crew 1: 4 artifacts written.
- Gate: **PASS**, 0 validation errors.
- Crew 2: 4 artifacts written.
- A best model name + metric printed — **whatever the real run actually
  produces**, not a hardcoded example from an earlier draft of this
  document. (The last live Phase 8 acceptance run selected `Logistic
  Regression Base`, `roc_auc = 0.8478` — a fact about that run, not a
  promise about the next one.)

**Expected PASS output (shape):**
```
status            : completed
validation_passed : True (0 error(s), 0 warning(s))
crew2_started     : True
crew2_completed   : True
best_model        : <whatever this run's real winner is>
roc_auc           : <whatever this run's real metric is>
```

### Step 2 — FAILURE (`make demo-fail`)

```bash
make demo-fail
# == python scripts/run_pipeline.py --inject-failure scale_change
```

**What the presenter says:** "Now we reproduce the actual Harbor & Vale
incident: `MonthlyCharges` gets multiplied by 100 — the exact signature of
a currency/unit conversion bug — strictly *after* Crew 1 finishes and
*before* the gate ever runs. The file still loads. The dtype is still
`float64`. Nothing about the file looks broken. That's exactly what let the
original incident slip past basic checks for five weeks."

**What the audience should notice:**
- A `CRITICAL FAULT INJECTION ACTIVE` log line.
- `monthly_charges`/`MonthlyCharges` multiplied by ×100; dtype unchanged.
- Gate: **FAILED** — not 0 errors.
- The message contains the literal phrase **`SUSPECTED SCALE CHANGE`** and
  quantifies it as **`≈100×`** the contract snapshot.
- An **integrity mismatch** is reported too (the file's bytes no longer
  match the hash the contract recorded).
- `crew2_started` is **False** — the Data Scientist Crew was never started.

**Expected FAIL output (shape):**
```
status            : halted_validation
validation_passed : False (2-3 error(s), 0 warning(s))
crew2_started     : False
```
```
[ERROR] scale_drift · check_id: SCALE_DRIFT_MEDIAN · column: MonthlyCharges
  SUSPECTED SCALE CHANGE: the observed median is ≈100× the value recorded
  in the contract snapshot (observed ~7035 vs. contracted ~70.35). The
  contract declares unit='currency_unspecified' ... A change of exactly
  this magnitude is characteristic of a unit or scale conversion.

[ERROR] integrity · check_id: INTEGRITY_SHA256_MATCH
  the candidate CSV's bytes do not match the contract's
  integrity.clean_data_sha256 — the file has changed since the contract
  was written.
```

### Step 3 — EXPLAIN WHY

**What the presenter says, verbatim (§P.3):**

> "The original Harbor & Vale incident passed every technical validation
> that existed. The file loaded. The types were correct. There were no
> nulls. Schema checks alone miss this *by definition* — a scale change
> doesn't break the schema. So our contract also records a distributional
> snapshot, and keeps a strict separation between what was *measured*
> (`observed`) and what is *enforced* (`constraints`, each with a
> justification). We are not claiming to know the original data was in
> cents — the contract's own `unit` field says `currency_unspecified`,
> and that's the honest, undocumented truth about the real Telco dataset.
> What we ARE claiming is that the scale shifted by a factor of
> approximately 100 relative to what was agreed, and that specific
> magnitude is the signature of a unit-conversion bug. That's the
> difference between 'the file is different' and an actionable diagnosis
> — without inventing metadata nobody actually recorded."

**Why this proves the architecture:** the gate's PASS/FAIL decision is
100% deterministic Python (`harbor_vale.contract.validator`) — zero LLM
involvement, proven in code and in `tests/failure/`. `run_scientist_crew`
is wired with `@listen("gate_passed")`, a route label only the gate's own
router can emit — Crew 2 is not merely skipped by an `if`, it is
structurally absent from the call graph on any failing run.

---

## Commands reference

| Command | Cost | What it proves |
|---|---|---|
| `make run` | 1 live OpenAI run | the full successful path |
| `make demo-fail` | 1 live OpenAI run (Crew 1 only; fault injection + gate are local) | the live, end-to-end incident reproduction |
| `python scripts/run_pipeline.py --replay-plans --inject-failure scale_change` | **zero LLM calls** | the identical fault-injection → gate → block path, replayed from stored plans |
| `python scripts/run_pipeline.py --validate-only` | zero LLM calls | "someone edited the file upstream" — the gate runs against whatever is already on disk, and never overwrites it |
| `python tests/failure/test_scale_change.py` (or any `tests/failure/test_*.py`) | **zero LLM calls** | the mandatory scenario, fully mocked Crew 1/Crew 2, asserted mechanically |

`make demo-fail` still invokes a real, live Crew 1 (fault injection happens
strictly *after* Crew 1 completes, per §P.1) — it is not free. The
`--replay-plans --inject-failure scale_change` combination proves the
identical fault-injection → gate → block code path with **zero** LLM
calls, by replaying Crew 1's already-stored, guardrail-accepted plans
instead of calling the LLM again. Prefer it for repeated rehearsal; reserve
a live `make demo-fail` for the actual presentation.

**No `--restore` step exists anywhere in this sequence**, by design: fault
injection mutates only a run-scoped snapshot copy (`runs/<run_id>/handoff/`)
of Crew 1's final artifacts — never `artifacts/crew1/*` itself. The next
`make run` is clean with no cleanup step. See `tests/failure/
test_default_run_isolation.py` for the mechanical proof (byte-for-byte hash
comparison of the real committed handoff, before and after a fault-injected
run).

## `--validate-only` demo sequence (the second mechanism, §P.1)

```bash
make run                                               # 1 — a successful run
# edit artifacts/crew1/clean_data.csv by hand           # 2 — "the analysts updated it"
python scripts/run_pipeline.py --validate-only          # 3 — the gate catches the edit
```

This is the scenario the *first* demo mechanism cannot cover: a change made
to the handoff *between* pipeline runs, by someone other than Crew 1. Both
crews are skipped entirely; the gate runs against exactly what is on disk
and never overwrites it, so the edit is still there to inspect afterward.

## Full failure-scenario catalog

Ten scenarios are wired and asserted in `tests/failure/` (PROJECT_PLAN.md
§O.3). Every BLOCKING one proves: `passed is False`, the expected check
family is present, `crew2_started is False`, and the real Crew 2 mock's
call count is `0`. The one WARN-only scenario proves the opposite — the
gate does not block every contract edit.

| Scenario | Test file | Family | Blocking? |
|---|---|---|---|
| `scale_change` ⭐ mandatory | `test_scale_change.py` | `scale_drift` + `integrity` | **Yes** |
| `rename_column` | `test_rename_column.py` | `schema` | Yes |
| `drop_required_column` | `test_drop_required_column.py` | `schema` | Yes |
| `change_dtype` | `test_change_dtype.py` | `schema` | Yes |
| `inject_nulls` | `test_inject_nulls.py` | `constraints` | Yes |
| `unknown_category` (closed domain declared) | `test_unknown_category.py` | `constraints` | Yes |
| `unknown_category` (no closed domain declared) | `test_unknown_category.py` | — (no finding for this check) | blocked only by the unrelated, always-fires integrity hash check |
| `flip_target_encoding` | `test_flip_target_encoding.py` | `target` | Yes |
| `truncate_dataset` | `test_truncate_dataset.py` | `modeling` + `integrity` | Yes |
| `corrupt_contract_json` | `test_corrupt_contract_json.py` | `artifacts` (prerequisite gating — no other family runs) | Yes |
| `contract_only_change` | `test_contract_only_change.py` | `schema` | **No — WARN only, Crew 2 continues** |

Two supporting files are not per-scenario but prove cross-cutting
guarantees: `test_default_run_isolation.py` (Internal Gate 10.2) and
`test_validate_only_demo.py` (Internal Gate 10.4).

## Screenshot evidence

See the repo's evidence checklist (README "Failure Demonstration" section)
for exactly which five screenshots to capture and from where. Capturing
them is a manual, one-time action against a real `streamlit run` — this
project deliberately does not add browser automation (Playwright/Selenium)
solely to take screenshots.
