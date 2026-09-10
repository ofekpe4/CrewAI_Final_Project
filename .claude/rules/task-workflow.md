# Rule: Task Execution Workflow

## Scope

- Execute **only** tasks explicitly approved in the current user prompt.
- Any scope expansion — extra files, extra refactors, "while I'm here" fixes —
  requires approval first.
- Completing a task is **not** authorization to start the next one.
- Never continue automatically to a later Task or Phase.

## Required lifecycle

Every approved task follows this exact end-of-task sequence:

1. **IMPLEMENT** — inspect actual state on disk first (do not assume), then
   implement only the approved scope.
2. **VERIFY** — run the real check (test, import, command) and read the real
   output. Never report success without passing verification.
3. **WRITE WORKING-FLOW SESSION RECORD** — add
   `working flow/YYYY-MM-DD_session-N.md` with the 11 required headings
   (see `working flow/README.md`). This happens **before** the task commit,
   because the record itself belongs inside that commit.
4. **STAGE** — `git add` **only** the files that belong to this task
   (the task's own changes **plus** the session record from step 3).
5. **REVIEW STAGED DIFF** — `git diff --cached` (or `--stat` then the full diff).
   Confirm nothing unrelated is staged.
6. **COMMIT** — one focused, professional commit on the current branch.
7. **POST-COMMIT VERIFY** — immediately run, and read the output of:
   - `git status --short`
   - `git branch --show-current`
   - `git log -1 --oneline`
8. **FINAL RESPONSE** — the structured report (see below), including the
   mandatory `### Post-Commit Verification` section.
9. **STOP** — wait for human review. Completing this task is not authorization
   for the next one.

## Working-flow record vs. the task commit — permanent clarification

This removes a recurring Git/reporting ambiguity. It is durable.

1. **The session record is written BEFORE the task commit**, because the record
   is part of that same commit.
2. **The session record MUST NOT be expected to contain the hash of the commit
   that contains itself.** A file cannot carry the hash of the commit it is
   committed in.
3. **Git wording inside the session record must be unambiguous and must not
   claim a commit that has not happened yet.**
   - Use: `Files intended for this task commit: <paths>`
   - Do **NOT** use: `This session commits: ...` (or any past/definite tense)
     while the file is being written, i.e. before the commit exists.
   - It is fine for the record to name the **parent** commit (which does exist)
     and the branch.
4. **After the commit is successfully created**, run (POST-COMMIT VERIFY):
   - `git status --short`
   - `git branch --show-current`
   - `git log -1 --oneline`
5. **The FINAL RESPONSE to the user must always contain a section:**

   `### Post-Commit Verification`

   with exactly these items:
   - branch
   - commit hash
   - commit message
   - working tree clean: YES/NO
   - expected task files tracked: YES/NO
6. **The final response — not the working-flow file — is the authoritative
   source for the newly-created task commit hash.** If a later session needs
   that hash, it comes from Git (`git log`) or the prior final response, never
   from an expectation that the session record self-references it.
7. **Do NOT create a second commit, and do NOT `git commit --amend`, solely to
   insert the commit's own hash into its session record.** The hash lives in
   Git history and in the final response; that is sufficient.
8. **If a task is intentionally not committed**, the final response must state
   explicitly:

   `Task commit created: NO`

   and explain why (e.g. task only PARTIALLY verified, blocked on a real LLM,
   user asked for inspection only). In that case the `### Post-Commit
   Verification` section still reports branch + working-tree state and lists the
   uncommitted files as `Files intended for a future task commit`.

## Required report contents

Every execution report (the FINAL RESPONSE) must include:

- **Changes made** — files created/modified, with paths.
- **Verification** — the commands or tests run, and their actual results.
- **Warnings / problems** — anything unexpected, even if non-blocking.
- **Current status** — PASS / FAIL / PARTIAL / NOT EXECUTED.
- **Manual action required** — whether the human must do something (e.g. supply an API key).
- **`### Post-Commit Verification`** — as defined above (mandatory, every task,
  committed or not).

## Communication

- Answer the user in **Hebrew**.
- Commands, paths, filenames, code, and raw output stay in English.
- Never report success without passing verification.
