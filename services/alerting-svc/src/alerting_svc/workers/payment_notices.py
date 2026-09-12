"""Telling a household what happened to their money.

Two events, one job. The ledger records a payment; this is what makes somebody find out
about it.

**`disbursement.released` → the confirmation message.** "LKR 47,500 has been sent to your
account. Reply YES if it arrived, or NO if it did not." That reply is the only independent
evidence this platform ever gets that money actually reached a person — a ledger recording
what the state believes it paid is not evidence that anyone was paid. A NO becomes a
grievance automatically. It is the cheapest and highest-signal error detector in the
system, and it does not exist unless this message goes out.

**`disbursement.reversed` → the bad news, and what to do about it.** The bank returned the
payment, a case has already been opened, and the household is at home believing they have
been paid. The message names the amount, says what to do — take new account details to the
Divisional Secretariat, visit your branch — and gives the case reference, because being
told something went wrong with no way to follow it up is worse than not being told.

Three rules the handler follows, and each is a failure mode it exists to avoid:

**At most once.** `handle_idempotently` claims the event in the same transaction as the
send. A redelivered event must not send a second SMS to somebody already confused about the
first.

**A household with no phone is a recorded gap, not an error.** Not everybody has one. It is
logged and acknowledged, because retrying forever against a person who cannot be reached by
SMS achieves nothing except hiding the fact that somebody has to visit them.

**A directory outage is a retry, not a gap.** The event is *not* acknowledged, so it comes
back. Treating "we could not ask who this is" as "this person cannot be reached" would
silently drop a household's confirmation message and make the coverage figures wrong in the
direction that looks fine.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alerting_svc.adapters.channels.base import Channel, DeliveryStatus, Message, Target
from alerting_svc.adapters.households import (
    DirectoryUnavailable,
    HouseholdContact,
    HouseholdDirectory,
)
from alerting_svc.domain import payment_messages
from sarana_shared.domain import reversal_reasons
from sarana_shared.events import catalogue
from sarana_shared.events.bus import EventBus, Subscription
from sarana_shared.events.envelope import EventEnvelope

_log = structlog.get_logger(__name__)

# The two events this consumer handles. Named here rather than inline so the subscription
# and the dispatch table cannot fall out of step.
HANDLED: Final[tuple[str, ...]] = (
    catalogue.AID_DISBURSEMENT_RELEASED,
    catalogue.AID_DISBURSEMENT_REVERSED,
)

CONSUMER_GROUP: Final = "alerting_payment_notices"


@dataclass(frozen=True, slots=True)
class NoticeResult:
    """What happened to one notice. Returned so a test can assert without reading logs."""

    sent: bool
    reason: str

    @property
    def acknowledged(self) -> bool:
        """Whether the event is done with.

        A gap is done: the household cannot be reached by SMS and re-delivering the event
        will not change that. An outage is not.
        """
        return self.reason != "directory_unavailable"


async def notify_released(
    envelope: EventEnvelope,
    *,
    directory: HouseholdDirectory,
    channel: Channel,
) -> NoticeResult:
    """Ask a household whether their payment arrived."""
    payload = envelope.payload
    if not payload.get("confirmation_required", True):
        # The releasing service can say the household should not be asked - a cash payment
        # handed over against a signature is already confirmed by the signature.
        return NoticeResult(sent=False, reason="confirmation_not_required")

    contact = await _resolve(directory, payload["household_id"])
    if contact is None or not contact.reachable:
        return _gap(payload["household_id"], "no_contact")

    body = payment_messages.confirmation_message(
        amount_lkr_cents=int(payload["amount_lkr_cents"]),
        payment_ref=payload.get("payment_ref"),
        language=contact.preferred_language,
    )
    return await _send(channel, contact, body, kind="confirmation")


async def notify_reversed(
    envelope: EventEnvelope,
    *,
    directory: HouseholdDirectory,
    channel: Channel,
) -> NoticeResult:
    """Tell a household their payment came back, and where the case is."""
    payload = envelope.payload

    contact = await _resolve(directory, payload["household_id"])
    if contact is None or not contact.reachable:
        # Worse than a missed confirmation. A household who cannot be reached by SMS about
        # a *failed* payment is one who will keep believing they were paid until an officer
        # gets to them, so this is logged at warning rather than info.
        _log.warning(
            "reversal_notice_undeliverable",
            household_id=str(payload["household_id"]),
            grievance_ref=payload.get("grievance_ref"),
            impact="the household believes they were paid and cannot be told by SMS; "
            "the grievance is open and needs an officer to make contact",
        )
        return NoticeResult(sent=False, reason="no_contact")

    body = payment_messages.reversal_message(
        amount_lkr_cents=int(payload["amount_lkr_cents"]),
        reason_text=reversal_reasons.reason_text(
            str(payload.get("reason", "")), contact.preferred_language
        ),
        grievance_ref=str(payload.get("grievance_ref", "-")),
        language=contact.preferred_language,
    )
    return await _send(channel, contact, body, kind="reversal")


async def _resolve(directory: HouseholdDirectory, household_id: object) -> HouseholdContact | None:
    """Resolve a household, letting a directory outage propagate."""
    return await directory.contact(str(household_id))


def _gap(household_id: object, reason: str) -> NoticeResult:
    _log.info(
        "payment_notice_no_contact",
        household_id=str(household_id),
        impact="no SMS was sent; this household has no contact number on file",
    )
    return NoticeResult(sent=False, reason=reason)


async def _send(
    channel: Channel, contact: HouseholdContact, body: str, *, kind: str
) -> NoticeResult:
    """Hand one message to the channel and report what came back."""
    # `reachable` was checked by the caller, so the hash is present. Asserted rather than
    # assumed because a None here would address a message to nobody and report it sent.
    assert contact.recipient_ref_hash is not None  # noqa: S101 - guarded by `reachable`
    target = Target(
        target_ref_hash=contact.recipient_ref_hash,
        gn_division_code=contact.gn_division_code,
        preferred_language=contact.preferred_language,
    )
    message = Message(target=target, language=target.preferred_language or "en", body=body)

    receipts = await channel.send([message])
    delivered = any(
        receipt.status in {DeliveryStatus.SENT, DeliveryStatus.DELIVERED} for receipt in receipts
    )
    _log.info(
        "payment_notice_sent",
        kind=kind,
        language=message.language,
        accepted=delivered,
        # Never the hash and never the number. Which household got which message is in the
        # delivery record behind an access check, not in a log line.
        gn_division_code=target.gn_division_code,
    )
    return NoticeResult(sent=delivered, reason="sent" if delivered else "channel_refused")


async def handle(
    envelope: EventEnvelope,
    *,
    directory: HouseholdDirectory,
    channel: Channel,
) -> NoticeResult:
    """Route one event to its notice.

    Raises:
        DirectoryUnavailable: so the bus redelivers. The one failure that must not be
            acknowledged: a household whose contact could not be looked up has not been
            told anything, and dropping the event loses that permanently.
    """
    if envelope.event_type == catalogue.AID_DISBURSEMENT_RELEASED:
        return await notify_released(envelope, directory=directory, channel=channel)
    if envelope.event_type == catalogue.AID_DISBURSEMENT_REVERSED:
        return await notify_reversed(envelope, directory=directory, channel=channel)

    # Subscribed to two types and handed a third. Not an error to raise on - redelivering
    # it forever would not help - but worth saying loudly, because it means the
    # subscription and this function have fallen out of step.
    _log.error("payment_notice_unhandled_event", event_type=envelope.event_type)
    return NoticeResult(sent=False, reason="unhandled_event_type")


class PaymentNoticeWorker:
    """Subscribes to the two payment events and sends the messages.

    Failures inside a handler are not swallowed: the bus redelivers an unacknowledged
    event, and `handle_idempotently` is what stops the redelivery producing a second SMS.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        bus: EventBus,
        directory: HouseholdDirectory,
        channel: Channel,
    ) -> None:
        self._factory = session_factory
        self._bus = bus
        self._directory = directory
        self._channel = channel
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="alerting-payment-notices")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        from alerting_svc.adapters.events import handle_idempotently

        async def on_event(envelope: EventEnvelope) -> None:
            async with self._factory() as session:

                async def run(_session: AsyncSession, event: EventEnvelope) -> str | None:
                    result = await handle(event, directory=self._directory, channel=self._channel)
                    if not result.acknowledged:
                        # Raised so the claim rolls back with it and the bus redelivers.
                        raise DirectoryUnavailable(
                            "the household directory could not be reached; this notice "
                            "has not been sent and the event must come back"
                        )
                    return result.reason

                await handle_idempotently(session, envelope, run, group=CONSUMER_GROUP)
                await session.commit()

        await self._bus.subscribe(
            Subscription(
                group=CONSUMER_GROUP,
                consumer=CONSUMER_GROUP,
                event_types=HANDLED,
                # This sends real SMS to real people. A replay handed to this consumer
                # would message every household about a payment they were told about
                # weeks ago, so the bus refuses to hand it a replayed envelope at all.
                side_effect_free=False,
            ),
            on_event,
        )
