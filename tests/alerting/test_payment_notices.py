"""The consumer that tells a household what happened to their money.

Two gaps closed here, and the first is older than the second.

**The confirmation loop had never run.** `ledger-svc` publishes
`sarana.aid.disbursement.released` with a comment saying "alerting-svc listens for this and
sends the confirmation SMS", and alerting-svc consumed nothing at all. So the YES/NO reply
— which the ledger calls the cheapest and highest-signal error detector in the platform,
and the only independent evidence that money reached anybody — was never asked for.

**A reversed payment told nobody.** The compensating entry, the grievance and the reopened
entitlement were all written; the household stayed at home believing they had been paid.

The tests below are mostly about what the consumer does when it *cannot* send, because
those are the paths that decide whether a silent failure looks like a quiet day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

import pytest

from alerting_svc.adapters.channels.base import DeliveryStatus, Message, Receipt
from alerting_svc.adapters.households import (
    DirectoryUnavailable,
    HouseholdContact,
    NullDirectory,
)
from alerting_svc.domain import payment_messages
from alerting_svc.workers import payment_notices
from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.reversal_reasons import REASON_TEXT, ReversalReason
from sarana_shared.events import catalogue
from sarana_shared.events.envelope import EventEnvelope

HOUSEHOLD = uuid7()


@dataclass
class StubDirectory:
    """A household directory that answers however the test needs."""

    contact_value: HouseholdContact | None = None
    raises: Exception | None = None
    asked: list[str] = field(default_factory=list)

    async def contact(self, household_id: UUID | str) -> HouseholdContact | None:
        self.asked.append(str(household_id))
        if self.raises is not None:
            raise self.raises
        return self.contact_value

    async def aclose(self) -> None:
        return None


@dataclass
class StubChannel:
    """An SMS channel that records what it was asked to send."""

    name: str = "SMS"
    simulated: bool = True
    status: DeliveryStatus = DeliveryStatus.SENT
    sent: list[Message] = field(default_factory=list)

    async def send(self, messages: list[Message]) -> list[Receipt]:
        self.sent.extend(messages)
        return [
            Receipt(
                target_ref_hash=message.target.target_ref_hash,
                channel=self.name,
                language=message.language,
                status=self.status,
                simulated=True,
            )
            for message in messages
        ]


def a_contact(language: str = "si", *, reachable: bool = True) -> HouseholdContact:
    return HouseholdContact(
        household_id=str(HOUSEHOLD),
        recipient_ref_hash="c" * 64 if reachable else None,
        preferred_language=language,
        gn_division_code="LK-21-01-001",
    )


def released_event(**overrides: object) -> EventEnvelope:
    payload: dict[str, object] = {
        "disbursement_id": str(uuid7()),
        "entitlement_id": str(uuid7()),
        "household_id": str(HOUSEHOLD),
        "amount_lkr_cents": 47_500_00,
        "released_by": str(uuid7()),
        "payment_rail": "BANK_TRANSFER",
        "payment_ref": "MOCK-BANK_TRANSFER-000000000001",
        "seq": 1,
        "entry_hash": "a" * 64,
        "confirmation_required": True,
        "simulated": True,
        **overrides,
    }
    return EventEnvelope(
        event_type=catalogue.AID_DISBURSEMENT_RELEASED,
        producer="ledger-svc",
        payload=payload,
    )


def reversed_event(**overrides: object) -> EventEnvelope:
    payload: dict[str, object] = {
        "reversal_id": str(uuid7()),
        "disbursement_id": str(uuid7()),
        "entitlement_id": str(uuid7()),
        "household_id": str(HOUSEHOLD),
        "amount_lkr_cents": 47_500_00,
        "reason": "ACCOUNT_CLOSED",
        "needs_new_bank_details": True,
        "grievance_id": str(uuid7()),
        "grievance_ref": "GRV-A1B2C3",
        "seq": 1,
        "entry_hash": "b" * 64,
        "simulated": True,
        **overrides,
    }
    return EventEnvelope(
        event_type=catalogue.AID_DISBURSEMENT_REVERSED,
        producer="ledger-svc",
        payload=payload,
    )


# --------------------------------------------------------------------------------------
# The confirmation message
# --------------------------------------------------------------------------------------


async def test_a_released_payment_asks_the_household_to_confirm() -> None:
    """The message that makes the whole confirmation loop possible."""
    directory = StubDirectory(contact_value=a_contact("en"))
    channel = StubChannel()

    result = await payment_notices.handle(released_event(), directory=directory, channel=channel)

    assert result.sent
    assert len(channel.sent) == 1
    body = channel.sent[0].body
    assert "47,500" in body
    assert "YES" in body and "NO" in body


async def test_the_message_names_the_amount_and_the_reference() -> None:
    """ "Did you get 47,500 rupees?" is answerable; "did you get your payment?" is not."""
    directory = StubDirectory(contact_value=a_contact("en"))
    channel = StubChannel()

    await payment_notices.handle(released_event(), directory=directory, channel=channel)

    body = channel.sent[0].body
    assert "47,500" in body
    assert "MOCK-BANK_TRANSFER-000000000001" in body


async def test_the_message_is_in_the_households_own_language() -> None:
    """The whole point of `preferred_language` is that somebody recorded it."""
    for language in ("si", "ta", "en"):
        directory = StubDirectory(contact_value=a_contact(language))
        channel = StubChannel()

        await payment_notices.handle(released_event(), directory=directory, channel=channel)

        assert channel.sent[0].language == language
        expected = payment_messages.confirmation_message(
            amount_lkr_cents=47_500_00,
            payment_ref="MOCK-BANK_TRANSFER-000000000001",
            language=language,
        )
        assert channel.sent[0].body == expected


async def test_a_release_that_needs_no_confirmation_sends_nothing() -> None:
    """Cash handed over against a signature is already confirmed by the signature."""
    directory = StubDirectory(contact_value=a_contact())
    channel = StubChannel()

    result = await payment_notices.handle(
        released_event(confirmation_required=False), directory=directory, channel=channel
    )

    assert not result.sent
    assert channel.sent == []


# --------------------------------------------------------------------------------------
# The reversal message
# --------------------------------------------------------------------------------------


async def test_a_reversed_payment_tells_the_household_what_to_do() -> None:
    """Not "payment failed". The specific remedy, in their language, with the case ref."""
    directory = StubDirectory(contact_value=a_contact("en"))
    channel = StubChannel()

    result = await payment_notices.handle(reversed_event(), directory=directory, channel=channel)

    assert result.sent
    body = channel.sent[0].body
    assert "47,500" in body
    assert REASON_TEXT[ReversalReason.ACCOUNT_CLOSED]["en"] in body
    assert "GRV-A1B2C3" in body


async def test_the_reversal_message_never_shows_a_status_code() -> None:
    """A household must not be sent the string `ACCOUNT_CLOSED`.

    It is the laziest possible rendering and it is exactly what happens if somebody
    interpolates the reason instead of looking it up.
    """
    for reason in ReversalReason:
        directory = StubDirectory(contact_value=a_contact("en"))
        channel = StubChannel()

        await payment_notices.handle(
            reversed_event(reason=reason.value), directory=directory, channel=channel
        )

        assert reason.value not in channel.sent[0].body


async def test_an_unrecognised_reason_still_says_something_true() -> None:
    """An older build meeting a newer reason must not send an empty explanation.

    The household still needs to know the money came back; saying the reason is being
    investigated is unspecific and true, which beats silence.
    """
    directory = StubDirectory(contact_value=a_contact("en"))
    channel = StubChannel()

    result = await payment_notices.handle(
        reversed_event(reason="SOMETHING_NEW"), directory=directory, channel=channel
    )

    assert result.sent
    assert "returned" in channel.sent[0].body.lower()


# --------------------------------------------------------------------------------------
# When it cannot send
# --------------------------------------------------------------------------------------


async def test_a_household_with_no_phone_is_a_gap_not_a_retry() -> None:
    """Not everybody has a phone.

    Acknowledged, because redelivering the event will not give them one. What it needs is
    an officer, and the log line says so.
    """
    directory = StubDirectory(contact_value=a_contact(reachable=False))
    channel = StubChannel()

    result = await payment_notices.handle(released_event(), directory=directory, channel=channel)

    assert not result.sent
    assert result.acknowledged
    assert channel.sent == []


async def test_an_unknown_household_is_a_gap_not_a_retry() -> None:
    """A household the directory does not have is a fact, not an outage."""
    directory = StubDirectory(contact_value=None)
    channel = StubChannel()

    result = await payment_notices.handle(released_event(), directory=directory, channel=channel)

    assert not result.sent
    assert result.acknowledged


async def test_a_directory_outage_is_not_acknowledged() -> None:
    """The test that matters most.

    "We could not ask who this is" must never be recorded as "this person cannot be
    reached". One is a fact about the platform and the event has to come back; the other
    is a fact about a person and goes in the delivery record. Confusing them silently
    drops a household's message and makes the coverage figures wrong in the direction
    that looks fine.
    """
    directory = StubDirectory(raises=DirectoryUnavailable("core-api is down"))
    channel = StubChannel()

    with pytest.raises(DirectoryUnavailable):
        await payment_notices.handle(released_event(), directory=directory, channel=channel)

    assert channel.sent == []


async def test_a_channel_refusal_is_reported_not_swallowed() -> None:
    """A gateway that refused is not a message that was sent."""
    directory = StubDirectory(contact_value=a_contact())
    channel = StubChannel(status=DeliveryStatus.FAILED)

    result = await payment_notices.handle(released_event(), directory=directory, channel=channel)

    assert not result.sent
    assert result.reason == "channel_refused"


async def test_the_null_directory_resolves_nothing_and_says_so() -> None:
    """A deployment with no credential must not look like one with nothing to send.

    It returns None rather than inventing a recipient, which the consumer records as a
    gap - and the directory logs the remedy on every attempt.
    """
    result = await payment_notices.handle(
        released_event(), directory=NullDirectory(), channel=StubChannel()
    )

    assert not result.sent
    assert result.acknowledged


async def test_an_unhandled_event_type_is_not_retried_forever() -> None:
    """Subscribed to two types and handed a third.

    Worth logging loudly, not worth redelivering: the subscription and the dispatch have
    fallen out of step and no amount of retrying fixes that.
    """
    envelope = EventEnvelope(event_type=catalogue.ALERT_DISPATCHED, producer="test", payload={})

    result = await payment_notices.handle(
        envelope, directory=StubDirectory(), channel=StubChannel()
    )

    assert not result.sent
    assert result.acknowledged


# --------------------------------------------------------------------------------------
# The contracts these events must satisfy
# --------------------------------------------------------------------------------------


def test_both_events_validate_against_their_published_contracts() -> None:
    """The payload a service publishes must match the contract that documents it.

    `EventPayload` forbids extra fields, so a consumer calling `parse_payload` on a
    payload with an undocumented field fails outright. The released contract carried
    exactly this defect from file 10 until the first consumer was written - which is this
    one.
    """
    # Importing the payloads module is what populates the registry; without it every
    # lookup is an UnknownEventType and this test would pass for the wrong reason.
    import sarana_shared.events.payloads  # noqa: F401
    from sarana_shared.events.registry import parse_payload

    parse_payload(released_event())
    parse_payload(reversed_event())


def test_the_consumer_declares_itself_side_effecting() -> None:
    """A replay must never re-send these.

    Messaging every household about a payment they were told about weeks ago is the exact
    harm `side_effect_free` exists to prevent.
    """
    import inspect

    source = inspect.getsource(payment_notices.PaymentNoticeWorker)
    assert "side_effect_free=False" in source


def test_the_reply_words_are_typeable_on_any_keyboard() -> None:
    """YES and NO stay Latin in all three languages.

    Asking somebody to switch input method to answer a one-word question is asking them
    not to answer, and the reply is the only independent evidence the platform gets.
    """
    for language in ("si", "ta", "en"):
        body = payment_messages.confirmation_message(
            amount_lkr_cents=1000, payment_ref="X", language=language
        )
        assert payment_messages.YES in body
        assert payment_messages.NO in body


def test_an_amount_is_rendered_in_rupees_not_cents() -> None:
    """`47,500` rather than `4750000`. The second is a different number to a reader."""
    assert payment_messages.format_lkr(47_500_00) == "47,500"
    assert payment_messages.format_lkr(250_000_00) == "250,000"
