"""Mock telco, push and manual channels.

Every one of these stands in for an integration that does not exist yet. They are written
to behave like the real thing where it matters - per-message receipts, partial failure,
asynchronous confirmation - so that the delivery accounting above them is exercised
properly rather than being tested against something that always succeeds.

A mock that always succeeds teaches you nothing about the day the gateway is congested.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import structlog

from alerting_svc.adapters.channels.base import DeliveryStatus, Message, Receipt

_log = structlog.get_logger(__name__)


@dataclass(slots=True)
class MockSmsGateway:
    """SMS through a mock telco.

    Reports SENT rather than DELIVERED: a real gateway confirms handset delivery later,
    over a DLR webhook. Claiming DELIVERED at send time would make every SMS look
    confirmed and hollow out the whole delivery-proof feature.
    """

    name: str = "SMS"
    simulated: bool = True
    failure_rate: float = 0.03
    seed: int | None = None
    _random: random.Random = field(default_factory=random.Random)

    def __post_init__(self) -> None:
        if self.seed is not None:
            self._random = random.Random(self.seed)  # noqa: S311

    async def send(self, messages: list[Message]) -> list[Receipt]:
        receipts = []
        for index, message in enumerate(messages):
            failed = self._random.random() < self.failure_rate
            receipts.append(
                Receipt(
                    target_ref_hash=message.target.target_ref_hash,
                    channel=self.name,
                    language=message.language,
                    # SENT, not DELIVERED. The DLR callback upgrades it.
                    status=DeliveryStatus.FAILED if failed else DeliveryStatus.SENT,
                    provider_ref=f"mock-sms-{index}",
                    failure_reason="gateway rejected the message" if failed else None,
                    simulated=True,
                )
            )
        return receipts


@dataclass(slots=True)
class MockUssdPush:
    """USSD push. Confirmed by the session opening on the handset."""

    name: str = "USSD"
    simulated: bool = True

    async def send(self, messages: list[Message]) -> list[Receipt]:
        return [
            Receipt(
                target_ref_hash=message.target.target_ref_hash,
                channel=self.name,
                language=message.language,
                # A USSD push only lands if the handset is on and idle. Unknown is the
                # honest answer for the rest.
                status=DeliveryStatus.UNKNOWN,
                failure_reason="awaiting session-open acknowledgement",
                simulated=True,
            )
            for message in messages
        ]


@dataclass(slots=True)
class MockPushService:
    """App push through a mock Expo/FCM/APNs.

    Receipts are polled after send in the real service, so this reports SENT and leaves
    the confirmation to the receipt webhook.
    """

    name: str = "PUSH"
    simulated: bool = True

    async def send(self, messages: list[Message]) -> list[Receipt]:
        return [
            Receipt(
                target_ref_hash=message.target.target_ref_hash,
                channel=self.name,
                language=message.language,
                status=DeliveryStatus.SENT,
                provider_ref="mock-push",
                simulated=True,
            )
            for message in messages
        ]


@dataclass(slots=True)
class InAppChannel:
    """In-app delivery: the client acknowledges having read it.

    Queued, not sent: the message waits until the app next opens. For someone whose phone
    is off during a flood that may be hours, and the receipt should say so.
    """

    name: str = "APP"
    simulated: bool = False

    async def send(self, messages: list[Message]) -> list[Receipt]:
        return [
            Receipt(
                target_ref_hash=message.target.target_ref_hash,
                channel=self.name,
                language=message.language,
                status=DeliveryStatus.QUEUED,
                failure_reason="waiting for the app to open",
                simulated=False,
            )
            for message in messages
        ]


@dataclass(slots=True)
class ManualChannel:
    """Radio and paper. A person does the delivering; an operator records the count.

    Nothing is confirmed per recipient because nothing can be. The receipt exists so the
    coverage picture can show that a division was reached by loudhailer even though no
    handset confirmed anything.
    """

    name: str = "RADIO"
    simulated: bool = False

    async def send(self, messages: list[Message]) -> list[Receipt]:
        return [
            Receipt(
                target_ref_hash=message.target.target_ref_hash,
                channel=self.name,
                language=message.language,
                status=DeliveryStatus.UNKNOWN,
                failure_reason="manual distribution; count recorded by an operator",
                simulated=False,
            )
            for message in messages
        ]
