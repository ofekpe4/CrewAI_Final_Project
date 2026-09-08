# Rule: Task Execution Workflow

## Scope

- Execute **only** tasks explicitly approved in the current user prompt.
- Any scope expansion — extra files, extra refactors, "while I'm here" fixes —
  requires approval first.
- Completing a task is **not** authorization to start the next one.
- Never continue automatically to a later Task or Phase.

## Required lifecycle

Every approved task:

1. **Inspect** — check actual state on disk before changing anything. Do not assume.
2. **Execute** — implement only the approved scope.
3. **Verify** — run the real check (test, import, command) and read the real output.
4. **Report** — structured report, see below.
5. **STOP** — wait for human review.

## Required report contents

Every execution report must include:

- **Changes made** — files created/modified, with paths.
- **Verification** — the commands or tests run, and their actual results.
- **Warnings / problems** — anything unexpected, even if non-blocking.
- **Current status** — PASS / FAIL / PARTIAL / NOT EXECUTED.
- **Manual action required** — whether the human must do something (e.g. supply an API key).

## Communication

- Answer the user in **Hebrew**.
- Commands, paths, filenames, code, and raw output stay in English.
- Never report success without passing verification.
