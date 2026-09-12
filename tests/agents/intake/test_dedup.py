"""Duplicate detection, and the asymmetry that decides every threshold in it.

Build file 15 says the false-merge case matters more than the dedup case, and this file is
written to that order. A duplicate incident costs a dispatcher ten seconds. A false merge
means a household reported, was folded into another family's incident, one team went to that
address, and the family who reported waited for someone who never came - and nobody noticed,
because from the outside the queue looked short.

So the tests that matter most here are the ones asserting the agent did **not** merge:
on a low-confidence yes, on an unavailable provider, on an unparseable answer, on a
confident no. Every one of those produces two incidents and a flagged pair.
"""

from __future__ import annotations

import pytest

from agent_svc.agents.intake import dedup
from tests.agents.intake.conftest import (
    NOW,
    OTHER_DIVISION,
    BrokenCall,
    RecordingCall,
    neighbour,
)

SINHALA = "ගම්පොල අංක 12 නිවස කඩා වැටී ඇත. ළමයි දෙන්නෙක් ඇතුළේ."
TAMIL = "கம்பளை 12 ஆம் இலக்க வீடு இடிந்தது. இரண்டு குழந்தைகள் உள்ளே."
ENGLISH = "House number 12 in Gampola collapsed, two children inside"


def yes(confidence: float) -> RecordingCall:
    return RecordingCall(
        f'{{"same_incident": true, "confidence": {confidence}, "reasoning": "same house"}}'
    )


def no(confidence: float = 0.95) -> RecordingCall:
    return RecordingCall(
        f'{{"same_incident": false, "confidence": {confidence}, '
        f'"reasoning": "different households"}}'
    )


# ---------------------------------------------------------------------------------------
# The bands
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("similarity", "band"),
    [
        (0.95, "auto_link"),
        (0.90, "auto_link"),
        (0.85, "ambiguous"),
        (0.72, "ambiguous"),
        (0.71, "separate"),
        (0.10, "separate"),
    ],
)
def test_similarity_falls_into_the_expected_band(similarity: float, band: str) -> None:
    assert dedup.band_of(similarity) == band


async def test_a_very_similar_pair_links_without_asking_a_model() -> None:
    """Above the auto-link threshold the texts say substantially the same thing about the
    same place in the same window, and a model call buys nothing."""
    call = yes(0.99)

    decision = await dedup.decide(
        incoming_text=ENGLISH,
        incoming_original=SINHALA,
        occurred_at=NOW,
        neighbours=[neighbour("rep-2", similarity=0.94)],
        call=call,
    )

    assert decision.link_to_incident == "inc-existing"
    assert call.prompts == []


async def test_a_dissimilar_pair_is_never_considered() -> None:
    call = yes(0.99)

    decision = await dedup.decide(
        incoming_text=ENGLISH,
        incoming_original=SINHALA,
        occurred_at=NOW,
        neighbours=[neighbour("rep-2", similarity=0.40)],
        call=call,
    )

    assert not decision.merged
    assert decision.verdicts == []
    assert call.prompts == []


# ---------------------------------------------------------------------------------------
# The two cases build file 15 names
# ---------------------------------------------------------------------------------------


async def test_a_tamil_voice_note_and_a_sinhala_sms_about_one_house_are_linked() -> None:
    """Required by build file 15.

    Multilingual embeddings mean an SMS in Tamil and a voice note in Sinhala about the same
    collapsed house can match, and the adjudicator reads both in their original languages -
    a translation loses the street number that makes them the same house.
    """
    call = yes(0.93)

    decision = await dedup.decide(
        incoming_text=ENGLISH,
        incoming_original=SINHALA,
        occurred_at=NOW,
        neighbours=[neighbour("rep-2", similarity=0.80, text_original=TAMIL, text_en=ENGLISH)],
        call=call,
    )

    assert decision.link_to_incident == "inc-existing"
    assert TAMIL in call.prompts[0]
    assert SINHALA in call.prompts[0]


async def test_two_different_flood_reports_in_one_division_are_not_merged() -> None:
    """Required by build file 15, and the case that matters more than the one above.

    Similar wording from one village is the normal case during a flood. Merging on it means
    the second household is never visited.
    """
    decision = await dedup.decide(
        incoming_text="Water entering our house on Temple Road",
        incoming_original="Water entering our house on Temple Road",
        occurred_at=NOW,
        neighbours=[
            neighbour(
                "rep-2",
                similarity=0.79,
                incident_type="FLOOD",
                text_en="Water entering our house on Station Road",
            )
        ],
        call=no(),
    )

    assert not decision.merged


# ---------------------------------------------------------------------------------------
# Every uncertain path lands on "separate, and tell a person"
# ---------------------------------------------------------------------------------------


async def test_a_low_confidence_yes_does_not_merge() -> None:
    """The adjudicator leaning towards "same" is not enough to fold two households' reports
    together. It is enough to put the pair in front of somebody."""
    decision = await dedup.decide(
        incoming_text=ENGLISH,
        incoming_original=SINHALA,
        occurred_at=NOW,
        neighbours=[neighbour("rep-2", similarity=0.80)],
        call=yes(0.60),
    )

    assert not decision.merged
    assert decision.flagged_pairs == ["rep-2"]


