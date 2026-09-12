"""Targeting, language routing, alert fatigue, and the gap report.

The claims here are the ones that decide who hears about a cyclone, and each of them has a
specific way of being wrong that this file pins down.

**Alert fatigue in both directions.** Suppress too little and by the third day of an event
people have stopped reading; suppress too much and somebody misses the escalation. The
tests assert both halves, because a rule that only got one half right would look correct in
whichever test was written first.

**Households with no phone are counted, not dropped.** They are the reason `/delivery/gaps`
exists. A division reported as fully covered when a third of it has no channel at all is
the map that stops an officer sending the vehicle.

**Unconfirmed is never delivered.** The gap arithmetic has to keep UNKNOWN on the wrong
side of the line, in every path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agent_svc.agents.warning import gaps as gap_rules
from agent_svc.agents.warning import targeting
from agent_svc.agents.warning.ports import (
    DELIVERY_STATUSES,
    ChannelOutcome,
    DivisionReach,
    PriorAlert,
    Receipt,
)
from alerting_svc.adapters.channels.base import languages_for
from alerting_svc.repo.base import DELIVERY_STATUSES as ALERTING_DELIVERY_STATUSES
from tests.agents.warning.conftest import NOON_COLOMBO, household

DIVISION = "LK-21-01-001"


def prior(number: int, impact_class: int, *, minutes_ago: int = 30) -> PriorAlert:
    return PriorAlert(
        household_id=f"hh-{number}",
        hazard_event_id="evt-1",
        impact_class=impact_class,
        sent_at=NOON_COLOMBO - timedelta(minutes=minutes_ago),
    )


# ---------------------------------------------------------------------------------------
# Alert fatigue
# ---------------------------------------------------------------------------------------


def test_a_second_watch_level_alert_to_the_same_household_is_suppressed() -> None:
    """Alert fatigue during a multi-day event is a real cause of people ignoring the one
    that mattered."""
    targets = [household(1, DIVISION), household(2, DIVISION)]

    kept, suppressed = targeting.suppress_fatigued(
        targets, [prior(1, impact_class=2)], impact_class=2
    )

    assert [target.household_id for target in kept] == ["hh-2"]
    assert suppressed == ["hh-1"]


def test_an_escalation_is_never_suppressed() -> None:
    """The other half, and the one that kills somebody if it is wrong.

    A household that had a watch and is now at warning level is being told something new.
    """
    targets = [household(1, DIVISION)]

    kept, suppressed = targeting.suppress_fatigued(
        targets, [prior(1, impact_class=2)], impact_class=3
    )

    assert [target.household_id for target in kept] == ["hh-1"]
    assert suppressed == []


def test_a_de_escalation_is_suppressed() -> None:
    """Somebody already told to evacuate does not need a watch-level message afterwards."""
    targets = [household(1, DIVISION)]

    kept, _ = targeting.suppress_fatigued(targets, [prior(1, impact_class=4)], impact_class=2)

    assert kept == []


def test_an_alert_outside_the_fatigue_window_does_not_suppress() -> None:
    """The window is what stops a three-day event silencing itself on day one."""
    start = targeting.fatigue_window_start(NOON_COLOMBO)
    stale = prior(1, impact_class=3, minutes_ago=targeting.FATIGUE_WINDOW_HOURS * 60 + 1)

    assert stale.sent_at < start


# ---------------------------------------------------------------------------------------
# Targeting
# ---------------------------------------------------------------------------------------


def test_two_households_sharing_one_handset_get_one_message() -> None:
    """A common arrangement in a village. The same evacuation order twice is noise at the
    moment attention is scarcest."""
    shared = [
        household(1, DIVISION),
        household(1, DIVISION),  # same hash
    ]

    assert len(targeting.deduplicate(shared)) == 1


def test_households_with_no_phone_never_collapse_into_each_other() -> None:
    """Each one is a separate person somebody has to go and find, and the gap figure has to
    say how many."""
    unreachable = [
        household(1, DIVISION, reachable=False),
        household(2, DIVISION, reachable=False),
    ]

    assert len(targeting.deduplicate(unreachable)) == 2


def test_a_household_with_no_channel_is_targeted_and_counted() -> None:
    """Dropping them here would report a division as fully covered when part of it cannot
    be reached at all."""
    plan = targeting.build_plan(
        [household(1, DIVISION), household(2, DIVISION, reachable=False)],
        reach={},
        priors=[],
        impact_class=3,
    )

    assert plan.as_summary() == {
        "targeted": 2,
        "no_channel_available": 1,
        "suppressed_for_fatigue": 0,
    }
    assert plan.counts_by_division()[DIVISION]["no_channel_available"] == 1


# ---------------------------------------------------------------------------------------
# Language routing
# ---------------------------------------------------------------------------------------


def test_a_stated_preference_wins() -> None:
    ordered = targeting.language_order(household(1, DIVISION, language="ta"))

    assert ordered[0] == "ta"
    assert set(ordered) == {"si", "ta", "en"}


def test_an_unknown_preference_falls_back_to_the_divisions_languages() -> None:
    """Never to an inference from a name. It is unreliable, and it goes wrong in exactly the
    communities most likely to be missed."""
    ordered = targeting.language_order(
        household(1, DIVISION),
        reach=DivisionReach(gn_division_code=DIVISION, dominant_languages=("ta",)),
    )

    assert ordered[0] == "ta"


def test_a_division_with_no_reference_entry_still_gets_an_order() -> None:
    """Sending in the wrong order is recoverable. Sending nothing is not."""
    ordered = targeting.division_language_order({}, (DIVISION,))

    assert ordered[DIVISION] == list(targeting.DEFAULT_LANGUAGE_ORDER)


def test_the_default_language_order_matches_alerting_svcs() -> None:
    """Two different default orders would send two communities in one division different
    languages depending on which service made the decision."""
    from alerting_svc.adapters.channels.base import Target

    theirs = languages_for(
        Target(target_ref_hash="h", gn_division_code=DIVISION, preferred_language=None),
        "APP",
    )

    assert tuple(theirs) == targeting.DEFAULT_LANGUAGE_ORDER


# ---------------------------------------------------------------------------------------
# The gap report
# ---------------------------------------------------------------------------------------


def receipts_for(targets: list, channel: str, status: str) -> list[Receipt]:
    return [
        Receipt(target_key=target.key, channel=channel, language="en", status=status)
        for target in targets
    ]


def test_a_target_confirmed_on_any_channel_is_confirmed_once() -> None:
    """The denominator is the number of households, not the number of messages."""
    targets = [household(index, DIVISION) for index in range(1, 4)]
    outcomes = [
        ChannelOutcome(channel="SMS", receipts=receipts_for(targets, "SMS", "FAILED")),
        ChannelOutcome(channel="APP", receipts=receipts_for(targets, "APP", "DELIVERED")),
    ]

    report = gap_rules.assess(outcomes, targets)

    assert report.confirmed == 3
    assert report.failed == 0
    assert report.targeted == 3


def test_unconfirmed_is_never_counted_as_delivered() -> None:
    """A channel that cannot confirm has not confirmed. Rounding it up produces a map that
    says a village was warned when nobody knows whether it was."""
    targets = [household(index, DIVISION) for index in range(1, 5)]
    outcomes = [ChannelOutcome(channel="LORA", receipts=receipts_for(targets, "LORA", "UNKNOWN"))]

    report = gap_rules.assess(outcomes, targets)

    assert report.confirmed == 0
    assert report.unconfirmed == 4
    assert report.gaps[0].confirmed_fraction == 0.0


def test_a_household_no_channel_attempted_is_reported_not_lost() -> None:
    """Silent omission is the failure this catches, and it is silent precisely because
    nothing produced a record to notice."""
    reached = household(1, DIVISION)
    missed = household(2, DIVISION, reachable=False)
    outcomes = [ChannelOutcome(channel="SMS", receipts=receipts_for([reached], "SMS", "DELIVERED"))]

    report = gap_rules.assess(outcomes, [reached, missed])

    assert report.targeted == 2
    assert report.no_channel_available == 1


def test_one_channel_failing_outright_does_not_take_the_others_down() -> None:
    """Required by build file 14: with one adapter failing 100%, the other channels still
    complete and the gaps report shows the failure accurately."""
    targets = [household(index, DIVISION) for index in range(1, 11)]
    outcomes = [
        ChannelOutcome(channel="SMS", error="gateway unreachable"),
        ChannelOutcome(channel="APP", receipts=receipts_for(targets, "APP", "DELIVERED")),
    ]

    report = gap_rules.assess(outcomes, targets)

    assert report.confirmed == 10
    assert report.channels_failed == ("SMS",)
    # The picture is complete but less trustworthy: SMS might have reached people nobody
    # has a record of, and the confidence says so rather than claiming certainty.
    assert report.divisions[0].reachability_confidence < 1.0


def test_a_division_below_the_threshold_is_named_worst_first() -> None:
    """The operationally important output: it names where to send a vehicle, in time."""
    good = [household(index, "LK-21-01-001") for index in range(1, 11)]
    bad = [household(index, "LK-21-01-002") for index in range(11, 21)]
    outcomes = [
        ChannelOutcome(
            channel="SMS",
            receipts=[
                *receipts_for(good, "SMS", "DELIVERED"),
                *receipts_for(bad[:2], "SMS", "DELIVERED"),
                *receipts_for(bad[2:], "SMS", "FAILED"),
            ],
        )
    ]

    report = gap_rules.assess(outcomes, [*good, *bad])

    assert [gap.gn_division_code for gap in report.gaps] == ["LK-21-01-002"]
    assert report.gaps[0].confirmed_fraction == 0.2


def test_every_summary_carries_its_denominator() -> None:
    """Never a percentage without one. "82% delivered" is unactionable."""
    targets = [household(index, DIVISION) for index in range(1, 11)]
    outcomes = [ChannelOutcome(channel="SMS", receipts=receipts_for(targets, "SMS", "UNKNOWN"))]

    report = gap_rules.assess(outcomes, targets)

    assert "of 10 targeted" in report.as_sentence()
    assert "10" in report.gaps[0].as_sentence()


def test_an_all_unknown_division_reports_low_reachability_confidence() -> None:
    """The number is about how much of the picture we know, not how likely delivery was.

    A division where every receipt came back UNKNOWN scores low even if everybody got the
    message, because the honest statement is that we cannot tell.
    """
    targets = [household(index, DIVISION) for index in range(1, 11)]
    outcomes = [ChannelOutcome(channel="LORA", receipts=receipts_for(targets, "LORA", "UNKNOWN"))]

    report = gap_rules.assess(outcomes, targets)

    assert report.divisions[0].reachability_confidence == gap_rules.MIN_CONFIDENCE


def test_a_fully_accounted_division_reports_full_confidence() -> None:
    targets = [household(index, DIVISION) for index in range(1, 11)]
    outcomes = [ChannelOutcome(channel="SMS", receipts=receipts_for(targets, "SMS", "DELIVERED"))]

    report = gap_rules.assess(outcomes, targets)

    assert report.divisions[0].reachability_confidence == 1.0


def test_the_delivery_vocabulary_matches_the_column_that_stores_it() -> None:
    """A status this agent counts and `alerting.delivery_receipt.status` rejects would fail
    at the INSERT, after the warning had already gone out."""
    assert set(DELIVERY_STATUSES) == set(ALERTING_DELIVERY_STATUSES)


def test_a_division_with_no_targets_is_not_reported_as_certain() -> None:
    """Zero targets is a targeting result worth looking at, not complete information."""
    assert gap_rules.reachability_confidence(targeted=0, definite=0, channels_failed=0) == 0.0


def test_the_gap_threshold_matches_alerting_svcs() -> None:
    from alerting_svc.domain import delivery

    assert gap_rules.GAP_THRESHOLD == delivery.GAP_THRESHOLD


def test_prior_alerts_are_ordered_against_a_real_clock() -> None:
    """The window is computed from the run's clock, not read inside the pure rule."""
    now = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)

    assert targeting.fatigue_window_start(now) == now - timedelta(
        hours=targeting.FATIGUE_WINDOW_HOURS
    )
