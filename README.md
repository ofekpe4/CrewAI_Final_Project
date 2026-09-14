# Harbor & Vale — Industry-Simulated AI Product Workflow

Two CrewAI crews separated by a **machine-enforced dataset contract** and a
**deterministic validation gate**. The interesting part is not the ML — it is the
*seam*: a contract that one crew writes and the other must honour, and a Flow that
checks it before anything downstream is allowed to run.

> **Status: Phases 0–5 complete.**
> The environment and core infrastructure exist and are tested (Phase 0). The
> CrewAI execution-pattern spike is resolved (Phase 1): **Pattern A** — one
> `Crew` of 3 sequential `Task`s per crew, each with `output_pydantic` +
> `guardrail` + deterministic `callback` + explicit `context=`, wrapped by a
> `Flow` that routes on the gate result. See
> [`docs/architecture.md`](docs/architecture.md). The dataset is selected and
> reproducibly acquired (Phase 2). The Dataset Contract schema — `observed` vs.
> `constraints`, never one becoming the other — is built and tested (Phase 3).
> The **deterministic Validation Gate** exists and is fully tested (Phase 4):
> it checks a candidate `clean_data.csv` against a `dataset_contract.json`
> with **zero LLM calls**, and is the sole future PASS/FAIL authority before
> Crew 2 runs. See [`docs/contract_spec.md`](docs/contract_spec.md). **The
> entire deterministic execution + security layer is now built and proven
> end-to-end (Phase 5)**: profiling, a closed-vocabulary cleaning executor,
> deterministic EDA statistics/figures/reporting, an exact-file Crew 1 →
> Crew 2 handoff allowlist, a `ColumnTransformer`-based feature builder, and
> `sklearn`-based train/evaluate/winner-selection — proven together on the
> **real** 7,043-row Telco dataset with hardcoded (not agent-produced) plans,
> **zero LLM calls**, and verified double-run byte-identical reproducibility.
> **The crews, the Flow, and the Streamlit app are *not* implemented yet.**
> See [Project status](#project-status) below.

---

## Why this project exists

The scenario it simulates: analysts changed `order_value` from cents to dollars,
renamed some fields, and dropped a column. A churn model loaded that data,
trained, and served predictions — **without a single error**. Weeks of retention
budget were spent on exactly the wrong customers.

The failure was not technical. It was **semantic**. Schema checks pass this by
construction: `float64` is still `float64`. So the design here records an agreed
*distributional snapshot* of the data in a contract, and checks new data against
it — separating **what was measured** from **what is enforced, with justification**.

The authoritative architecture and plan live in
[`PROJECT_PLAN.md`](PROJECT_PLAN.md). This README is a working entry point, not a
substitute for it.

---

## Architecture at a glance (planned)

```
data/raw/*  ──►  Crew 1 (Data Analyst, 3 agents)  ──►  THE HANDOFF  ──►  Validation Gate  ──►  Crew 2 (Data Scientist, 3 agents)
                 Quality Inspector                     clean_data.csv      deterministic          Feature Engineer
                 EDA & Insights Analyst                dataset_contract.json   Python, never        Modeling Specialist
                 Data Contract Architect               (exactly these 2)       an LLM decision      Responsible AI Documenter
```

- **Agent plans, Python executes.** Agents produce structured plans; Pydantic
  guardrails validate them; deterministic Python performs every precision-critical
  step (cleaning, measurement, validation, model selection).
- **The gate is pure Python.** PASS/FAIL before Crew 2 is a deterministic decision
  with zero LLM involvement.
- **The handoff is exactly two files.** Crew 2 is mechanically blocked from raw
  data and from Crew 1 internals.
- A CrewAI **Flow** orchestrates the whole run and routes on the gate result.

The orchestration pattern (**Pattern A**) and the exact CrewAI `1.15.20` runtime
behaviour it relies on are decided and documented in
[`docs/architecture.md`](docs/architecture.md) (Phase 1 spike). None of the
pipeline itself is built yet — it is the target described in `PROJECT_PLAN.md`
§C–§H.

---

## Requirements

| | |
|---|---|
| **Python** | **3.12.x**, CPython, **not** from Anaconda/Conda. The project is developed on Homebrew Python `3.12.14`; any non-Conda 3.12 works. CrewAI `1.15.20` supports `>=3.10,<3.14`; 3.12 was chosen to reduce install risk. |
| **OS** | Developed on macOS (Apple Silicon). Linux should work; not yet tested. |
| **Anaconda / Conda** | **Not used and not required.** Do not install this project's dependencies into a Conda `base` or global environment, even if your shell shows `(base)`. |
| **LLM API key** | **Not needed for Phase 0–5.** Crew execution (Phase 6+) will need an `OPENAI_API_KEY`; see [Configuration](#configuration). |

---

## Setup (Anaconda-free)

From a clean clone, in the project root:

```bash
# 1. Create a project-local virtual environment with a non-Conda Python 3.12
python3.12 -m venv .venv

# 2. Activate it  (bash/zsh)
source .venv/bin/activate
#    fish:            source .venv/bin/activate.fish
#    Windows PowerShell:  .venv\Scripts\Activate.ps1

# 3. Confirm the interpreter is the project venv, not Conda
python --version                 # -> Python 3.12.x
python -c "import sys; print(sys.prefix)"       # -> .../CrewAI_Final_Project/.venv
python -c "import sys; print(sys.base_prefix)"  # -> a non-Conda Python 3.12

# 4. Install the pinned dependencies
python -m pip install -r requirements.txt
```

If `python3.12` is not on your `PATH`, install a non-Conda build first — e.g.
`brew install python@3.12` (macOS) or from <https://www.python.org/downloads/> —
then use its `python3.12` for step 1. Never use a Conda interpreter.

`requirements.txt` is a full, exact lock (`pip freeze` output) of the environment
that Phase 0 was verified against: `crewai==1.15.20` plus its transitive
dependencies, 134 pinned distributions. It will be regenerated when later phases
add project dependencies (pandas, scikit-learn, matplotlib/seaborn, Streamlit,
and dev tooling).

### Verify the install

```bash
# CrewAI import smoke test (the Phase 0 acceptance check)
python -c "from crewai import Agent, Task, Crew, Process; \
from crewai.flow.flow import Flow, listen, start, router; print('crewai imports OK')"

python -m pip check          # -> No broken requirements found.
```

---

## Configuration

- **`config/settings.yaml`** — non-secret tunables only: deterministic seeds, the
  LLM model/provider/temperature, logging levels, validation tolerances, and a
  *provisional* business-context block. No paths, no secrets.
- **`config/llm.py`** — the single source of truth for LLM configuration. Reads
  `settings.yaml`; never reads the API key on import. `require_api_key()` is meant
  to be called only at execution time (Phase 6+).
- **`src/harbor_vale/io_paths.py`** — the single source of truth for filesystem
  paths. `PROJECT_ROOT` is derived from the file location; there are no
  machine-specific absolute paths anywhere in the project.

### Secrets

Secrets live in a git-ignored `.env` file, never in the repo.
[`.env.example`](.env.example) lists the variable **names** only:

```bash
cp .env.example .env
# then edit .env and add your key (only needed from Phase 6 onward)
```

---

## Project structure

```
CrewAI_Final_Project/
├── PROJECT_PLAN.md              # authoritative architecture + plan (source of truth)
├── README.md                   # this file
├── requirements.txt            # exact dependency lock (pip freeze)
├── .env.example                # secret NAMES only; real .env is git-ignored
├── conftest.py                 # test import bootstrap (repo root + src/ on sys.path)
│
├── config/
│   ├── settings.yaml           # non-secret tunables
│   ├── llm.py                  # single source of LLM config           [implemented]
│   └── narrative_fallbacks/    # (placeholder — Phase 6)
│
├── src/harbor_vale/
│   ├── io_paths.py             # single source of path truth           [implemented]
│   ├── logging_setup.py        # console + optional per-run file log   [implemented]
│   ├── contract/                # schema.py · builder.py · validator.py [implemented — Phase 3–4]
│   ├── plans/                   # contract_draft · cleaning_plan · insights_doc ·
│   │                             # feature_plan · experiment_plan       [implemented — Phase 3, 5]
│   ├── access/                  # allowlist.py · handoff.py (Crew1→Crew2 boundary) [implemented — Phase 5]
│   ├── tools/                   # profiling · cleaning · eda · feature · modeling [implemented — Phase 5]
│   ├── ml/                      # features.py · train.py · evaluate.py  [implemented — Phase 5]
│   ├── templates/                # eda_report.html · insights.md · styles.css (Jinja2) [implemented — Phase 5]
│   ├── demo/fault_injection.py  # deterministic mutation helpers (tests-only) [implemented — Phase 4]
│   ├── crews/{analyst_crew,scientist_crew}/                            # (placeholders — Phase 6–7)
│   └── flow/                                                           # (placeholder — Phase 8)
│
├── app/                        # Streamlit UI                          (placeholder — Phase 9)
├── data/raw/                   # downloaded datasets, git-ignored      [implemented — Phase 2]
├── artifacts/{crew1,validation,crew2}/                                 (placeholders — run outputs)
├── scripts/{download_data.py, calibrate_validation_tolerances.py}      [implemented — Phase 2, 4]
├── spike/                       # Phase 1 disposable spikes (task_1_1..task_1_6) [evidence]
├── docs/architecture.md         # orchestration decision + CrewAI 1.15.20 findings [Phase 1, corrected Phase 3, 5]
├── docs/contract_spec.md        # Dataset Contract specification                  [Phase 3]
├── docs/validation_calibration.md # scale/drift tolerance calibration evidence   [Phase 4]
├── tests/{unit,integration,failure,smoke,fixtures}/
│   └── unit/  — Phase 0–5 unit tests (see "Running the tests" above)  [implemented]
└── working flow/               # per-session development log
```

Directories marked *(placeholder)* currently contain only a `.gitkeep` and will be
filled in the phase noted. `PROJECT_PLAN.md` §L has the complete target layout.

---

## Running the tests

`pytest` is **not installed yet** (it is a dev dependency, added in a later phase
together with `requirements-dev.txt`). The Phase 0 unit tests are written in
pytest style **and** are runnable directly with the interpreter:

```bash
source .venv/bin/activate
python tests/unit/test_io_paths.py                    # path layer
python tests/unit/test_logging_setup.py                # logging foundation
python tests/unit/test_dataset_ingestion.py             # Phase 2 — dataset
python tests/unit/test_contract_schema.py                # Phase 3 — DatasetContract
python tests/unit/test_contract_builder.py                # Phase 3 — deterministic builder
python tests/unit/test_observed_not_enforced.py             # Phase 3 — the central rule
python tests/unit/test_validator_artifacts.py               # Phase 4 — check family A
python tests/unit/test_validator_schema.py                   # Phase 4 — check family B
python tests/unit/test_validator_target.py                    # Phase 4 — check family C
python tests/unit/test_validator_constraints.py                 # Phase 4 — check family D
python tests/unit/test_validator_scale_drift.py                  # Phase 4 — check family E ⭐
python tests/unit/test_validator_integrity.py                     # Phase 4 — check family F
python tests/unit/test_validator_modeling.py                       # Phase 4 — check family G
python tests/unit/test_validator_aggregate.py                       # Phase 4 — gate decision rule
python tests/unit/test_fault_injection.py                            # Phase 4 — demo helpers
python tests/unit/test_validation_report_rendering.py                 # Phase 4 — report rendering
python tests/unit/test_handoff_allowlist.py                             # Phase 5 — boundary security ⭐
python tests/unit/test_cleaning_executor.py                              # Phase 5 — CleaningPlan + executor
python tests/unit/test_eda_tools.py                                       # Phase 5 — EDA stats/figures/rendering
python tests/unit/test_feature_builder.py                                  # Phase 5 — FeaturePlan + build_features
python tests/unit/test_model_selection.py                                   # Phase 5 — train/evaluate determinism
python tests/unit/test_plans_validation.py                                   # Phase 5 — guardrail parser contract
python tests/unit/test_hardcoded_e2e.py                                       # Phase 5 — full E2E on real data ⭐ (~35s)
```

Each prints `PASS`/`FAIL` per check and exits non-zero on any failure. Once
`pytest` is added, `pytest` from the project root will discover the same files
unchanged (`conftest.py` already wires the import paths).

---

## Project status

### Done — Phase 0: project foundation

- [x] Project-local `.venv` on non-Conda **Python 3.12.14**, isolated from Conda `base`.
- [x] **CrewAI 1.15.20** installed; import smoke test passes
      (`Agent, Task, Crew, Process`; `Flow, listen, start, router`).
- [x] `requirements.txt` — exact pinned lock; `pip check` clean.
- [x] Git repository initialised; `.gitignore`; `.env.example` (names only); `.env` git-ignored.
- [x] Full directory skeleton per `PROJECT_PLAN.md` §L.
- [x] `src/harbor_vale/io_paths.py` — deterministic central path layer, zero machine-specific paths.
- [x] `src/harbor_vale/logging_setup.py` — console + optional per-run file logging, idempotent.
- [x] `config/settings.yaml` + `config/llm.py` — non-secret config; import needs no API key.
- [x] Unit tests for the path and logging layers (16 checks, all passing).

### Done — Phase 1: CrewAI execution-pattern spike

- [x] `output_pydantic`, `guardrail` + retry, `callback` timing, `context=[task]`,
      `Literal` tool enforcement, and `Flow` / `@router` / `or_` / `and_` all
      verified at runtime against the pinned **`crewai==1.15.20`**
      (`spike/task_1_1_*.py` … `spike/task_1_6_*.py`).
- [x] Orchestration decision: **Pattern A** (one sequential `Crew` per crew;
      `Agent → validated plan → guardrail → deterministic callback → artifact →
      next Agent`), with **Pattern B** kept as a documented fallback.
- [x] [`docs/architecture.md`](docs/architecture.md) records the decision, the
      proven `1.15.20` behaviour, the failure modes, and the boundaries production
      code must follow.
- [x] No production `Agent` / `Task` / `Crew` / `Flow` written — spike code only,
      marked disposable.

### Done — Phase 2: dataset selection and reproducible ingestion

- [x] **Telco Customer Churn** selected against the Plan's 12 mandatory criteria.
- [x] `scripts/download_data.py` — reproducible acquisition with SHA256 verification.
- [x] `data/README.md` — provenance, licensing, schema, and known data-quality issues.
- [x] Dataset ingestion unit tests.

### Done — Phase 3: Dataset Contract schema

- [x] `contract/schema.py` — the `DatasetContract` Pydantic model, `observed`
      (measured, never enforced) strictly separated from `constraints`
      (enforced only when explicitly declared with a justification).
- [x] `contract/builder.py` — deterministic Python merges a validated
      `ContractDraft` + real CSV bytes + pandas-measured facts into a
      `DatasetContract`; every measured number (SHA256, row/column counts,
      dtypes, statistics) comes from the actual file, never an LLM.
- [x] `plans/contract_draft.py` + guardrail — the semantic-only draft an
      agent will produce in Phase 6+; structurally cannot carry a measured value.
- [x] **`test_observed_not_enforced.py`** proves the central rule: a value
      above `observed.max` alone is never rejected.

### Done — Phase 4: the deterministic Validation Gate ⭐

- [x] `contract/validator.py` — every check family A–G (artifacts, schema,
      target, constraints, scale_drift, integrity, modeling), **zero LLM
      calls**. `passed = (errors == 0)`; the gate runs every applicable check
      and collects every finding, never stopping at the first failure.
- [x] Family A checks all **four** required Crew 1 artifacts
      (`clean_data.csv`, `dataset_contract.json`, `eda_report.html`,
      `insights.md`) present/non-empty — the latter two by existence/size
      only, never read, so the Crew 1 → Crew 2 handoff boundary (§G.0) is
      not widened.
- [x] `config/settings.yaml`'s `validation:` tolerances calibrated against
      the real Telco dataset (bootstrap evidence) and marked final, not
      provisional — see [`docs/validation_calibration.md`](docs/validation_calibration.md).
- [x] `ValidationFinding` / `ValidationReport` (Pydantic) + `render_validation_report_markdown`.
- [x] Scale-drift detection (§E.3): the mandatory incident reproduction —
      `monthly_charges × 100`, dtype unchanged — is caught and reported as
      **"SUSPECTED SCALE CHANGE"**, without ever claiming a specific currency
      the source dataset never documented.
- [x] `demo/fault_injection.py` — deterministic mutation helpers (for tests
      only at this phase; not wired to any CLI flag or Flow yet).
- [x] `observed.*` remains unenforceable by itself — proven again at the gate
      layer, not just the contract-representation layer.
- [x] 10 test files, every check family + aggregate gate behaviour covered.

### Done — Phase 5: deterministic tools + handoff boundary enforcement ⭐

**"Agent plans, Python executes" — the entire execution layer built and
proven BEFORE any agent is connected.** Plain Python functions with
explicit typed signatures only — no CrewAI `@tool`/`BaseTool` yet (that
wrapping is Phase 6–7). Zero LLM/Agent/Task/Crew/Flow anywhere.

- [x] **`access/allowlist.py` + `access/handoff.py`** — the Crew 1 → Crew 2
      boundary (§G.0): Layer 1 is logical names only (`HandoffName =
      Literal["clean_data", "dataset_contract"]`, no path parameter exists
      in the public signature); Layer 2 is `ExactFileAllowlist` — exact
      resolved files, never a directory/glob/prefix, `../` traversal and
      symlink escapes neutralised by `Path.resolve()`. 24 boundary-security
      tests cover every denylist vector (raw data, `_internal/*`,
      `insights.md`, `eda_report.html`, traversal, absolute paths, symlink
      escapes, sibling files, directories).
- [x] **`tools/profiling_tools.py` + `tools/cleaning_tools.py` +
      `plans/cleaning_plan.py`** — deterministic dataset profiling and a
      closed 7-operation `CleaningPlan` executor (`drop_duplicates`,
      `impute`, `cast`, `rename`, `drop_column`, `clip`,
      `standardize_category`) — no `eval`, no arbitrary transform.
- [x] **`tools/eda_tools.py` + `templates/`** — deterministic EDA
      statistics/correlations/figures (matplotlib, `Agg` backend, closed
      after generation, deterministic filenames) and Jinja2-autoescaped
      `eda_report.html`/`insights.md` rendering, with a visible degraded
      banner when narrative is unavailable.
- [x] **`plans/insights_doc.py`** — `InsightsDoc`'s anti-hallucination rule:
      every `evidence_stat_key` must resolve to a real key in the measured
      EDA statistics, or the insight is rejected.
- [x] **`tools/feature_tools.py` + `ml/features.py` + `plans/feature_plan.py`**
      — a validated `FeaturePlan` cross-checked against the real
      `DatasetContract` (hard exclusions mechanically blocked, advisory
      exclusions require a justified override, required features enforced,
      target never admissible as a feature), executed via a closed-vocabulary
      `sklearn.ColumnTransformer`.
- [x] **`ml/train.py` + `ml/evaluate.py` + `plans/experiment_plan.py`** —
      the closed 3-estimator vocabulary (`logistic_regression`,
      `random_forest`, `gradient_boosting`) with per-estimator parameter
      allowlists (`random_state` never agent-settable); the approved
      protocol exactly (`train_test_split(test_size=0.2, stratify=y,
      random_state=42)`, `StratifiedKFold(5, shuffle=True, random_state=42)`
      on train only, preprocessing inside the `Pipeline`, test set touched
      once); Python-only winner selection (argmax, deterministic tie-break).
- [x] **The hardcoded, zero-LLM, full end-to-end proof** — raw Telco data
      (7,043 real rows, not the 30-row synthetic fixture) → cleaning →
      EDA → contract → **Phase 4 gate PASS** → Crew 2 handoff → features →
      train/evaluate → winner → `experiments.json` → `model.joblib`. Run
      **twice** with identical inputs/plans/seeds: verified byte-identical
      for every artifact including figures and `model.joblib` itself — the
      one field allowed (and confirmed) to differ is the validation
      report's own `validated_at` timestamp.
- [x] 130 new test functions across 7 files, plus every Phase 0–4 test
      still green.

### Not started

Everything else. Specifically **not implemented and not working yet**:

- **Crew 1** (Data Analyst) and **Crew 2** (Data Scientist) (Phases 6–7) —
  the deterministic tools above exist as plain functions; CrewAI
  `@tool`/`BaseTool` wrapping and the actual `Agent`/`Task`/`Crew`
  definitions do not exist yet.
- The **Flow** orchestration and failure demo (Phases 8, 10).
- **Streamlit** app (Phase 9).
- Any trained **model** actually served, evaluation report, or model card
  as a real production artifact (the Phase 5 proof's model/reports exist
  only in an isolated test workspace, never in `artifacts/`).

There is no runnable pipeline yet. `make run` / `make demo-fail` do not exist.

---

## Reproducibility (planned framing)

The deterministic layer of this pipeline is intended to be fully reproducible:
given the same inputs and the same stored agent plans, it produces identical
artifacts. The agent layer is not — LLM outputs vary between runs. That is
precisely why every agent decision is captured as a structured plan artifact, and
why all execution is performed by deterministic Python. Seeds
(`PYTHONHASHSEED=0`, `numpy` 42, sklearn `random_state=42`) are pinned in
`config/settings.yaml`.

---

## Development log

Every meaningful work session is recorded under [`working flow/`](working%20flow/)
with a fixed 11-heading format. Start there (latest file) to see exactly what has
been done and what is next.

## License

Not yet specified.
