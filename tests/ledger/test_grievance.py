"""Grievances and the citizen confirmation loop.

The "NO" reply is the highest-signal input this platform receives: it costs the sender one
message and tells us something no dashboard can, that the money did not arrive. So most of
these tests are about that reply being read correctly, and about the three answers being
kept distinct — confirmed, disputed, and *silent*, which is not the same as either.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ledger_svc.domain.grievance import (
    CONFIRMATION_WINDOW_DAYS,
    ConfirmationReply,
    GrievanceRefused,
    assert_resolution_is_trilingual,
    assert_transition,
    blocks_release,
    from_confirmation_reply,
    lapse_unconfirmed,
    parse_confirmation,
    public_ref,
    raise_grievance,
    sla_due,
)
from sarana_shared.domain.ids import uuid7

HOUSEHOLD = uuid7()
DISBURSEMENT = uuid7()
NOW = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)


# --------------------------------------------------------------------------------------
# Reading the reply
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("body", ["YES", "yes", " Yes ", "Y", "ok", "OK", "1", "yes."])
def test_a_yes_in_english_is_understood(body: str) -> None:
    assert parse_confirmation(body) is ConfirmationReply.YES


@pytest.mark.parametrize("body", ["NO", "no", " No ", "N", "2", "no!"])
def test_a_no_in_english_is_understood(body: str) -> None:
    assert parse_confirmation(body) is ConfirmationReply.NO


@pytest.mark.parametrize("body", ["ඔව්", "ஆம்", "சரி"])
def test_a_yes_in_sinhala_or_tamil_is_understood(body: str) -> None:
    """A citizen replying in their own language must not have their answer discarded."""
    assert parse_confirmation(body) is ConfirmationReply.YES


@pytest.mark.parametrize("body", ["නැත", "නෑ", "இல்லை"])
def test_a_no_in_sinhala_or_tamil_is_understood(body: str) -> None:
    assert parse_confirmation(body) is ConfirmationReply.NO


def test_a_no_inside_a_sentence_still_counts() -> None:
    """People do not reply with single words. "no it did not come" is a NO."""
    assert parse_confirmation("no it did not come") is ConfirmationReply.NO


def test_an_unrecognised_reply_is_neither() -> None:
    """The honest answer, and the one that goes to a human.

    Guessing YES closes a case nobody confirmed. Guessing NO puts a false dispute on a
    household's record and wastes an officer's day.
    """
    assert parse_confirmation("who is this") is ConfirmationReply.UNRECOGNISED
    assert parse_confirmation("") is ConfirmationReply.UNRECOGNISED


# --------------------------------------------------------------------------------------
# The reply becomes a grievance
# --------------------------------------------------------------------------------------


def test_a_no_reply_raises_a_grievance_automatically() -> None:
    """The case the brief names as the primary input, not an afterthought."""
    grievance = from_confirmation_reply(
        household_id=HOUSEHOLD, disbursement_id=DISBURSEMENT, body="NO", raised_at=NOW
    )

    assert grievance is not None
    assert grievance.subject_type == "DISBURSEMENT"
    assert grievance.subject_id == DISBURSEMENT
    assert grievance.channel == "SMS"


def test_a_yes_reply_raises_nothing() -> None:
    assert (
        from_confirmation_reply(household_id=HOUSEHOLD, disbursement_id=DISBURSEMENT, body="YES")
        is None
    )


def test_an_unrecognised_reply_raises_nothing() -> None:
    """It goes to a person instead. Raising a dispute nobody filed is its own harm."""
    assert (
        from_confirmation_reply(
            household_id=HOUSEHOLD, disbursement_id=DISBURSEMENT, body="call me"
        )
        is None
    )


def test_an_automatic_grievance_is_described_in_all_three_languages() -> None:
    """The household will be written back to, in the language they used."""
    grievance = from_confirmation_reply(
        household_id=HOUSEHOLD, disbursement_id=DISBURSEMENT, body="NO"
    )

    assert grievance is not None
    assert set(grievance.description) == {"si", "ta", "en"}
    assert all(text.strip() for text in grievance.description.values())


# --------------------------------------------------------------------------------------
# Silence is not a failure
# --------------------------------------------------------------------------------------


def test_no_reply_inside_the_window_concludes_nothing() -> None:
    released = NOW - timedelta(days=CONFIRMATION_WINDOW_DAYS - 1)

    assert lapse_unconfirmed(disbursement_id=DISBURSEMENT, released_at=released, now=NOW) is None


def test_no_reply_after_the_window_is_unconfirmed_not_failed() -> None:
    """The distinction the brief insists on.

    Silence means a dead phone, an SMS that never arrived, or a message nobody understood.
    None of those is evidence the money is missing, and reporting them as failures would
    overstate one problem while hiding another.
    """
    released = NOW - timedelta(days=CONFIRMATION_WINDOW_DAYS + 1)

    outcome = lapse_unconfirmed(disbursement_id=DISBURSEMENT, released_at=released, now=NOW)

    assert outcome is not None
    assert outcome.unconfirmed
    assert not outcome.confirmed
    assert outcome.grievance is None
    assert "not as failed" in outcome.summary


# --------------------------------------------------------------------------------------
# Raising one directly
# --------------------------------------------------------------------------------------


def a_description() -> dict[str, str]:
    return {"si": "වැරදියි", "ta": "தவறு", "en": "The assessment is wrong"}


def test_a_household_can_dispute_an_assessment() -> None:
    grievance = raise_grievance(
        household_id=HOUSEHOLD,
        subject_type="ASSESSMENT",
        subject_id=uuid7(),
        channel="APP",
        description=a_description(),
        raised_at=NOW,
    )

    assert grievance.status == "RECEIVED"
    assert grievance.public_ref.startswith("GRV-")


def test_an_empty_complaint_is_refused() -> None:
    """A grievance with nothing in it cannot be investigated, and the citizen should be
    told so rather than left waiting on a case nobody can action."""
    with pytest.raises(GrievanceRefused, match="must say what is wrong"):
        raise_grievance(
            household_id=HOUSEHOLD,
            subject_type="ASSESSMENT",
            subject_id=None,
            channel="APP",
            description={"si": "  ", "ta": "", "en": ""},
        )


def test_an_unknown_channel_is_refused_with_a_usable_message() -> None:
    with pytest.raises(GrievanceRefused, match="not a channel"):
        raise_grievance(
            household_id=HOUSEHOLD,
            subject_type="ASSESSMENT",
            subject_id=None,
            channel="CARRIER_PIGEON",
            description=a_description(),
        )


def test_an_unknown_subject_is_refused() -> None:
    with pytest.raises(GrievanceRefused, match="not something a household can dispute"):
        raise_grievance(
            household_id=HOUSEHOLD,
            subject_type="THE_WEATHER",
            subject_id=None,
            channel="APP",
            description=a_description(),
        )


# --------------------------------------------------------------------------------------
# References and the SLA clock
# --------------------------------------------------------------------------------------


def test_a_public_reference_avoids_the_characters_people_mishear() -> None:
    """Read aloud over a phone and written on paper, so no I, L, O or U."""
    references = "".join(public_ref(NOW).split("-")[2] for _ in range(200))

    assert not set(references) & set("ILOU")


def test_references_do_not_collide() -> None:
    assert len({public_ref(NOW) for _ in range(500)}) == 500


def test_the_sla_clock_starts_when_the_grievance_was_raised() -> None:
    """Not when an officer got round to it. The household has been waiting since they
    complained."""
    grievance = raise_grievance(
        household_id=HOUSEHOLD,
        subject_type="ASSESSMENT",
        subject_id=None,
        channel="APP",
        description=a_description(),
        raised_at=NOW,
    )

    assert grievance.sla_due_at == sla_due(NOW, "ASSESSMENT")
    assert grievance.sla_due_at > grievance.raised_at


def test_a_disputed_payment_gets_a_shorter_sla_than_a_disputed_assessment() -> None:
    """The household says money they were told about did not arrive.

    Every day of that is a day they are going without it.
    """
    assert sla_due(NOW, "DISBURSEMENT") < sla_due(NOW, "ASSESSMENT")


# --------------------------------------------------------------------------------------
# What blocks a release
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["RECEIVED", "ACKNOWLEDGED", "UNDER_REVIEW", "ESCALATED"])
def test_an_undispositioned_grievance_blocks_its_own_release(status: str) -> None:
    assert blocks_release(status)


def test_an_escalated_grievance_still_blocks() -> None:
    """Escalated means passed upward, not answered.

    Paying while the dispute is still travelling settles the question in one direction
    without anybody having decided it.
    """
    assert blocks_release("ESCALATED")


@pytest.mark.parametrize("status", ["RESOLVED", "REJECTED"])
def test_a_dispositioned_grievance_does_not_block(status: str) -> None:
    assert not blocks_release(status)


# --------------------------------------------------------------------------------------
# Moving a grievance along
# --------------------------------------------------------------------------------------


def test_an_officer_may_acknowledge_review_and_escalate_in_any_order() -> None:
    """Deliberately permissive between open states: the record should reflect what
    actually happened, not a workflow nobody follows."""
    assert_transition("RECEIVED", "UNDER_REVIEW")
    assert_transition("RECEIVED", "ESCALATED")
    assert_transition("UNDER_REVIEW", "ACKNOWLEDGED")


@pytest.mark.parametrize("current", ["RESOLVED", "REJECTED"])
def test_a_dispositioned_grievance_cannot_be_reopened(current: str) -> None:
    """Otherwise a resolution could be quietly withdrawn.

    A new complaint is a new grievance, so the household keeps both the original answer
    and the new dispute.
    """
    with pytest.raises(GrievanceRefused, match="cannot be reopened"):
        assert_transition(current, "UNDER_REVIEW")


def test_an_unknown_status_is_refused() -> None:
    with pytest.raises(GrievanceRefused, match="not a grievance status"):
        assert_transition("RECEIVED", "FORGOTTEN")


def test_a_resolution_must_be_written_in_all_three_languages() -> None:
    """It is sent to the citizen. One language would reach some of them."""
    with pytest.raises(GrievanceRefused, match="all three languages"):
        assert_resolution_is_trilingual({"en": "We have corrected the assessment."})


def test_a_trilingual_resolution_is_accepted() -> None:
    assert_resolution_is_trilingual({"si": "නිවැරදි කළා", "ta": "சரிசெய்யப்பட்டது", "en": "Corrected"})
