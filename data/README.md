# Dataset — Telco Customer Churn (Phase 2)

> Scope of this document: PROJECT_PLAN.md §J (dataset selection strategy) and
> §T Phase 2 (Internal Gates 2A–2D). Selection is evidence-based against the
> Plan's 12 mandatory criteria (§J.1). This file is the single source of
> truth for provenance, units, and quality issues for this dataset — later
> phases (contract schema, cleaning, feature engineering) must not restate or
> silently reinterpret these facts.

## 1. Selected dataset

**Telco Customer Churn** (the classic 7,043×21 IBM sample dataset). Selected
per PROJECT_PLAN.md §J.2's preferred candidate; it satisfies all 12 mandatory
criteria on real, verified evidence (§4 below) — no criterion was weakened
and no alternative candidate was required.

## 2. Why it was selected

- Matches the Harbor & Vale narrative exactly: a retention/churn story for a
  services business, with a scale-sensitive monetary-like column
  (`MonthlyCharges`) and a genuinely messy derived column (`TotalCharges`) —
  the same shape of problem the project's validation gate is designed to
  catch.
- All three demographic/account "no service" quality issues below are **real
  and observed**, not manufactured for the exercise (§J.1 criterion 3
  explicitly forbids inventing issues).
- Small, single-entity-per-row, no aggregation needed (criterion 10).
- Reproducible without an API key or authentication (criterion 9) — see §5.

## 3. Provenance

