# Harbor & Vale — Project Instructions

Industry-Simulated AI Product Workflow: two CrewAI crews separated by a
machine-enforced dataset contract and a deterministic validation gate.

---

## Project Source of Truth

- `PROJECT_PLAN.md` (repo root) is the authoritative architecture and project plan.
- Before making an architectural decision or starting a new implementation phase,
  read the relevant sections of `PROJECT_PLAN.md`. Read sections, not the whole file.
- Do not silently deviate from the approved Plan.
- If implementation evidence contradicts the Plan, **report the conflict and wait for
  approval** before changing the Plan or the architecture.
- Useful section map: `C.2` execution pattern · `E` contract · `F` validation gate ·
  `G.0` handoff boundary · `H` Flow · `T` phases and dependency graph · `W` Definition of Done.

## Task-by-Task Workflow

- Work only on tasks explicitly approved in the current user prompt.
- **Never automatically continue to the next Task or Phase.**
- Every approved task follows: **inspect → implement → verify → report → STOP**.
- Completing one task is not authorization for the next one.
- After the approved scope is complete, STOP and wait for human review.
- See `.claude/rules/task-workflow.md`.

## Communication

- **Answer the user in Hebrew.**
- Commands, code, filenames, APIs, paths, Git names, and raw technical output stay in English.
- Execution reports must clearly distinguish: **PASS / FAIL / NOT EXECUTED / warning /
  unresolved issue**. Never blur these together.

## Verification

- Never report a task as complete unless its verification actually passed.
- Show the real commands/tests and their real output. Do not paraphrase results.
- Do not hide failures behind silent fallbacks.
- Report deviations and unexpected behavior explicitly, even when minor.

## Environment

- **Do not use Conda/Anaconda `base` as the project environment**, even if the shell shows `(base)`.
- The project uses a project-local `.venv`, created only once explicitly approved.
- Do not install project dependencies globally.
- Do not install, upgrade, or modify dependencies unless the current task explicitly authorizes it.

## Project Focus

- The primary learning objective is **agentic AI with CrewAI**: Agents, Tasks, Tools,
  structured outputs, guardrails, Crews, Flow, routing, context passing, agent boundaries,
  and failure handling.
- Avoid unnecessary infrastructure and over-engineering. Keep the ML deliberately simple.
- Deterministic Python owns everything precision-critical: execution, measurement, validation.

## Handoff Safety

- Crew 2 must **never** access raw data or Crew 1 internal artifacts.
- The approved Crew 1 → Crew 2 handoff is exactly two files:
  - `artifacts/crew1/clean_data.csv`
  - `artifacts/crew1/dataset_contract.json`
- Blocked for Crew 2: `data/raw/*`, `artifacts/crew1/_internal/*`, `insights.md`, `eda_report.html`.
- **PASS/FAIL at the handoff boundary is deterministic Python logic, never an LLM decision.**
- See `.claude/rules/project-safety.md`.

## Session Continuity

At the start of a fresh implementation session:
1. Inspect the project state on disk.
2. Read the relevant `PROJECT_PLAN.md` sections for the current task.
3. Read the latest entry in `working flow/` if one exists.
4. Inspect Git state, once Git exists.
5. Then execute **only** the currently approved task.

At the end of meaningful implementation work, add or update a session summary in
`working flow/` using the 11 required headings (see `working flow/README.md`).
