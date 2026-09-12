"""Bank and payment rail — the transfer that actually reaches a household.

Settlement is asynchronous and that is the whole difficulty. A transfer is *accepted*
immediately and *settles* later, so there is a window in which the ledger has released
money that has not arrived, and a smaller window in which it never will.

Three consequences, all of them load-bearing:

  **Accepted is not settled.** `TransferState.ACCEPTED` means the rail took the
  instruction. Nothing has moved. Anything that reports an accepted transfer to a
  household as a completed payment is lying to somebody waiting for money.

  **Idempotent on `client_reference`.** Submitting the same reference twice returns the
  first transfer, never a second one. This is what makes a retry after a timeout safe,
  and a timeout on a payment call is exactly when a retry is most tempting.

  **A failed transfer is a compensating ledger entry plus a grievance, not a retry.**
  Roughly three in a hundred fail — account closed, name mismatch, dormant account — and
  they fail *after* the ledger recorded a release. The append-only ledger cannot be edited
  to pretend it did not happen, so the correction is a new entry that reverses it and a
  grievance raised on the household's behalf so a human follows up. Retrying silently
  would leave a household with a published disbursement and an empty account.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field

from sarana_shared.adapters.gov.base import Integration, MockGovClient, RealClientStub


class TransferState(StrEnum):
    """Where a transfer has got to on the rail."""

    ACCEPTED = "ACCEPTED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    RETURNED = "RETURNED"


class FailureReason(StrEnum):
    """Why a rail refused or returned a transfer.

    A closed enum rather than free text, because each of these has a different remedy and
    the grievance raised for the household should say which one applies. "Payment failed"
    tells a family nothing they can act on.
    """

    ACCOUNT_CLOSED = "ACCOUNT_CLOSED"
    ACCOUNT_DORMANT = "ACCOUNT_DORMANT"
    NAME_MISMATCH = "NAME_MISMATCH"
    INVALID_ACCOUNT = "INVALID_ACCOUNT"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"


class TransferRequest(BaseModel):
    """An instruction to move money to one beneficiary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_reference: str
    amount_lkr_cents: int = Field(gt=0)
    rail: str
    # A keyed hash, never an account number. The rail resolves it at the edge against the
    # mandate the household gave; nothing in SARANA holds the account.
    beneficiary_ref_hash: str
    narrative: str


class Transfer(BaseModel):
    """A transfer as the rail currently sees it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    transfer_ref: str
    client_reference: str
    state: TransferState
    amount_lkr_cents: int = Field(ge=0)
    accepted_at: datetime
    settled_at: datetime | None = None
    failure_reason: FailureReason | None = None

    @property
    def is_final(self) -> bool:
        """Whether this transfer will not change again."""
        return self.state in (TransferState.SETTLED, TransferState.FAILED, TransferState.RETURNED)

    @property
    def money_moved(self) -> bool:
        """Whether a household actually received anything.

        The property to branch on before telling anyone they have been paid. Deliberately
        not `state != FAILED`: an accepted transfer has not moved money either.
        """
        return self.state is TransferState.SETTLED


class WebhookRegistration(BaseModel):
    """The rail's acknowledgement of a settlement callback URL."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    webhook_id: str
    url: str
    events: tuple[str, ...] = Field(default_factory=tuple)
    registered_at: datetime


class PaymentClient(Protocol):
    """What SARANA needs from a payment rail."""

    async def submit(self, request: TransferRequest) -> Transfer:
        """Instruct a transfer. Idempotent on `client_reference`.

        Returns as soon as the rail accepts, normally in `ACCEPTED`. Settlement follows.
        """
        ...

    async def transfer(self, transfer_ref: str) -> Transfer:
        """The current state of one transfer.

        Raises:
            GovRecordNotFound: if the rail has no such transfer.
        """
        ...

    async def register_webhook(self, *, url: str, events: list[str]) -> WebhookRegistration:
        """Ask the rail to call back on settlement and failure.

        The callback is an optimisation, never the only path: settlement is also polled,
        because a webhook that silently stops arriving looks exactly like a quiet day.
        """
        ...

    async def aclose(self) -> None: ...


class PaymentMockClient(MockGovClient):
    """Talks to `gov-mock`'s payment rail routes."""

    system: ClassVar[str] = "pay"

    async def submit(self, request: TransferRequest) -> Transfer:
        body = await self._post_json("/pay/v1/transfers", json=request.model_dump(mode="json"))
        return Transfer.model_validate(body["transfer"])

    async def transfer(self, transfer_ref: str) -> Transfer:
        body = await self._get_json(f"/pay/v1/transfers/{transfer_ref}")
        return Transfer.model_validate(body["transfer"])

    async def register_webhook(self, *, url: str, events: list[str]) -> WebhookRegistration:
        body = await self._post_json(
            "/pay/v1/webhooks/register", json={"url": url, "events": events}
        )
        return WebhookRegistration.model_validate(body["webhook"])


class PaymentRealClient(RealClientStub):
    """A commercial bank's disbursement rail. Not yet written.

    Government relief in Sri Lanka moves through several rails at once — bank transfer,
    mobile money, post office order, and cash handed over against a signature — and only
    the first two have an API at all. The real client will therefore be one per rail
    behind this Protocol, not one client.

    The hard part is not the transfer. It is the mandate: proving the account belongs to
    the household the entitlement was calculated for, without SARANA holding the account
    number. That is what `beneficiary_ref_hash` is for and what has to be agreed.
    """

    integration: ClassVar[Integration] = Integration(
        system="pay",
        organisation="Bank of Ceylon / People's Bank disbursement rails",
        base_url="https://corporate.boc.lk/api/disbursement",
        credential=(
            "a corporate disbursement account with per-batch authorisation, mTLS, and a "
            "signing certificate held in the HSM rather than the application"
        ),
        agreement=(
            "a bulk disbursement agreement covering beneficiary reference resolution, "
            "the settlement SLA, and how a returned payment is reconciled"
        ),
    )

    async def submit(self, request: TransferRequest) -> Transfer:
        self._pending("submit", "/transfers")

    async def transfer(self, transfer_ref: str) -> Transfer:
        self._pending("transfer", f"/transfers/{transfer_ref}")

    async def register_webhook(self, *, url: str, events: list[str]) -> WebhookRegistration:
        self._pending("register_webhook", "/webhooks/register")
