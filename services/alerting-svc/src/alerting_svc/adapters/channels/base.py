"""The channel adapter contract, and language routing.

Fan-out is fan-out: every channel fires concurrently, none blocks another, and a channel
that throws does not fail the alert. A warning that reached five channels and failed on
the sixth is a warning that reached five channels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class DeliveryStatus(StrEnum):
    """What happened to one message.

    `UNKNOWN` is a real and important state, not a placeholder. A channel that cannot
    confirm delivery must say so rather than reporting success, because the whole point of
    the delivery record is telling an operator who probably was *not* reached.
    """

    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    NO_CHANNEL = "NO_CHANNEL"


@dataclass(frozen=True, slots=True)
class Target:
    """One person to warn, reduced to what a channel needs.

    Identified by an HMAC of their contact number, never the number itself. A channel
    adapter resolves that to a real address at the edge; nothing in this service decrypts
    it.
    """

    target_ref_hash: str
    gn_division_code: str
    preferred_language: str | None = None


@dataclass(frozen=True, slots=True)
class Message:
    """One rendered message for one target, in one language."""

    target: Target
    language: str
    body: str


@dataclass(frozen=True, slots=True)
class Receipt:
    """What a channel reports back about one message."""

    target_ref_hash: str
    channel: str
    language: str
    status: DeliveryStatus
    provider_ref: str | None = None
    failure_reason: str | None = None
    # True for every receipt from a transport that does not exist. Carried on the record,
    # not inferred from the channel name, so nothing downstream can lose it.
    simulated: bool = False


@dataclass(frozen=True, slots=True)
class ChannelResult:
    """Everything one channel did, including having failed entirely."""

    channel: str
    receipts: list[Receipt] = field(default_factory=list)
    error: str | None = None

    @property
    def failed_outright(self) -> bool:
        return self.error is not None

    @property
    def delivered(self) -> int:
        return sum(
            1
            for receipt in self.receipts
            if receipt.status in {DeliveryStatus.DELIVERED, DeliveryStatus.SENT}
        )


class Channel(Protocol):
    """One way of reaching people.

    `send` must not raise for a single message's failure - that is a FAILED receipt. It
    may raise if the whole channel is unavailable, and the fan-out records that without
    letting it touch the others.
    """

    name: str
    simulated: bool

    async def send(self, messages: list[Message]) -> list[Receipt]:
        """Deliver messages and report per-message outcomes."""
        ...


# How many languages each channel can carry per target.
#
# SMS is one: a trilingual SMS is three segments, which triples the cost and the time to
# clear a queue during exactly the event when the gateway is congested. The app has no such
# limit and sends all three, so nobody is reading a warning in their second language
# because of a billing constraint.
LANGUAGES_PER_CHANNEL: dict[str, int] = {
    "SMS": 1,
    "USSD": 1,
    "PUSH": 1,
    "APP": 3,
    "LORA": 1,
    "RADIO": 3,
    "PAPER_QR": 3,
}


def languages_for(
    target: Target,
    channel: str,
    *,
    division_languages: dict[str, list[str]] | None = None,
    default_order: tuple[str, ...] = ("si", "ta", "en"),
) -> list[str]:
    """Which languages to send this target on this channel, in order.

    A known preference wins. Otherwise the order comes from the **division's** dominant
    languages in reference data - never from the person's name. Inferring language from a
    name is both unreliable and the kind of inference that goes wrong in exactly the
    communities most likely to be missed.
    """
    capacity = LANGUAGES_PER_CHANNEL.get(channel, 1)

    if target.preferred_language:
        ordered = [target.preferred_language] + [
            language for language in default_order if language != target.preferred_language
        ]
    elif division_languages and target.gn_division_code in division_languages:
        known = division_languages[target.gn_division_code]
        ordered = known + [language for language in default_order if language not in known]
    else:
        ordered = list(default_order)

    return ordered[:capacity]


def no_channel_receipts(targets: list[Target], channel: str) -> list[Receipt]:
    """Receipts for targets a channel simply cannot reach.

    Recorded rather than dropped. "No channel available" is a distinct and actionable
    answer: those are the people who need a vehicle with a loudhailer.
    """
    return [
        Receipt(
            target_ref_hash=target.target_ref_hash,
            channel=channel,
            language="",
            status=DeliveryStatus.NO_CHANNEL,
            failure_reason="no address for this target on this channel",
        )
        for target in targets
    ]
