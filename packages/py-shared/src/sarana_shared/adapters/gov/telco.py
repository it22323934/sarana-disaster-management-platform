"""Telco SMS and USSD gateway — the channel that reaches people with no smartphone.

Three operators are modelled, and they behave differently on purpose. The differences are
not colour: they are the reasons the delivery accounting in file 09 is shaped the way it
is.

  **Delivery receipts are late, and one operator does not send them at all.** Roughly two
  per cent of messages on that operator are delivered or dropped with no DLR ever
  arriving. That is why `UNKNOWN` is a distinct delivery state from `FAILED` in
  `alerting_svc`, and why it counts *against* coverage rather than being folded into
  delivered. A map claiming a village was warned when nobody knows is worse than a map
  admitting the gap.

  **Throughput is capped per operator.** A national fan-out does not leave in one second,
  and an alert that assumes it does will report as dispatched long before anybody's phone
  buzzes.

  **Coverage is modelled per division and it degrades during an event.** Cell sites lose
  power. The scenario driver drops coverage as the storm passes, which is exactly when the
  warning matters and exactly when it stops arriving.

Receipts are pushed back to `alerting-svc` at `/internal/v1/dlr/{provider}` rather than
polled. `send` returns message ids; it does not return delivery.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field

from sarana_shared.adapters.gov.base import Integration, MockGovClient, RealClientStub


class Operator(StrEnum):
    """The three mobile operators modelled.

    Named rather than numbered so a delivery gap in a district can be read against the
    operator that actually serves it.
    """

    DIALOG = "DIALOG"
    MOBITEL = "MOBITEL"
    HUTCH = "HUTCH"


class MessageState(StrEnum):
    """What the gateway knows about one message.

    `UNKNOWN` is the honest answer from an operator that sends no receipts, and it is a
    state the platform must carry rather than resolve.
    """

    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class SmsRequest(BaseModel):
    """One outbound SMS.

    The recipient is a keyed hash. The gateway resolves it to a number at the edge against
    the mandate the citizen gave; nothing above this line handles an MSISDN.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    recipient_ref_hash: str
    body: str
    language: str
    # Life-safety traffic jumps the queue. A billing-priority message and an evacuation
    # order sharing a queue is a design that kills people slowly.
    priority: bool = False


class SmsAccepted(BaseModel):
    """The gateway's acknowledgement of one message."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message_id: str
    recipient_ref_hash: str
    operator: Operator
    state: MessageState
    accepted_at: datetime
    # None for the operator that sends no receipts. Present so a caller can tell "no DLR
    # yet" from "no DLR ever", which are different waits.
    dlr_expected: bool = True


class BulkAccepted(BaseModel):
    """The result of a bulk submission.

    Partial acceptance is normal: a gateway at its throughput cap takes what it can and
    refuses the rest. `rejected` is not an error — it is the part that has to be resent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    accepted: tuple[SmsAccepted, ...] = Field(default_factory=tuple)
    rejected: tuple[str, ...] = Field(default_factory=tuple)
    throughput_limit_per_second: int = Field(ge=0)

    @property
    def fully_accepted(self) -> bool:
        return not self.rejected


class MessageStatus(BaseModel):
    """The gateway's current view of one message."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message_id: str
    operator: Operator
    state: MessageState
    updated_at: datetime
    failure_reason: str | None = None


class UssdPush(BaseModel):
    """A USSD session pushed to a handset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    recipient_ref_hash: str
    operator: Operator
    accepted_at: datetime


