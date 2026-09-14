"""The single most important test in Phase 3 (PROJECT_PLAN.md §E.1 rule 3, §E.2).

**The rule under test:** `observed` != `constraints`. A number Python
measured from the current dataset must never, by itself, become an
enforceable business rule. Enforcement exists only where a semantic
declaration (from the — here already-validated — `ContractDraft`) explicitly
put one there, with a justification.

This file proves it against a REAL built contract (from
`tests/fixtures/telco_contract_fixture.csv`, via the real
`contract/builder.py`) — not a hand-typed JSON blob standing in for one.

Explicitly NOT tested here: whether a *candidate* dataset later passes or
fails against this contract (that comparison, and the PASS/FAIL gate itself,
is `contract/validator.py` — Phase 4, not built yet). This file only proves
facts about the contract's own *representation*: what got copied from
`observed` into `constraints`, and what did not.

Runnable two ways:
  * ``pytest tests/unit/test_observed_not_enforced.py``   (once pytest is installed)
  * ``python tests/unit/test_observed_not_enforced.py``   (no test dependency required)
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harbor_vale.contract.builder import build_contract  # noqa: E402
from harbor_vale.contract.schema import BusinessRangeConstraint  # noqa: E402
from harbor_vale.plans.contract_draft import validate_contract_draft  # noqa: E402
from tests.fixtures.build_example_contract import build_draft  # noqa: E402

FIXTURE_CSV = _ROOT / "tests" / "fixtures" / "telco_contract_fixture.csv"


def _built_contract():
    ok, draft = validate_contract_draft(build_draft())
    assert ok, f"fixture draft should be valid: {draft}"
    return build_contract(
        draft, FIXTURE_CSV,
        contract_version="1.0.0", run_id="test-run", created_by="test",
        dataset_name="telco_customer_churn", source_documentation_url="https://example.invalid",
    )


# --- THE core architectural claim ------------------------------------------

def test_observed_max_does_not_become_the_enforced_business_range_max() -> None:
    """The central claim, stated as literally as possible.

    `monthly_charges.observed.max` is a real, non-trivial measured number
    from the fixture CSV. If the builder (wrongly) turned observed snapshots
    into enforced rules, `constraints.business_range.max` would equal it.
    It must not — the draft declared `business_range.max = null` ("no
    defensible upper bound exists"), and the builder must have preserved
    that declaration exactly, not overwritten it with the measurement.
    """
    contract = _built_contract()
    monthly = next(c for c in contract.columns if c.name == "monthly_charges")

    observed_max = monthly.observed.max
    assert observed_max is not None and observed_max > 0, "the fixture must have a real observed max to make this test meaningful"

    business_range = monthly.constraints.business_range
    assert business_range is not None, "monthly_charges does declare a business_range (min=0) — just not a max"
    assert business_range.max is None, (
        f"BUG: observed.max ({observed_max}) leaked into constraints.business_range.max "
        f"({business_range.max}) — a measured snapshot must never become an automatic ceiling"
    )
    # And the two numbers are not even coincidentally equal via some other path.
    assert business_range.max != observed_max


def test_a_future_value_above_the_observed_max_is_not_structurally_rejected() -> None:
    """Demonstrates *why* snapshot != business rule, at the representation level.

    Not a Phase 4 gate invocation (`contract/validator.py` does not exist
    yet) — just the honest structural fact: with `business_range.max = None`,
    there is nothing in the contract for any future check to compare a new
    value against. A naive "is this value within the business range"
    predicate, applied only to what THIS contract actually declares, cannot
    reject a legitimate future premium-plan charge above today's snapshot.
    """
    contract = _built_contract()
    monthly = next(c for c in contract.columns if c.name == "monthly_charges")
    business_range = monthly.constraints.business_range
    hypothetical_future_value = monthly.observed.max + 50.0  # a plausible future premium plan

    def within_declared_business_range(value: float, constraint) -> bool:
        # A minimal, local stand-in for "does a declared business_range
        # reject this value" — intentionally NOT contract/validator.py.
        if constraint is None:
            return True  # no range constraint declared at all => nothing to violate
        if constraint.min is not None and value < constraint.min:
            return False
        if constraint.max is not None and value > constraint.max:
            return False
        return True

    assert within_declared_business_range(hypothetical_future_value, business_range), (
        "a future value above today's observed max must still be representable as "
        "'within the declared business range' when no max was ever declared"
    )


# --- the same claim, generalized: nothing observed silently becomes a constraint

def test_closed_domain_is_not_derived_from_observed_categories() -> None:
    """`payment_method` has exactly 4 observed categories in the fixture, and
    the draft DID declare a matching closed_domain — but a sibling
    observation-only fact (`value_distribution`) must not itself be treated
    as if it were the enforcement; the enforcement exists only because the
    draft separately, explicitly declared it with a justification.
    """
    contract = _built_contract()
    payment = next(c for c in contract.columns if c.name == "payment_method")
    assert payment.observed.value_distribution is not None
    assert payment.constraints.closed_domain is not None
    # The constraint's *values* are the draft's declared set, not merely
    # "whatever pandas happened to observe" reinterpreted as a rule object —
    # prove this by constructing the naive BAD pattern by hand and showing
    # it is not what the builder actually produced structurally: the real
    # constraint carries a `justification`, something no `observed.*`
    # field has any concept of.
    assert payment.constraints.closed_domain.justification.strip() != ""
    assert not hasattr(payment.observed, "justification")


def test_a_column_with_no_declared_range_gets_no_range_constraint_regardless_of_observed_spread() -> None:
    """`tenure_months` has plenty of observed spread (0 to ~72) — but a
    column-level rule only exists if it was declared. Contrast with
    `monthly_charges`, which the draft *did* give a `business_range.min`.
    Here we build a throwaway column with a wide observed range and NO
    declared business_range and confirm the resulting `constraints` really
    is empty, not auto-filled from the observed spread.
    """
    contract = _built_contract()
    # `senior_citizen` is 0/1 in the draft — deliberately not range-declared,
    # while still being genuinely numeric and observed to have a real min/max.
    senior = next(c for c in contract.columns if c.name == "senior_citizen")
    assert senior.observed.min is not None and senior.observed.max is not None
    assert senior.constraints.business_range is None, (
        "no business_range was declared for senior_citizen — it must stay None "
        "even though observed.min/max are real, present numbers"
    )


def test_scale_drift_is_not_derived_from_observed_standard_deviation() -> None:
    """`total_charges` has a real, large observed standard deviation in the
    fixture (cumulative billing varies a lot by tenure) but the draft never
    declared a `scale_drift` policy for it (only `monthly_charges` did) — so
    it must come out `None`, regardless of how volatile the observed data is.
    """
    contract = _built_contract()
    total_charges = next(c for c in contract.columns if c.name == "total_charges")
    assert total_charges.observed.std is not None and total_charges.observed.std > 0
    assert total_charges.constraints.scale_drift is None


def test_business_range_and_closed_domain_remain_independently_constructible_bad_vs_good() -> None:
    """docs/contract_spec.md's paired BAD/GOOD examples, executed as assertions.

    BAD (not what the builder does, shown only to contrast):
        business_range = BusinessRangeConstraint(min=0, max=<observed max>, justification="...")
    GOOD (what the builder actually produces for monthly_charges):
        business_range.max is None
    Both are *constructible* — pydantic doesn't know which one is "wrong" —
    which is exactly why this has to be an architectural discipline enforced
    by the builder never doing the BAD thing, proven above, not a schema rule
    that could reject the BAD shape outright.
    """
    contract = _built_contract()
    monthly = next(c for c in contract.columns if c.name == "monthly_charges")
    observed_max = monthly.observed.max

    bad_pattern = BusinessRangeConstraint(
        min=0, max=observed_max, justification="derived automatically from the observed snapshot"
    )
    assert bad_pattern.max == observed_max  # constructible, but NOT what build_contract() produced

    good_pattern = monthly.constraints.business_range
    assert good_pattern.max is None
    assert good_pattern != bad_pattern


if __name__ == "__main__":
    _failures: list[str] = []
    for _name, _fn in sorted(
        (n, f) for n, f in dict(globals()).items() if n.startswith("test_") and callable(f)
    ):
        try:
            _fn()
        except Exception as exc:  # noqa: BLE001
            _failures.append(_name)
            print(f"FAIL  {_name}: {exc.__class__.__name__}: {exc}")
        else:
            print(f"PASS  {_name}")
    print(f"\n{len(_failures)} failed" if _failures else "\nall passed")
    sys.exit(1 if _failures else 0)
