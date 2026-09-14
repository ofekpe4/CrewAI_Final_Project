# Validation-gate tolerance calibration (Phase 4 close-out)

Resolves PROJECT_PLAN.md §V.2 **N5** ("טולרנס דריפט | Phase 4 | 0.25 — לכייל
מול נתונים") and the related risk row **§U7** ("טולרנס דריפט רחב מדי →
מפספסים את התקרית ... טולרנס 0.25 מכויל מול נתונים אמיתיים בשלב 4"). Both
name two `config/settings.yaml` values as **provisional until calibrated
against real data in Phase 4**:

- `validation.scale_drift_median_rel_tolerance: 0.25`
- `validation.target_positive_rate_tolerance_abs: 0.05`

This document is that calibration. It replaces "provisional" with
"calibrated" for both — see **Decision** below.

## 1. Where these two numbers actually live, and where they don't

**`config/settings.yaml`'s `validation:` block is consumed by zero code
today.** Verified directly:

```bash
grep -rn "settings.yaml\|SETTINGS_YAML\|load_settings\|scale_drift_median_rel_tolerance\|target_positive_rate_tolerance_abs" src tests
# → only io_paths.py's SETTINGS_YAML path constant and its own test.
# config/llm.py reads only the `llm:` block. Nothing reads `validation:`.
```

**The actual, sole, enforced source of tolerance policy is each
`DatasetContract` instance**, read only by `contract/validator.py`:

- `column.constraints.scale_drift.median_rel_tolerance` (per column, only
  where declared — §E.2, §Phase 4 "NO AUTOMATIC ENFORCEMENT")
- `target.drift.positive_rate_tolerance_abs` (only where `target.drift` is
  declared)

`tests/fixtures/build_example_contract.py` already declares
`monthly_charges.scale_drift.median_rel_tolerance = 0.25` by hand (matching
`settings.yaml`'s value, coincidentally — the two are not wired together in
code) and `tests/fixtures/gate_fixtures.py`'s `build_contract_json(...,
with_target_drift=True)` declares `positive_rate_tolerance_abs = 0.05`.

**`config/settings.yaml`'s role, going forward (Phase 6+):** a documented,
evidence-backed **suggested default** for the Data Contract Architect agent
to start from when it drafts a `ContractDraft`'s `scale_drift`/`drift`
constraints — never a runtime fallback `contract/validator.py` itself
reads. The agent (like every other constraint) still owns writing its own
`justification` and may choose a different tolerance per column if the
evidence for that specific column warrants one; `settings.yaml` gives it a
calibrated starting point, not an enforced ceiling. This keeps exactly one
authoritative, enforced source of policy — the contract — with no second,
competing source at validation time.

## 2. Why "real monthly drift" can't be measured directly

This project has no recurring real-world data feed to calibrate against —
Phase 2 downloaded `data/raw/telco_customer_churn.csv` (7,043 rows) **once**.
There is no second, later, real snapshot of the same population to compare
against. Inventing a "typical month-over-month drift" number without that
evidence would be exactly the fabricated statistical justification this task
explicitly rules out.

What the real data **can** honestly support: bootstrap resampling of the
actual 7,043-row dataset to measure how much apparent "drift" **pure
sampling noise alone** produces — an empirical, evidence-based upper bound
on what a legitimate (non-incident) re-validation could plausibly look
like, against which the chosen tolerances can be judged without fabricating
a claim the data doesn't support.

## 3. Method

`scripts/calibrate_validation_tolerances.py` (deterministic,
`numpy.random.default_rng(42)`, matching the seed already pinned in
`settings.yaml`'s `seeds.numpy`): for each of several batch sizes, draw
3,000 bootstrap samples of `MonthlyCharges`/`Churn` from the real dataset
and measure each sample's deviation from the true population
median/positive-rate. Run with:

```bash
python scripts/calibrate_validation_tolerances.py
```

**The realistic operating scale for this project is `batch_n = 7043`** —
Crew 1 always processes the full downloaded dataset; there is no
monthly-subset architecture here. Smaller batch sizes are included only to
show how the noise floor behaves at scales this pipeline does not actually
operate at.

## 4. Results (real Telco Customer Churn data, `n_iter=3000`, seed 42)

Population: `median(MonthlyCharges) = 70.35`, `churn_rate = 0.2654`.

**Median relative deviation from pure sampling noise (`MonthlyCharges`):**

| batch_n | p50 | p95 | p99 | max |
|---:|---:|---:|---:|---:|
| 100  | 3.945% | 14.110% | 20.186% | 27.754% |
| 300  | 1.386% | 6.930%  | 9.631%  | 15.707% |
| 700  | 0.746% | 5.119%  | 6.219%  | 12.154% |
| 1500 | 0.462% | 2.488%  | 4.513%  | 5.757%  |
| 3500 | 0.249% | 0.746%  | 1.102%  | 3.980%  |
| **7043 (realistic)** | **0.213%** | **0.711%** | **0.995%** | **1.990%** |

**Positive-rate absolute deviation from pure sampling noise (`Churn`):**

| batch_n | p50 | p95 | p99 | max |
|---:|---:|---:|---:|---:|
| 100  | 2.537pp | 8.537pp  | 10.537pp | 15.463pp |
| 300  | 1.796pp | 4.870pp  | 6.204pp  | 9.204pp  |
| 700  | 1.108pp | 3.108pp  | 4.177pp  | 5.892pp  |
| 1500 | 0.670pp | 2.004pp  | 2.537pp  | 3.996pp  |
| 3500 | 0.349pp | 1.051pp  | 1.377pp  | 1.823pp  |
| **7043 (realistic)** | **0.369pp** | **1.022pp** | **1.321pp** | **2.116pp** |

**Incident-scale deviations, for contrast (deliberate corruption, not sampling noise):**

| factor | median deviation |
|---:|---:|
| ×2   | 100.0%  |
| ×3   | 200.0%  |
| ×10  | 900.0%  |
| ×100 | 9,900.0% |

## 5. Decision

Both values **remain 0.25 / 0.05** — now **calibrated**, not provisional:

- **`scale_drift_median_rel_tolerance = 0.25`**: at the realistic
  full-population re-validation scale, pure sampling noise never exceeded
  **1.99%** across 3,000 bootstrap draws — **0.25 sits ~12.5× above the
  observed noise ceiling**, so it will not false-positive on a legitimate
  re-run of the same pipeline, while remaining **enormously** smaller than
  any real incident: even a mild ×2 error (100% deviation) is 400× the
  tolerance; the mandatory ×100 incident is nearly 40,000× it. Not brittle
  (small realistic perturbations pass comfortably), not so wide it would
  miss a real incident (§U7's stated risk).
- **`target_positive_rate_tolerance_abs = 0.05`**: at realistic scale,
  sampling noise never exceeded **2.12 percentage points** — 0.05 (5pp)
  sits **~2.4× above** that ceiling, a real but not excessive margin,
  consistent with churn base-rate drift being a more sensitive signal than
  a monetary column's scale (§E.2: "a large shift in base rate implies the
  label's meaning changed").
- **Not optimized to the 30-row synthetic fixture** — every number above
  comes from the real 7,043-row `data/raw/telco_customer_churn.csv`, per
  this task's explicit instruction. The synthetic fixture
  (`tests/fixtures/telco_contract_fixture.csv`) is used only by
  `test_validator_scale_drift.py`'s functional tests (does the gate compute
  the ratio correctly at all), never for calibrating what the tolerance
  *should be*.
- **`config/settings.yaml` status changes from "Provisional defaults;
  calibrated against real data in Phase 4" to "Calibrated defaults for
  future `ContractDraft` authoring (Phase 6+) — see
  `docs/validation_calibration.md`. NOT read by `contract/validator.py` at
  validation time; the sole enforced source is each `DatasetContract`'s own
  declared `scale_drift`/`drift` constraints."**

## 6. Verification these decisions don't disturb proven Phase 4 behaviour

- Normal baseline (`tests/fixtures/telco_contract_fixture.csv` against
  `contract_example.json`, `scale_drift.median_rel_tolerance = 0.25`
  unchanged): still passes — `test_normal_baseline_passes_with_no_scale_drift_finding`.
- A realistic, non-incident perturbation (+10% on `monthly_charges`, well
  under the empirical noise-to-tolerance margin above) still passes —
  `test_ordinary_in_tolerance_drift_passes`.
- The mandatory ×100 scale change still fails decisively with `"SUSPECTED
  SCALE CHANGE"` — `test_detects_hundredfold_scale_change`. No tolerance
  value changed, so this was never at risk; re-verified after this
  document's changes as part of the full Phase 4 regression sweep.
