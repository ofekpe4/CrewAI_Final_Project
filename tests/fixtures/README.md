# Test fixtures

## `telco_contract_fixture.csv`

**A synthetic, hand-generated Phase 3 test fixture — NOT a production artifact.**

- **Is NOT** `artifacts/crew1/clean_data.csv`. No such file exists yet; it is
  a Phase 5+ (deterministic cleaning) / Phase 6+ (Crew 1) deliverable.
- **Is NOT** downloaded, scraped, or derived from the real Telco Customer
  Churn dataset in `data/raw/`. Every value was generated with
  `numpy.random.default_rng(42)` from plausible ranges/domains — it exists
  solely to give `tests/unit/test_contract_builder.py` and
  `tests/unit/test_observed_not_enforced.py` a **real CSV file on disk** to
  hash, load, and measure, so those tests exercise genuine pandas behaviour
  (dtypes, SHA256, row counts, quantiles) rather than mocked data.
- 30 rows, 21 columns, using the **proposed canonical column names** from
  `data/README.md` §6.5 (`tenure_months`, `monthly_charges`, `total_charges`,
  `churn`, snake_case for the rest) — i.e. it represents what a *cleaned*
  Telco handoff would plausibly look like, not the raw file's actual column
  names or dtypes (`churn` here is already `int64` 0/1, `total_charges` is
  already a clean float with no blank-placeholder rows — Phase 2's `data/README.md`
  §7.1 issue is Crew 1's cleaning work, not reproduced here).
- Internally consistent with the real dataset's structural quirks the
  contract needs to be able to represent: `phone_service == "No"` implies
  `multiple_lines == "No phone service"`; `internet_service == "No"` implies
  the six internet-dependent columns read `"No internet service"`.
- Measured churn positive rate: **26.67%** (8/30) — deliberately close to
  Phase 2's real measured 26.54%, but this is an independent synthetic fact
  about the fixture, not a copy of the real dataset's numbers.

If this file is ever regenerated, its SHA256 **will** change — that is
expected and fine; it is a fixture, not an integrity-locked download like
`data/raw/telco_customer_churn.csv`. Tests that check "the SHA256 is stable"
mean *within one file on disk across repeated reads*, not across
regenerations of this fixture.

## `contract_example.json`

An example `DatasetContract`, built by `contract/builder.py` from
`telco_contract_fixture.csv` via a small script
(`tests/fixtures/build_example_contract.py`), committed for documentation and
as a fast fixture for tests that need an already-valid contract without
re-running the builder. It validates against
`harbor_vale.contract.schema.DatasetContract` — see
`docs/contract_spec.md` for the human-readable walkthrough of its shape.
**Also not a production artifact** — the production `dataset_contract.json`
is written to `artifacts/crew1/` only by the real pipeline (Phase 6+).