class Coverage(BaseModel):
    """Modelled mobile coverage for one GN division.

    `percent` is the share of the population with a usable signal *now*, not the share
    with a subscription. During an event it falls as cell sites lose mains power and run
    down their batteries.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gn_division_code: str
    percent: float = Field(ge=0.0, le=100.0)
    operators: tuple[Operator, ...] = Field(default_factory=tuple)
    sites_on_battery: int = Field(default=0, ge=0)
    sites_down: int = Field(default=0, ge=0)
    measured_at: datetime


class TelcoClient(Protocol):
    """What SARANA needs from the telco gateway."""

    async def send_sms(self, message: SmsRequest) -> SmsAccepted:
        """Submit one message."""
        ...

    async def send_bulk(self, messages: list[SmsRequest]) -> BulkAccepted:
        """Submit many messages, accepting partial acceptance."""
        ...

    async def push_ussd(self, *, recipient_ref_hash: str, menu_id: str) -> UssdPush:
        """Push a USSD session to a handset."""
        ...

    async def message(self, message_id: str) -> MessageStatus:
        """The gateway's current view of one message.

        Raises:
            GovRecordNotFound: if the gateway has no such message.
        """
        ...

    async def coverage(self, *, gn_division_code: str) -> Coverage:
        """Modelled coverage for one GN division."""
        ...

    async def aclose(self) -> None: ...


class TelcoMockClient(MockGovClient):
    """Talks to `gov-mock`'s telco gateway routes."""

    system: ClassVar[str] = "telco"

    async def send_sms(self, message: SmsRequest) -> SmsAccepted:
        body = await self._post_json(
            "/telco/v1/sms/send", json={"messages": [message.model_dump(mode="json")]}
        )
        return SmsAccepted.model_validate(body["accepted"][0])

    async def send_bulk(self, messages: list[SmsRequest]) -> BulkAccepted:
        body = await self._post_json(
            "/telco/v1/sms/send",
            json={"messages": [message.model_dump(mode="json") for message in messages]},
        )
        return BulkAccepted.model_validate(body)

    async def push_ussd(self, *, recipient_ref_hash: str, menu_id: str) -> UssdPush:
        body = await self._post_json(
            "/telco/v1/ussd/push",
            json={"recipient_ref_hash": recipient_ref_hash, "menu_id": menu_id},
        )
        return UssdPush.model_validate(body["push"])

    async def message(self, message_id: str) -> MessageStatus:
        body = await self._get_json(f"/telco/v1/sms/{message_id}")
        return MessageStatus.model_validate(body["message"])

    async def coverage(self, *, gn_division_code: str) -> Coverage:
        body = await self._get_json(
            "/telco/v1/coverage", params={"gn_division_id": gn_division_code}
        )
        return Coverage.model_validate(body["coverage"])


class TelcoRealClient(RealClientStub):
    """A mobile operator's enterprise messaging gateway. Not yet written.

    One client per operator behind this Protocol: Dialog, Mobitel and Hutch each have
    their own gateway, their own throughput agreement and their own receipt format.

    The thing to negotiate first is not the API. It is priority routing for life-safety
    traffic and a sender ID that a citizen recognises as the state — an evacuation order
    arriving from a short code indistinguishable from a promotion is one that gets
    ignored. Both are commercial conversations with a long lead time.
    """

    integration: ClassVar[Integration] = Integration(
        system="telco",
        organisation="Dialog Axiata / Mobitel / Hutch enterprise messaging",
        base_url="https://api.operator.lk/messaging",
        credential=(
            "a registered enterprise sender ID per operator with priority routing for "
            "emergency traffic, and IP allowlisting on the submit endpoint"
        ),
        agreement=(
            "a bulk messaging contract per operator, TRCSL authorisation for the "
            "emergency sender ID, and an agreed receipt format including how the "
            "operator reports a message it cannot account for"
        ),
    )

    async def send_sms(self, message: SmsRequest) -> SmsAccepted:
        self._pending("send_sms", "/sms/send")

    async def send_bulk(self, messages: list[SmsRequest]) -> BulkAccepted:
        self._pending("send_bulk", "/sms/send")

    async def push_ussd(self, *, recipient_ref_hash: str, menu_id: str) -> UssdPush:
        self._pending("push_ussd", "/ussd/push")

    async def message(self, message_id: str) -> MessageStatus:
        self._pending("message", f"/sms/{message_id}")

    async def coverage(self, *, gn_division_code: str) -> Coverage:
        self._pending("coverage", "/coverage")
