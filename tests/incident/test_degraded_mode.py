"""Working with the agents switched off.

The build brief is explicit that this is required, not optional, and the reason is in the
last line of that section: never let a dispatcher believe AI ranking is on when it is off.

So these tests check two different things and both matter. The queue must still be usable
and ordered sensibly - and it must say, unmistakably, which ordering produced it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from incident_svc.adapters.channels import sms, ussd
from incident_svc.domain import dedup, triage

pytestmark = pytest.mark.asyncio(loop_scope="session")


def at(minutes: float) -> datetime:
    """A timestamp `minutes` after a fixed origin."""
    return datetime(2026, 8, 28, 12, 0, tzinfo=UTC) + timedelta(minutes=minutes)


# --------------------------------------------------------------------------------------
# The triage rule ranks a real queue sensibly
# --------------------------------------------------------------------------------------


def test_two_hundred_reports_produce_a_usable_ranked_queue() -> None:
    """The case the brief names, as a pure function over the same inputs the API uses."""
    incidents = [
        triage.TriageInput(
            incident_type=("FLOOD", "TRAPPED", "SUPPLIES_NEEDED", "MEDICAL")[index % 4],
            people_at_risk=index % 30,
            minutes_since_reported=float(index % 90),
            has_over_70=index % 7 == 0,
            has_under_5=index % 5 == 0,
        )
        for index in range(200)
    ]

    scored = [triage.score(candidate) for candidate in incidents]
    ranked = sorted(scored, key=lambda result: -result.score)

    assert len(ranked) == 200
    assert ranked[0].score >= ranked[-1].score
    # A ranking where everything ties is not a ranking.
    assert len({round(result.score, 3) for result in scored}) > 20


def test_a_trapped_person_outranks_a_supplies_request_all_else_equal() -> None:
    """The ordering has to be defensible, not merely stable."""
    trapped = triage.score(
        triage.TriageInput("TRAPPED", people_at_risk=2, minutes_since_reported=0)
    )
    shelter = triage.score(
        triage.TriageInput("SUPPLIES_NEEDED", people_at_risk=2, minutes_since_reported=0)
    )

    assert trapped.score > shelter.score


def test_more_people_at_risk_outranks_fewer() -> None:
    many = triage.score(triage.TriageInput("FLOOD", 40, 0))
    few = triage.score(triage.TriageInput("FLOOD", 2, 0))

    assert many.score > few.score


def test_a_vulnerable_household_outranks_an_otherwise_identical_one() -> None:
    vulnerable = triage.score(
        triage.TriageInput("FLOOD", 3, 0, has_over_70=True, has_mobility_impairment=True)
    )
    ordinary = triage.score(triage.TriageInput("FLOOD", 3, 0))

    assert vulnerable.score > ordinary.score


def test_waiting_longer_raises_the_score() -> None:
    """Otherwise a queue under load starves whatever arrived first."""
    old = triage.score(triage.TriageInput("FLOOD", 3, minutes_since_reported=120))
    new = triage.score(triage.TriageInput("FLOOD", 3, minutes_since_reported=0))

    assert old.score > new.score


def test_the_score_is_bounded_so_two_queues_stay_comparable() -> None:
    extreme = triage.score(
        triage.TriageInput(
            "MEDICAL",
            people_at_risk=100_000,
            minutes_since_reported=100_000,
            has_over_70=True,
            has_under_5=True,
            has_mobility_impairment=True,
        )
    )
    empty = triage.score(triage.TriageInput("OTHER", 0, 0))

    assert 0.0 <= empty.score <= extreme.score <= 1.0


def test_an_unknown_incident_type_lands_mid_table() -> None:
    """Bottom would bury a real emergency described in words we did not anticipate.

    Top would let any unrecognised string jump the queue.
    """
    unknown = triage.type_weight("SOMETHING_NOBODY_ANTICIPATED")

    assert triage.type_weight("INFRASTRUCTURE") < unknown
    assert unknown < triage.type_weight("TRAPPED")


def test_every_score_carries_the_factors_that_produced_it() -> None:
    """A ranking a dispatcher cannot interrogate gets over-trusted or ignored."""
    result = triage.score(triage.TriageInput("FLOOD", 10, 30))

    assert set(result.factors) >= {"people_at_risk", "vulnerability", "incident_type", "age"}
    assert result.factors["weights"]["people_at_risk"] == triage.WEIGHT_PEOPLE_AT_RISK
    assert result.model_version == "rule-v1"


def test_the_rule_result_never_claims_to_be_assisted() -> None:
    """The flag is what the console reads to decide whether to show the banner."""
    assert triage.score(triage.TriageInput("FLOOD", 1, 0)).assisted is False


# --------------------------------------------------------------------------------------
# Deterministic dedup flags, never merges
# --------------------------------------------------------------------------------------


def _candidate(
    identifier: str,
    *,
    division: str = "LK-21-01-001",
    incident_type: str = "FLOOD",
    lon: float | None = 80.6337,
    lat: float | None = 7.2906,
    minutes: float = 0,
) -> dedup.Candidate:
    return dedup.Candidate(
        id=identifier,
        gn_division_code=division,
        incident_type=incident_type,
        lon=lon,
        lat=lat,
        occurred_at=at(minutes),
    )


def test_the_documented_rule_flags_a_nearby_recent_report_of_the_same_type() -> None:
    """Same division, same type, within 300m, within 20 minutes."""
    flagged = dedup.is_candidate(_candidate("new", minutes=10), _candidate("existing", minutes=0))

    assert flagged is not None
    assert flagged.existing_id == "existing"


def test_a_report_outside_the_time_window_is_not_a_candidate() -> None:
    assert dedup.is_candidate(_candidate("new", minutes=25), _candidate("old")) is None


def test_a_report_beyond_three_hundred_metres_is_not_a_candidate() -> None:
    """0.01 degrees of longitude is roughly a kilometre here."""
    far = _candidate("far", lon=80.6437)

    assert dedup.is_candidate(_candidate("new"), far) is None


def test_a_different_incident_type_in_the_same_place_is_not_a_candidate() -> None:
    """A fire and a flood at one address are two emergencies, not one."""
    other = _candidate("other", incident_type="FIRE")

    assert dedup.is_candidate(_candidate("new"), other) is None


def test_a_different_division_is_not_a_candidate() -> None:
    other = _candidate("other", division="LK-21-01-002")

    assert dedup.is_candidate(_candidate("new"), other) is None


def test_a_report_with_no_location_can_still_be_a_candidate() -> None:
    """SMS carries no coordinates, and those are the likeliest duplicates of an app report."""
    flagged = dedup.is_candidate(
        _candidate("sms", lon=None, lat=None, minutes=2), _candidate("app")
    )

    assert flagged is not None
    assert flagged.distance_m is None


def test_candidates_come_back_closest_in_time_first() -> None:
    """A dispatcher wants the cluster, with the most likely match at the top."""
    found = dedup.find_candidates(
        _candidate("new", minutes=10),
        [_candidate("far", minutes=0), _candidate("near", minutes=9)],
    )

    assert [candidate.existing_id for candidate in found] == ["near", "far"]


def test_a_flag_explains_itself_in_terms_a_human_can_check() -> None:
    flagged = dedup.is_candidate(_candidate("new", minutes=5), _candidate("existing"))

    assert flagged is not None
    assert "minutes apart" in flagged.reason
    assert dedup.METHOD in flagged.reason


# --------------------------------------------------------------------------------------
# Channels keep working with no agent anywhere
# --------------------------------------------------------------------------------------


def test_an_unparseable_sms_still_becomes_a_report() -> None:
    """The messages that do not match the syntax are the ones that matter most."""
    intake = sms.parse(
        body="please help the water is coming into the house",
        sender_msisdn_hash="hash",
        correlation_id="c",
    )

    assert intake.raw_text
    assert intake.channel == "SMS"


def test_free_text_in_sinhala_is_recognised_as_sinhala() -> None:
    intake = sms.parse(body="ගංවතුර උදව්", sender_msisdn_hash="h", correlation_id="c")

    assert intake.reported_language == "si"
    assert intake.incident_type == "FLOOD"


def test_free_text_in_tamil_is_recognised_as_tamil() -> None:
    intake = sms.parse(body="வெள்ளம் உதவி", sender_msisdn_hash="h", correlation_id="c")

    assert intake.reported_language == "ta"
    assert intake.incident_type == "FLOOD"


def test_the_documented_sms_syntax_still_works() -> None:
    intake = sms.parse(
        body="HELP LANDSLIDE hillside behind the school",
        sender_msisdn_hash="h",
        correlation_id="c",
    )

    assert intake.incident_type == "LANDSLIDE"
    assert "hillside" in (intake.raw_text or "")


def test_help_followed_by_a_non_type_is_treated_as_free_text() -> None:
    """`HELP` is someone asking for help, not a failed parse."""
    intake = sms.parse(body="HELP please", sender_msisdn_hash="h", correlation_id="c")

    assert intake.raw_text is not None
    assert "please" in intake.raw_text


@pytest.mark.parametrize("step", list(ussd.SCREENS))
def test_every_ussd_screen_fits_in_one_message_in_every_language(step: ussd.Step) -> None:
    """A screen that overflows is truncated by the network and loses its last option."""
    for language, body in ussd.SCREENS[step].items():
        assert len(body) <= ussd.MAX_SCREEN_CHARS, f"{step}/{language} is {len(body)} chars"


def test_the_ussd_menu_is_at_most_four_levels_deep() -> None:
    assert len(ussd.SCREENS) <= 4


def test_a_ussd_session_produces_a_report_without_any_agent() -> None:
    """Language, type, people, confirm - the shortest path that still means something."""
    turn = ussd.start()
    for choice in ("3", "1", "2", "1"):
        turn = ussd.advance(turn.state, choice, sender_msisdn_hash="hash", correlation_id="c")

    assert turn.finished
    assert turn.intake is not None
    assert turn.intake.incident_type == "FLOOD"
    assert turn.intake.people_at_risk == 4


def test_an_invalid_keypress_reshows_the_screen_rather_than_ending_the_session() -> None:
    """Ending it would mean starting over on a phone that may not reconnect."""
    turn = ussd.advance(ussd.SessionState(), "9", sender_msisdn_hash="h", correlation_id="c")

    assert not turn.finished
    assert turn.state.step is ussd.Step.LANGUAGE


def test_declining_the_confirmation_sends_nothing() -> None:
    turn = ussd.start()
    for choice in ("3", "1", "2", "2"):
        turn = ussd.advance(turn.state, choice, sender_msisdn_hash="h", correlation_id="c")

    assert turn.finished
    assert turn.intake is None
