"""The test that proves the design works.

Build file 17 names this file in its definition of done and calls the first test here "the
normalisation test — this is the one that proves the design works". It is worth saying why
in the file rather than only in the commit.

A GN division that was genuinely hit hardest produces assessments that are **higher in
value, more numerous, and faster to approve** than its neighbours. Every one of those is a
signal the detectors look for. Compared against a national or district average, the
worst-hit division in the country is the most anomalous division in the country — and the
flag that comes out says somebody's paperwork looks suspicious because their village was
destroyed.

The officer who assessed the worst damage is therefore the officer most likely to be
flagged, and they are the one who did the most work under the worst conditions. ADR-009
exists because that flag can end a career on a statistical artifact.

So: the same assessment profile must produce **no flag** at impact class 4 and **a flag** at
impact class 1. If those two ever come out the same, this agent is comparing divisions with
each other again and must not ship.
"""

from __future__ import annotations

import pytest

from agent_svc.agents.ledger_anomaly import detectors, normalisation
from agent_svc.agents.ledger_anomaly.normalisation import (
    EXPECTED_CLAIM_SHARE,
    EXPECTED_TOTAL_LOSS_SHARE,
    MIN_ASSESSMENTS,
)
from tests.agents.ledger_anomaly.conftest import MILD, SEVERE, context, division

# One assessment profile, used at two impact classes. High value, clustered at total loss,
# a full division's worth - the shape a badly hit village produces.
PROFILE = {"count": 40, "total_loss_share": 0.7, "approval_minutes": 90.0}


def signals_for(code: str, impact_class: int, **overrides) -> list:
    rows = division(code, **{**PROFILE, **overrides})
    divisions = {code: context(code, impact_class=impact_class)}
    return detectors.run_all(normalisation.build_profiles(rows, divisions))


# ---------------------------------------------------------------------------------------
# The pair that proves it
# ---------------------------------------------------------------------------------------


def test_a_severe_division_with_high_value_assessments_produces_no_flag() -> None:
    """**The test that proves the design works.**

    Impact class 4 expects 70% total loss. A division producing exactly that is producing
    what the forecast predicted, and flagging it would flag the damage rather than anything
    about the assessments.
    """
    fired = [signal.detector for signal in signals_for(SEVERE, impact_class=4)]

    assert "value_distribution" not in fired


def test_the_identical_profile_at_low_impact_does_produce_a_flag() -> None:
    """The other half. Without it, "produces no flag" could be satisfied by a detector that
    never fires at all — which would be a safe agent and a useless one."""
    fired = [signal.detector for signal in signals_for(MILD, impact_class=1)]

    assert "value_distribution" in fired


def test_the_two_divisions_differ_only_in_their_forecast() -> None:
    """Stated explicitly, because the pair above only means something if the assessments
    really are identical. The sole difference is the impact class."""
    severe = division(SEVERE, **PROFILE)
    mild = division(MILD, **PROFILE)

    assert [row.category for row in severe] == [row.category for row in mild]
    assert [row.assessed_value_lkr for row in severe] == [row.assessed_value_lkr for row in mild]


# ---------------------------------------------------------------------------------------
# The expectation itself
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("impact_class", [0, 1, 2, 3, 4])
def test_expected_claims_rise_with_the_impact_class(impact_class: int) -> None:
    """A monotone expectation is what makes the comparison meaningful. If class 3 expected
    less than class 2, a badly hit division would be flagged for being badly hit."""
    expectation = normalisation.expectation_for(context(impact_class=impact_class))

    assert expectation.expected_claims >= 0
    assert expectation.expected_total_loss_share == EXPECTED_TOTAL_LOSS_SHARE[impact_class]


def test_the_claim_share_is_monotone_in_the_impact_class() -> None:
    shares = [EXPECTED_CLAIM_SHARE[level] for level in sorted(EXPECTED_CLAIM_SHARE)]

    assert shares == sorted(shares)


def test_the_total_loss_share_is_monotone_in_the_impact_class() -> None:
    shares = [EXPECTED_TOTAL_LOSS_SHARE[level] for level in sorted(EXPECTED_TOTAL_LOSS_SHARE)]

    assert shares == sorted(shares)


def test_the_forecasts_own_household_estimate_wins_when_it_is_larger() -> None:
    """The forecast already accounts for the event; the static household count only counts
    doors. Taking the smaller would under-expect a division and flag it for the difference."""
    expectation = normalisation.expectation_for(
        context(impact_class=2, households=100, expected_affected=300)
    )

    assert expectation.expected_claims == 300


# ---------------------------------------------------------------------------------------
# Suppression, which is the safe direction
# ---------------------------------------------------------------------------------------


def test_an_unsurveyed_division_is_not_normalisable() -> None:
    """The forecast covers warned districts, not the country. A division with no forecast
    has nothing to compare against."""
    expectation = normalisation.expectation_for(context(impact_class=0, forecast_confidence=0.0))

    assert not expectation.normalisable
    assert "nothing to normalise against" in expectation.reason


def test_an_unsurveyed_division_produces_no_signals_at_all() -> None:
    """Being blind here is the correct trade. The tempting fallback - compare it against
    the district mean instead - is exactly the peer comparison this module exists to
    avoid."""
    rows = division(SEVERE, count=40, total_loss_share=0.9)
    divisions = {SEVERE: context(SEVERE, impact_class=0, forecast_confidence=0.0)}

    assert detectors.run_all(normalisation.build_profiles(rows, divisions)) == []


def test_a_division_missing_from_the_exposure_source_is_suppressed_not_guessed() -> None:
    """A division the forecast never covered arrives with no context at all, and the
    default `DivisionContext` has zero confidence - so it suppresses rather than defaulting
    to impact class 0, which would expect almost nothing and flag everything."""
    rows = division(SEVERE, count=40, total_loss_share=0.9)

    profiles = normalisation.build_profiles(rows, {})

    assert not profiles[0].normalisable


def test_a_division_with_too_few_assessments_produces_no_signals() -> None:
    """A handful of rows produces ratios that swing on a single one, and a flag built on
    that is noise a reviewer pays for."""
    rows = division(SEVERE, count=MIN_ASSESSMENTS - 1, total_loss_share=1.0)
    divisions = {SEVERE: context(SEVERE, impact_class=1)}

    profiles = normalisation.build_profiles(rows, divisions)

    assert not profiles[0].normalisable
    assert "swing on a single one" in (profiles[0].suppression_reason or "")
    assert detectors.run_all(profiles) == []


# ---------------------------------------------------------------------------------------
# The unit of analysis
# ---------------------------------------------------------------------------------------


def test_profiles_are_grouped_by_division_and_nothing_else() -> None:
    """ADR-009: officer identity is never a feature, including as a proxy. The unit is the
    GN division, and this is where that is fixed."""
    rows = division(SEVERE, count=10) + division(MILD, count=10)

    profiles = normalisation.build_profiles(rows, {SEVERE: context(SEVERE), MILD: context(MILD)})

    assert [profile.gn_division_code for profile in profiles] == [SEVERE, MILD]


def test_an_assessment_carries_no_officer_field_at_all() -> None:
    """The strongest form of the guarantee: not "no detector reads it" but "there is
    nothing to read".

    A rule can be forgotten by whoever adds the next detector. A field that does not exist
    cannot be grouped by.
    """
    from agent_svc.agents.ledger_anomaly.ports import Assessment

    fields = set(Assessment.__dataclass_fields__)
    forbidden = {"assessor_id", "assessor", "approver_id", "approved_by", "user_id", "officer_id"}

    assert not (fields & forbidden)
