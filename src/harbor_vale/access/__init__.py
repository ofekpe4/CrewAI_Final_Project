"""The Crew 1 → Crew 2 handoff boundary (PROJECT_PLAN.md §G.0).

``allowlist`` — Layer 2, the exact-file allowlist (`ExactFileAllowlist`,
`HandoffAccessDenied`). ``handoff`` — Layer 1, logical names instead of
paths (`HandoffName`, `Crew2Handoff.read_handoff`).

No CrewAI dependency; no Agent/Task/Crew/Flow constructed here. Importing
this package has no side effects.
"""
