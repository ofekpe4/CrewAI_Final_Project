"""Dataset Contract package (PROJECT_PLAN.md §E).

``schema`` — the production ``DatasetContract`` model, ``observed`` vs.
``constraints`` separated (§E.2). ``builder`` — deterministic Python that
merges a validated :class:`~harbor_vale.plans.contract_draft.ContractDraft`
with real CSV bytes and measured pandas facts into a ``DatasetContract``.

Importing this package has no side effects.
"""
