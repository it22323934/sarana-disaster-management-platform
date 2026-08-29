"""Payment rail routes.

**Accepted is not settled.** A transfer comes back `ACCEPTED` and stays there until enough
simulated time has passed. Since the clock is pinned unless somebody advances it, a demo
has to explicitly move time forward to watch money arrive — which is the right shape,
because it makes the window between "the ledger released it" and "the household has it"
visible instead of instantaneous.

**About 3% fail, and they fail after acceptance.** That is the case the ledger has to
handle: an append-only entry has already recorded a release that turned out not to happen.
The correction is a compensating entry plus an auto-raised grievance, never a silent retry
— retrying leaves a household with a published disbursement and an empty account.

Idempotent on `client_reference`, which is what makes retrying after a timeout safe.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from gov_mock.api.deps import SimulatedNowDep, StateDep, mock_json
from gov_mock.data.derive import choose, falls_within
from gov_mock.state import MockState, Transfer, Webhook

router = APIRouter(prefix="/pay/v1", tags=["pay"])

# The rails the ledger recognises, mirroring `aid.disbursement.payment_rail`.
RAILS: Final[frozenset[str]] = frozenset({"BANK_TRANSFER", "MOBILE_MONEY", "POST_OFFICE", "CASH"})

# How long settlement takes, in simulated hours. Bank batches clear overnight; cash is
# handed over at a counter and is either done or not.
SETTLEMENT_HOURS: Final[dict[str, float]] = {
    "BANK_TRANSFER": 18.0,
    "MOBILE_MONEY": 0.5,
    "POST_OFFICE": 36.0,
    "CASH": 4.0,
}

# Build file 11 puts the failure rate at ~3%.
FAILURE_SHARE: Final = 0.03

# Why a transfer fails, and how often relative to the others. Every one of these is a
# reason a household can be told and can act on; "payment failed" is not.
FAILURE_REASONS: Final[tuple[str, ...]] = (
    "ACCOUNT_CLOSED",
    "ACCOUNT_DORMANT",
    "NAME_MISMATCH",
    "INVALID_ACCOUNT",
    "LIMIT_EXCEEDED",
)

# Above this, the rail refuses at submission rather than after acceptance. A single
# transfer of ten million rupees to one household is a data-entry error, and catching it
# at the rail is the last line before the money leaves.
SINGLE_TRANSFER_CEILING_CENTS: Final = 1_000_000_00


class TransferIn(BaseModel):
    """An instruction to move money to one beneficiary."""

    model_config = ConfigDict(extra="forbid")

    client_reference: str = Field(min_length=1, max_length=64)
    amount_lkr_cents: int = Field(gt=0)
    rail: str
    beneficiary_ref_hash: str = Field(min_length=1, max_length=128)
    narrative: str = Field(default="", max_length=140)


class WebhookIn(BaseModel):
    """A settlement callback registration."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=512)
    events: list[str] = Field(default_factory=list)


def _fails(client_reference: str) -> bool:
    """Whether this transfer fails after acceptance.

    Derived from the reference rather than drawn, so a transfer's fate does not change
    between the submit call and the settlement poll. A mock that re-rolled would produce
    transfers recovering from FAILED, which no rail does.

    See `gov_mock.data.derive` for why this is a digest and not a checksum over the
    characters — a batch of sequential references must not share one fate.
    """
    return falls_within(client_reference, share=FAILURE_SHARE, salt="pay-fail")


def _failure_reason(client_reference: str) -> str:
    return choose(client_reference, FAILURE_REASONS, salt="pay-reason")


