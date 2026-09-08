# Rule: Project Safety Invariants

These are durable. Violating one is a stop-and-ask situation, not a judgment call.

## Environment

- **Never** install project dependencies into Conda/Anaconda `base` or a global Python.
- The project environment is a project-local `.venv`, and only after explicit approval.

## Secrets

- **Never** commit or expose secrets, API keys, or tokens.
- Keys live in `.env` (gitignored). `.env.example` holds names only, never values.
- No secrets in `working flow/`, in logs, in commit messages, or in reports.

## The Crew 1 → Crew 2 boundary

- **Never** change the approved handoff boundary without approval.
- The handoff is exactly: `clean_data.csv` + `dataset_contract.json`.
- **Never** give Crew 2 access to `data/raw/*` or to `artifacts/crew1/_internal/*`
  (including `insights.md` and `eda_report.html`).
- Enforcement is mechanical (exact-file allowlist + `Literal` tool signatures),
  never prompt-based.

## The Validation Gate

- **Never** let an LLM decide the gate's PASS/FAIL. It is deterministic Python only.
- The gate is the single blocking authority before Crew 2 runs.
- Any Crew 2 sanity check is explicitly non-blocking and must be labeled as such.

## Failure handling

- **Do not** silently replace a critical agent failure with a fallback that looks successful.
  Critical agents: Data Quality Inspector, Data Contract Architect, Feature Engineer,
  Modeling Specialist → validate, retry, then **fail visibly**.
- Fallbacks are allowed only for narrative artifacts, and must carry a visible DEGRADED marker.

## Fault injection

- Fault injection exists for the failure demo only. It must never run on the default path:
  no-op unless an explicit CLI flag is passed.

## Scope discipline

- Do not introduce additional infrastructure (databases, auth, deployment platforms,
  extra frameworks) unless the Plan justifies it and the user approves it.