async def test_an_unavailable_model_does_not_merge() -> None:
    decision = await dedup.decide(
        incoming_text=ENGLISH,
        incoming_original=SINHALA,
        occurred_at=NOW,
        neighbours=[neighbour("rep-2", similarity=0.85)],
        call=BrokenCall(),
    )

    assert not decision.merged
    assert decision.flagged_pairs == ["rep-2"]


async def test_no_model_at_all_does_not_merge_the_ambiguous_band() -> None:
    """The degraded path. Vector similarity alone never merges anything in the band it
    cannot resolve."""
    decision = await dedup.decide(
        incoming_text=ENGLISH,
        incoming_original=SINHALA,
        occurred_at=NOW,
        neighbours=[neighbour("rep-2", similarity=0.85)],
        call=None,
    )

    assert not decision.merged
    assert decision.flagged_pairs == ["rep-2"]
    assert decision.verdicts[0].method == dedup.METHOD_VECTOR


async def test_an_unparseable_adjudication_does_not_merge() -> None:
    decision = await dedup.decide(
        incoming_text=ENGLISH,
        incoming_original=SINHALA,
        occurred_at=NOW,
        neighbours=[neighbour("rep-2", similarity=0.85)],
        call=RecordingCall("probably the same house, yes"),
    )

    assert not decision.merged
    assert decision.flagged_pairs == ["rep-2"]


async def test_a_confident_no_is_not_flagged() -> None:
    """A confident "different" is a real answer. Flagging it would fill the queue with pairs
    somebody already decided, and a queue people learn to skim is worse than none."""
    decision = await dedup.decide(
        incoming_text=ENGLISH,
        incoming_original=SINHALA,
        occurred_at=NOW,
        neighbours=[neighbour("rep-2", similarity=0.80)],
        call=no(0.95),
    )

    assert not decision.merged
    assert decision.flagged_pairs == []


async def test_a_report_attaches_to_at_most_one_incident() -> None:
    """Linking to two would merge those two incidents by the back door, decided by nobody."""
    decision = await dedup.decide(
        incoming_text=ENGLISH,
        incoming_original=SINHALA,
        occurred_at=NOW,
        neighbours=[
            neighbour("rep-2", similarity=0.95, incident_id="inc-a"),
            neighbour("rep-3", similarity=0.93, incident_id="inc-b"),
        ],
        call=None,
    )

    assert decision.link_to_incident == "inc-a"


async def test_a_neighbour_with_no_incident_cannot_be_linked_to() -> None:
    """A report that has not yet become an incident is nothing to attach to. Without this
    the link would be None and the report would silently create its own anyway - which is
    correct, and this pins it."""
    decision = await dedup.decide(
        incoming_text=ENGLISH,
        incoming_original=SINHALA,
        occurred_at=NOW,
        neighbours=[neighbour("rep-2", similarity=0.95, incident_id=None)],
        call=None,
    )

    assert not decision.merged


# ---------------------------------------------------------------------------------------
# The stats, which are only honest as a pair
# ---------------------------------------------------------------------------------------


def test_both_rates_are_reported_together() -> None:
    """A duplicate rate alone always improves by merging harder, which is exactly the
    behaviour that must not be rewarded."""
    stats = dedup.DedupStats(pairs=100, linked=30, false_merges=2, missed_duplicates=5)

    assert stats.duplicate_rate == 0.05
    assert stats.false_merge_rate == 0.02
    assert "false merges" in stats.as_sentence()


def test_the_merge_bar_is_above_the_platforms_ordinary_review_threshold() -> None:
    """This is the one decision in the agent whose wrong answer is invisible afterwards, so
    it is held to a higher bar than everything else."""
    from agent_svc.agents.intake.graph import REVIEW_THRESHOLD

    assert dedup.MERGE_CONFIDENCE > REVIEW_THRESHOLD


def test_the_prompt_tells_the_adjudicator_which_way_to_err() -> None:
    """The instruction is not the safety property - the code is - but a prompt that did not
    say this would be one working against the thresholds around it."""
    assert "unsure" in dedup.ADJUDICATION_INSTRUCTIONS
    assert "false" in dedup.ADJUDICATION_INSTRUCTIONS


async def test_the_prompt_carries_how_far_apart_the_reports_are() -> None:
    """Two reports twenty minutes apart from one village are more likely to be one event
    than two reports eighty minutes apart, and the adjudicator cannot see that without
    being told."""
    call = no()

    await dedup.decide(
        incoming_text=ENGLISH,
        incoming_original=SINHALA,
        occurred_at=NOW,
        neighbours=[neighbour("rep-2", similarity=0.80, minutes_ago=37)],
        call=call,
    )

    assert "minutes apart: 37" in call.prompts[0]


def test_the_search_window_bounds_the_candidate_query() -> None:
    start = dedup.window_start(NOW)

    assert (NOW - start).total_seconds() / 60 == dedup.WINDOW_MINUTES


async def test_a_candidate_in_another_division_is_still_judged_on_its_similarity() -> None:
    """The division filter belongs to the query, not to this function.

    Putting it here as well would hide a bug in the query behind a second check that
    silently did the same job.
    """
    decision = await dedup.decide(
        incoming_text=ENGLISH,
        incoming_original=SINHALA,
        occurred_at=NOW,
        neighbours=[neighbour("rep-2", similarity=0.95, division=OTHER_DIVISION)],
        call=None,
    )

    assert decision.merged