def _transfer_body(transfer: Transfer, now: datetime) -> dict[str, Any]:
    """Render a transfer, computing its state from how long the rail has had it."""
    elapsed_hours = (now - transfer.accepted_at).total_seconds() / 3600.0
    settles_after = SETTLEMENT_HOURS[transfer.rail]

    if elapsed_hours < settles_after:
        state = "ACCEPTED"
        settled_at = None
        reason = None
    elif _fails(transfer.client_reference):
        state = "FAILED"
        settled_at = None
        reason = _failure_reason(transfer.client_reference)
    else:
        state = "SETTLED"
        settled_at = transfer.accepted_at
        reason = None

    return {
        "transfer_ref": transfer.transfer_ref,
        "client_reference": transfer.client_reference,
        "state": state,
        "amount_lkr_cents": transfer.amount_lkr_cents,
        "accepted_at": transfer.accepted_at.isoformat(),
        "settled_at": settled_at.isoformat() if settled_at else None,
        "failure_reason": reason,
    }


@router.post("/transfers", summary="Instruct a transfer", status_code=201)
def submit(payload: TransferIn, state: StateDep, now: SimulatedNowDep) -> Any:
    """Instruct a transfer. Idempotent on `client_reference`."""
    if payload.rail not in RAILS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown rail {payload.rail!r}; expected one of {sorted(RAILS)}",
        )
    if payload.amount_lkr_cents > SINGLE_TRANSFER_CEILING_CENTS:
        raise HTTPException(
            status_code=422,
            detail=(
                "Amount exceeds the single-transfer ceiling. Refused at the rail rather "
                "than accepted and reversed."
            ),
        )

    existing_ref = state.transfers_by_client_ref.get(payload.client_reference)
    if existing_ref is not None:
        return mock_json({"transfer": _transfer_body(state.transfers[existing_ref], now)})

    sequence = state.next_sequence()
    transfer = Transfer(
        # Every reference says what it is. `MOCK-` first, as in
        # `ledger_svc.adapters.rails`, so a reference pasted into a ticket is
        # unmistakable at a glance.
        transfer_ref=f"MOCK-PAY-{payload.rail}-{sequence:08d}",
        client_reference=payload.client_reference,
        amount_lkr_cents=payload.amount_lkr_cents,
        rail=payload.rail,
        beneficiary_ref_hash=payload.beneficiary_ref_hash,
        accepted_at=now,
    )
    state.transfers[transfer.transfer_ref] = transfer
    state.transfers_by_client_ref[payload.client_reference] = transfer.transfer_ref

    return mock_json({"transfer": _transfer_body(transfer, now)}, status_code=201)


@router.get("/transfers/{transfer_ref}", summary="Transfer state")
def transfer(transfer_ref: str, state: StateDep, now: SimulatedNowDep) -> Any:
    """The current state of one transfer."""
    found = state.transfers.get(transfer_ref)
    if found is None:
        raise HTTPException(status_code=404, detail="No such transfer")
    return mock_json({"transfer": _transfer_body(found, now)})


@router.post("/webhooks/register", summary="Register a settlement callback", status_code=201)
def register_webhook(payload: WebhookIn, state: StateDep, now: SimulatedNowDep) -> Any:
    """Register a callback URL for settlement and failure.

    Recorded and never called. Delivering a callback would mean this mock reaching into
    the platform on its own schedule, which makes a scenario replay depend on network
    timing; the ledger polls instead. The registration exists so the real integration's
    shape is present and so nothing has to be invented later.
    """
    sequence = state.next_sequence()
    webhook = Webhook(
        webhook_id=f"MOCK-WH-{sequence:06d}",
        url=payload.url,
        events=tuple(payload.events),
        registered_at=now,
    )
    state.webhooks[webhook.webhook_id] = webhook

    return mock_json(
        {
            "webhook": {
                "webhook_id": webhook.webhook_id,
                "url": webhook.url,
                "events": list(webhook.events),
                "registered_at": webhook.registered_at.isoformat(),
            },
            "note": "Registered but never called; the ledger polls settlement.",
        },
        status_code=201,
    )


def transfers_for_state(state: MockState, now: datetime) -> list[dict[str, Any]]:
    """Every transfer, for `GET /mock/v1/state`."""
    return [_transfer_body(transfer, now) for transfer in state.transfers.values()]