| Fact | Value | Evidence |
|---|---|---|
| Original publisher | IBM — "Telco Customer Churn" sample data, distributed via IBM Watson Analytics / IBM Cognos Analytics sample-data catalogue | [IBM Cognos Analytics docs](https://www.ibm.com/docs/en/cognos-analytics/11.1.x?topic=samples-telco-customer-churn); [IBM Community blog, Steven Macko, 2019-07-11](https://community.ibm.com/community/user/businessanalytics/blogs/steven-macko/2019/07/11/telco-customer-churn-1113) |
| Described population | A fictional telco company providing home phone and Internet services to 7,043 customers in California, "in Q3" | IBM Community blog (above) |
| Secondary catalogue confirming provenance + license | Mendeley Data: "a globally recognized, real-world customer churn benchmark originally provided by IBM Sample Data Sets" | https://data.mendeley.com/datasets/phsxg9ssrf/1 (license listed there: CC BY 4.0) |
| Widely-mirrored community copy (NOT used as the acquisition source — license on that specific listing is unclear: "Data files © Original Authors · Not specified") | Kaggle, user `blastchar` | https://www.kaggle.com/datasets/blastchar/telco-customer-churn |
| **Acquisition source actually used by this project** | IBM's own GitHub organisation repository `IBM/telco-customer-churn-on-icp4d`, file `data/Telco-Customer-Churn.csv` | https://github.com/IBM/telco-customer-churn-on-icp4d |
| License of the acquisition source | **Apache License 2.0** (repository-level `LICENSE` file) — permissive, usable | Confirmed via GitHub API: `GET /repos/IBM/telco-customer-churn-on-icp4d/license` → `{"key": "apache-2.0", ...}` |
| Is the acquisition source official or a mirror? | **Official** — it is IBM's own GitHub organisation account, not a third-party mirror. It is a re-publication of the same IBM sample data by IBM itself, in a form that is scriptable and does not require a Kaggle account/API key. |

We deliberately did **not** use Kaggle as the acquisition source: Kaggle
requires an authenticated API key for scripted downloads (violating the
Plan's "not require an API key if a stable public source exists"), and the
most common Kaggle listing (`blastchar`) states its own license as "Not
specified." The IBM GitHub repository provides the identical data under an
explicit, permissive license, with no authentication required.

## 4. The 12 mandatory criteria — evidence table (PROJECT_PLAN.md §J.1)

| # | Criterion | Verdict | Evidence (measured from the actual downloaded file unless noted) |
|---|---|:---:|---|
| 1 | Size: 3K–100K rows, < 50MB | **PASS** | 7,043 rows; file size 970,457 bytes (~0.93 MB) |
| 2 | Columns: 10–30 | **PASS** | 21 columns |
| 3 | ≥3 real data-quality issues | **PASS** | 3 genuine issues found and measured — see §7 |
| 4 | ≥1 scale-sensitive column | **PASS** | `MonthlyCharges` — continuous, undocumented unit (§6.2) |
| 5 | ≥1 categorical column with a defensibly closed domain | **PASS** | `Contract` ∈ {Month-to-month, One year, Two year} — a fixed, business-defined set of plan tiers; also `PaymentMethod` (4 values), `InternetService` (3 values) |
| 6 | Binary target, 10%–40% positive | **PASS** | `Churn`: Yes = 1,869 / 7,043 = **26.54%** |
| 7 | ≥5 non-trivial predictive features | **PASS** | ≥12 plausible: `Contract`, `tenure`, `InternetService`, `TechSupport`, `OnlineSecurity`, `OnlineBackup`, `DeviceProtection`, `PaymentMethod`, `PaperlessBilling`, `SeniorCitizen`, `Dependents`, `Partner`, `StreamingTV`, `StreamingMovies`, `MultipleLines` |
| 8 | Business context understandable in ~30s | **PASS** | "Will this telecom customer cancel their subscription?" — immediately legible |
| 9 | Permissive license + stable reproducible acquisition | **PASS** | Apache-2.0 source repo; commit-pinned immutable URL, no API key (§5) |
| 10 | One row = one entity; no complex aggregation | **PASS** | One row per `customerID` (7,043 unique values, 0 duplicates) |
| 11 | Reliable source documentation for the scale-sensitive column's unit/currency | **PASS (via the neutral-fallback path the criterion itself defines)** | No authoritative source documents a currency for `MonthlyCharges`. This is stated explicitly, not glossed over — see §6.2. Per the criterion's own instruction, we use the neutral name `monthly_charges` with `unit: currency_unspecified` rather than inventing a currency. |
| 12 | Determinable when each column is measured relative to the target | **PASS** | IBM Community documentation states `Churn` = departed "this quarter", `tenure` = months with the company "by the end of the quarter", `TotalCharges` = "calculated to the end of the quarter" — i.e. every one of these is a snapshot at the **same** observation point. This directly supports the `TotalCharges` classification in §6.3. |

**Result: 12/12 PASS on real evidence. No alternative candidate (Bank
Customer Churn / E-Commerce Shipping / Online Retail II, per §J.2) was
required.**

## 5. Reproducible acquisition

- Script: `scripts/download_data.py`
- Source URL (**immutable — pinned to a commit, not a branch**):
  `https://raw.githubusercontent.com/IBM/telco-customer-churn-on-icp4d/1fd6fd70906479be1712e64cfc0ea89f58466629/data/Telco-Customer-Churn.csv`
  - Commit `1fd6fd7` is the **only** commit that has ever touched
    `data/Telco-Customer-Churn.csv` in that repository (verified via the
    GitHub commits API on 2026-09-14: `GET /repos/IBM/telco-customer-churn-on-icp4d/commits?path=data/Telco-Customer-Churn.csv`
    returns exactly one commit, dated 2019-09-30, message "Add data set.").
    The file has never been edited since it was added, so pinning to this
    commit SHA is expected to remain stable indefinitely.
  - GitHub does not offer a content-addressed URL, so this pinned-commit URL
    is the closest available approximation to an immutable reference. The
    **SHA256 check below is the real integrity lock** and is verified on
    every run of the script — this limitation (no cryptographic URL) is
    intentionally compensated for, per PROJECT_PLAN.md §Phase 2.
- Destination (canonical raw-data path, from `harbor_vale.io_paths.RAW_TELCO_CHURN_CSV`):
  `data/raw/telco_customer_churn.csv` — deterministic filename, git-ignored
  (`data/raw/*` except `.gitkeep`).
- Expected SHA256 (verified against the actual downloaded bytes on
  2026-09-14): `16320c9c1ec72448db59aa0a26a0b95401046bef5d02fd3aeb906448e3055e91`
- Behaviour: idempotent (skips the network call if a hash-valid copy is
  already on disk); fails loudly with a non-zero exit code on any network
  error, non-200 HTTP status, or SHA256 mismatch; never writes bytes it has
  not verified (a mismatched download is deleted, not kept); no credentials
  or API key required; no machine-specific absolute paths (all paths derive
  from `harbor_vale.io_paths`).

Reproduce with:
```bash
python scripts/download_data.py            # normal run — verifies/skips
python scripts/download_data.py --force    # re-download unconditionally
```

## 6. Semantic decisions (evidence-based, per PROJECT_PLAN.md §J.2 required research)

### 6.1 `tenure`

**Decision: rename to `tenure_months` — months are source-confirmed.**

The IBM Community documentation states explicitly: *"Tenure in Months:
Indicates the total amount of months that the customer has been with the
company by the end of the quarter specified above."* This is an explicit,
named unit ("Months") from the dataset's own publisher documentation, not an
inference. Observed range in the actual data: 0–72 (consistent with "months
since signup," well within a plausible multi-year telecom relationship).

- **What the source states:** the unit is months, explicitly named.
- **What the source does not state:** the exact starting/ending calendar
  dates of "the quarter" referenced (a fictional dataset; no real calendar
  anchor is given or needed).
- **Inferred:** nothing beyond the source's own wording was needed here.

### 6.2 `MonthlyCharges`

**Decision: rename to `monthly_charges`; unit = `currency_unspecified`. No
currency is invented.**

- **What the source states:** IBM's documentation describes it only as *"the
  customer's current total monthly charge for all their services from the
  company"* — a continuous billing amount, nothing about currency.
- **What the source does not state:** any currency code or symbol (no USD,
  no cents, nothing). Searched explicitly for this (IBM docs, IBM Community
  blog, Mendeley catalogue, Kaggle listings) — no authoritative source names
  a currency.
- **What can be reasonably inferred but is NOT source-confirmed:** the
  fictional company is described as based "in California," which suggests
  USD is *plausible*. This is explicitly **not** used as a basis for the
  column's unit — PROJECT_PLAN.md §J.1 criterion 11 and §B forbid inventing
  currency metadata from inference. The canonical name and metadata carry no
  currency: `monthly_charges`, `unit: currency_unspecified`.
- **Suitability as the scale-sensitive demonstration column:** yes —
  continuous, undocumented unit, a natural target for the project's
  "SUSPECTED SCALE CHANGE" fault-injection demo (PROJECT_PLAN.md §P), since
  a 100× multiplication would be immediately implausible against the
  contract's `observed` snapshot regardless of what unit is eventually
  assumed.

### 6.3 `TotalCharges`

**Decision: legitimate predictor available at prediction time — redundant /
collinear with `tenure` × `monthly_charges`, but NOT target leakage.**

Evidence and reasoning:

- **Source evidence on timing:** IBM's documentation states `TotalCharges` is
  *"calculated to the end of the quarter specified"* — the **same**
  observation point at which `Churn` itself is determined (*"the customer
  left the company this quarter"*) and at which `tenure` is counted (*"by
  the end of the quarter"*). All three columns are measured at one common
  snapshot instant. Nothing about `TotalCharges` is computed *after* or
  *because of* the churn outcome.
- **Measured relationship:** in the actual data, `TotalCharges` correlates
  with `tenure × MonthlyCharges` at **r = 0.9996** (mean absolute relative
  difference ≈ 3.2%, consistent with mid-tenure plan/add-on changes). This
  confirms it is essentially the customer's accumulated billing history as
  of the snapshot — a legitimate account-level feature, not a
  post-outcome artifact.
- **Why this is not leakage:** leakage requires the feature to encode
  information that would not be available (or would be different) *before*
  the churn event is known — e.g., a cancellation date, a refund, a support
  ticket filed in response to leaving. `TotalCharges` is simply "money billed
  so far," known continuously throughout the customer relationship,
  independent of whether the customer later churns. Correlation with
  `tenure`/`MonthlyCharges` is a multicollinearity concern for modeling, not
  a temporal/semantic leakage concern (per PROJECT_PLAN.md §J.2: "Do NOT
  classify it as leakage merely because it is correlated with tenure or
  monthly charges").
- **Known real quality issue on this column:** see §7.1 — it loads as a
  string, not a number, because of 11 blank-placeholder rows.

### 6.4 `Churn` (target)

**Decision: exact meaning confirmed; positive rate measured.**

- **Meaning:** *"Churn Label: Yes = the customer left the company this
  quarter. No = the customer remained with the company."* (IBM Community
  documentation.)
- **Measured class balance (from the actual downloaded file):**
  - `No` (retained): 5,174 / 7,043 = 73.46%
  - `Yes` (churned): 1,869 / 7,043 = **26.54%** — within the Plan's
    required 10%–40% band.

### 6.5 Proposed canonical-name mapping

This is the **proposed** neutral mapping for the contract-building phase
(Phase 3); it is **documented here, not physically applied** to any file in
Phase 2. The raw CSV in `data/raw/` remains byte-for-byte as downloaded.

| Source column | Proposed canonical name | Note |
|---|---|---|
| `customerID` | `customer_id` | identifier, excluded from modeling |
| `tenure` | `tenure_months` | unit confirmed by source (§6.1) |
| `MonthlyCharges` | `monthly_charges` | unit intentionally left unspecified (§6.2) |
| `TotalCharges` | `total_charges` | same unit-unspecified treatment as `monthly_charges`; requires numeric coercion (§7.1) before use |
| `Churn` | `churn` | target; `Yes`/`No` → boolean/int mapping deferred to Phase 3+ |
| all other columns | `snake_case` of the original name (e.g. `SeniorCitizen` → `senior_citizen`, `PaymentMethod` → `payment_method`) | no semantic change, casing only |

No `_usd` or any other currency suffix is used anywhere, per PROJECT_PLAN.md
§J.2's explicit correction from the project's v1 plan.

## 7. Measured data-quality issues (≥3 required, all observed — none invented)

All figures below are measured directly from `data/raw/telco_customer_churn.csv`
(SHA256 `16320c9c1ec72448db59aa0a26a0b95401046bef5d02fd3aeb906448e3055e91`) using
pandas. **No cleaning was performed** — that is Crew 1 / Phase 5+ work; this
section only documents what is wrong, not how to fix it.

### 7.1 `TotalCharges` — non-numeric due to a blank-string placeholder

- **Affected column:** `TotalCharges`.
- **Measured evidence:** the column loads as `str`/`object` dtype, not
  numeric, because **11 rows** contain a single whitespace character
  (`" "`, not an empty string, not `NaN`) instead of a number. All 11 of
  these rows have `tenure == 0` (brand-new customers with no completed
  billing cycle yet) and `Churn == "No"`.
- **Why it's a data-quality issue:** a naive `pd.read_csv` silently produces
  a string column for what is semantically a continuous monetary field; any
  downstream arithmetic (sums, means, the `tenure × MonthlyCharges`
  cross-check in §6.3) will raise or silently coerce incorrectly unless this
  is explicitly handled.
- **Likely downstream consequence:** if not caught, models/aggregations
  either crash on non-numeric input or (worse) silently treat the blank as
  the string `" "`, which some tooling coerces to `0` and some drops as
  `NaN` — a real correctness risk if the two paths disagree.
- **Not solved here** — this is Crew 1's cleaning work (Phase 5+).

### 7.2 Inconsistent encoding of "not applicable" vs. "no" across service columns

- **Affected columns:** `MultipleLines`, `OnlineSecurity`, `OnlineBackup`,
  `DeviceProtection`, `TechSupport`, `StreamingTV`, `StreamingMovies` (7
  columns).
- **Measured evidence:** each of these columns has **3** categorical values,
  not 2. Besides `"Yes"`/`"No"`, each also contains a third value —
  `"No phone service"` (for `MultipleLines`, gated by `PhoneService == "No"`)
  or `"No internet service"` (for the other six, gated by
  `InternetService == "No"`). E.g. `OnlineSecurity` ∈
  {`No`, `Yes`, `No internet service`}.
- **Why it's a data-quality issue:** this conflates two different concepts
  in one column — "the customer does not have this add-on" (a real `No`)
  and "the customer is structurally ineligible for this add-on because they
  don't have the underlying service" (fully determined by `PhoneService` /
  `InternetService`, not new information). Treating all three values as one
  flat nominal category (e.g. naive one-hot encoding) both loses this
  structure and creates redundant, perfectly-correlated dummy columns.
- **Likely downstream consequence:** inflated/misleading feature importance
  for what is really a restatement of `PhoneService`/`InternetService`;
  naive encoders create collinear dummy columns.
- **Not solved here** — flagged for Crew 1 / Phase 5+ cleaning and Phase 3
  contract design.

### 7.3 Inconsistent representation of binary flags across columns

- **Affected columns:** `SeniorCitizen` vs. `Partner` / `Dependents` /
  `PhoneService` / `PaperlessBilling` (and others).
- **Measured evidence:** `SeniorCitizen` is encoded as **`int64`** with
  values `{0, 1}`, while every other same-shape binary demographic/account
  flag in the same file (`Partner`, `Dependents`, `PhoneService`,
  `PaperlessBilling`) is encoded as **`str`** with values `{"Yes", "No"}`.
  Both encode the identical kind of information (a yes/no flag about the
  customer), but inconsistently.
- **Why it's a data-quality issue:** a schema/type inconsistency for
  semantically identical column *kinds* within the same file — code that
  handles "all the Yes/No columns" generically will silently mishandle
  `SeniorCitizen` (e.g., treating `0`/`1` as a continuous numeric feature,
  or failing a `.isin(["Yes","No"])` check) unless it is special-cased.
- **Likely downstream consequence:** silent miscategorisation of
  `SeniorCitizen` as numeric rather than categorical in any automated
  dtype-based feature-typing step.
- **Not solved here** — flagged for Phase 3 (contract schema) and Phase 5+
  (cleaning).

*(These 3 issues are sufficient to satisfy criterion 3 (§4). No additional
issues were manufactured; the file has no full-row duplicates,
no duplicate `customerID`, and no missing values under pandas' default
null-detection — the only "missing" values are the 11 blank-string
`TotalCharges` cells in §7.1, which pandas does not detect as null because
they are not empty strings.)*

## 8. Scale-sensitive column (criterion 4)

**`MonthlyCharges`** (proposed canonical name `monthly_charges`). Continuous,
range 18.25–118.75 in the observed data, unit intentionally left
unspecified (§6.2). This is the column intended for the project's semantic
scale-change fault-injection demonstration (PROJECT_PLAN.md §P) — a
plausible-looking value shift (e.g. ×100) is very hard to notice by staring
at the CSV but is exactly what a contract-based `observed` snapshot
comparison is designed to catch.

## 9. Closed-domain categorical candidate(s) (criterion 5)

- **`Contract`** — {`Month-to-month`, `One year`, `Two year`}: a small,
  business-defined set of contract tiers offered by the (fictional) telco.
  Adding a 4th tier would be a genuine business/product change, not a data
  artifact — defensible as closed.
- Secondary candidates: `PaymentMethod` (4 fixed payment channels),
  `InternetService` (3 fixed service types: DSL / Fiber optic / No).

## 10. Known assumptions

- The dataset's "customers" and "churn this quarter" framing is treated as a
  single-snapshot cross-section (one row per customer, one observation
  point), consistent with how the source documents it (§6.4, §12 evidence).
- `SeniorCitizen`'s `0`/`1` encoding is assumed to mean the same boolean
  sense as `Yes`/`No` in the other flag columns (`1` = senior), based on the
  column name and its binary domain — this is a naming-based inference, not
  separately source-confirmed, and is noted here rather than silently
  assumed.

## 11. Explicitly UNKNOWN

- **Currency of `MonthlyCharges` / `TotalCharges`.** No authoritative source
  states one. Treated as `currency_unspecified` (§6.2). Do not "fix" this in
  a later phase by assuming USD without new source evidence.
- **Exact real-world date range** the "Q3" snapshot corresponds to (the
  company is fictional; no calendar anchor is given or claimed).
- **Whether `TotalCharges`'s ~3.2% mean deviation from `tenure ×
  MonthlyCharges`** (§6.3) reflects mid-tenure price changes, promotional
  discounts, add-on changes, or rounding — the source does not document
  billing-history mechanics at that level of detail. The deviation is small
  enough not to affect the leakage/redundancy classification either way.

## 12. Reproducibility instructions

```bash
# from the project's .venv (project-local, never Conda base)
source .venv/bin/activate

# 1. acquire the raw dataset (network required only for this step)
python scripts/download_data.py

# 2. verify structure (fast, local, no network) — see tests/unit/test_dataset_ingestion.py
python tests/unit/test_dataset_ingestion.py
# or, once pytest is installed:
pytest tests/unit/test_dataset_ingestion.py
```

`data/raw/telco_customer_churn.csv` is git-ignored; every teammate/reviewer
reproduces it locally via the script above. Its SHA256 must always equal
`16320c9c1ec72448db59aa0a26a0b95401046bef5d02fd3aeb906448e3055e91` — a
different hash means either upstream changed (investigate before trusting)
or the local file was corrupted/hand-edited (re-run the script).
