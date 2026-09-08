# working flow

Session continuity layer for this project.

> The folder name contains a space **on purpose**. Do not rename it to `working_flow`,
> `docs`, or `.notes`. The approved Plan requires this exact name.

## Why this folder exists

Claude Code sessions do not share memory. A fresh session, or a session after `/clear`,
starts with no knowledge of what was already built, what was tried and rejected, or why a
decision was made. This folder is how that context survives.

## What this folder is — and is not

| | |
|---|---|
| **This folder** | The **execution and history layer**. What actually happened, when, and why. |
| **`PROJECT_PLAN.md`** | The **architecture source of truth**. What we intend to build and why. |

`PROJECT_PLAN.md` stays authoritative for architecture. If a session summary and the Plan
disagree about architecture, the Plan wins — and the disagreement itself is worth reporting.

## File naming

```
YYYY-MM-DD_session-N.md
```

Example: `2026-09-07_session-0.md`

## Required headings

Every meaningful session summary uses these **exact 11 headings**, in this order:

1. Session Goal
2. Work Completed
3. Files Created
4. Files Modified
5. Architectural Decisions
6. Commands / Tests Run
7. Results
8. Git Status
9. Known Issues
10. Next Session
11. Important Context

## Writing rules

- **Concise but complete.** Enough to restore context without rereading the code.
  No target line count.
- **No secrets.** No API keys, tokens, passwords, or connection strings. Ever.
- **Do not paste large logs.** Describe the outcome and point at `logs/` instead.
- **Record *why*.** `Architectural Decisions` must carry the reasoning, not just the choice.
  A decision without its reason cannot be re-evaluated later.
- **`Next Session` must be specific.** "Continue working" is useless.
  "Run Task 0.2: verify available Python interpreters and decide 3.12 vs 3.13" is useful.
- **Only record verified facts.** Never write down work that was not actually done.

## Protocol

**Start of a session:** read the most recent summary here (and its predecessor if it is
referenced), then compare it against the real state on disk and in Git. A mismatch between
what the summary claims and what is actually there is a red flag — investigate before
touching code.

**End of meaningful work:** add or update the session summary. This is part of the
Definition of Done, not an optional extra.

**Git:** these summaries are committed alongside the code they describe, in the branch for
that phase, e.g. `docs(working flow): session N — validation gate complete`.
