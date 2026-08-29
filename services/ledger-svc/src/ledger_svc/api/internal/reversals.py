"""A released payment came back. Recording that, and telling the household.

The rail accepts a transfer immediately and settles it later, and about three in a hundred
fail in between — account closed, dormant, name mismatch. By then the ledger has recorded
a release, hashed it and published it.

This endpoint is where that gets corrected, and it does four things or none:

  1. **appends a compensating entry** to `aid.disbursement_reversal`, on its own hash
     chain, committing to the disbursement it reverses;
  2. **stamps `reversed_at`** on the original — done by a database trigger, so the
     back-pointer cannot drift from the entry;
  3. **raises a grievance on the household's behalf**, because nobody has told them and
     they are at home believing they have been paid;
  4. **returns the entitlement to APPROVED**, so the money they are owed can be sent again.

**Never a retry.** Re-sending to the account that just rejected it produces a second
failure and a ledger claiming two payments. Paying again is a new release through the human
gate, after a person has looked at why the first one bounced. That is why this endpoint
does not send anything.

**Never an edit.** `aid.disbursement` keeps saying what it said: this money was released,
on this date, by this person. That remains true, and an auditor has to be able to see that
the state believed it had paid this household. What changed is what happened next, and that
is its own entry.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ledger_svc.adapters.events import publish
from ledger_svc.api.deps import CorrelationDep, SessionDep
from ledger_svc.domain import grievance as grievance_domain
from ledger_svc.domain import reversal as domain
from ledger_svc.repo import chain_writer, queries
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.domain.ids import uuid7
from sarana_shared.errors import Conflict, NotFound, ValidationFailed
from sarana_shared.events import catalogue

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["internal"])

# The settlement poller is a machine principal holding the same scope as the SMS gateway:
# it may record a fact about a payment and nothing else. It cannot read the ledger, approve
# anything, or release money — and `domain.reversal.MACHINE_REPORTABLE` stops it recording
# a reason that is a human judgement rather than something a bank reported.
RailPrincipal = Depends(require(Scope.GRIEVANCE_FILE))


class ReversalIn(BaseModel):
    """A rail reporting that a transfer it accepted has come back."""

    model_config = ConfigDict(extra="forbid")

    disbursement_id: UUID
    reason: str = Field(
        max_length=32,
        description="Why the rail returned it. See domain.reversal.ReversalReason.",
    )
    rail_reference: str | None = Field(
        default=None,
        max_length=128,
        description="The rail's own reference for the failed transfer, for reconciliation "
        "against the bank's statement.",
    )


class ReversalOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    reversal_id: str
    disbursement_id: str
    entitlement_id: str
    amount_lkr_cents: int
    reason: str
    seq: int
    entry_hash: str
    grievance_id: str
    grievance_ref: str
    action: str = Field(description="What was done, in words, for the caller's log.")


@router.post("/disbursements/reversal", response_model=ReversalOut, status_code=201)
async def record_reversal(
    body: ReversalIn,
    session: SessionDep,
    correlation_id: CorrelationDep,
    principal: Principal = RailPrincipal,
) -> Any:
    """Record that a released payment was returned, and open a case for the household."""
    context = await queries.reversal_context_row(session, body.disbursement_id)
    if context is None:
        raise NotFound("No such disbursement.")

    if context["reversed_at"] is not None:
        # A rail reporting the same failure twice is the same failure. Returning the
        # existing entry rather than 409-ing keeps a poller idempotent: it will re-report
        # every failure it sees on every pass, and making that an error would fill the logs
        # with alarms about the system working correctly.
        existing = await queries.get_reversal_for(session, body.disbursement_id)
        if existing is None:  # pragma: no cover - the trigger keeps these in step
            raise Conflict(
                "The disbursement is marked reversed but carries no compensating entry. "
                "That is a database inconsistency, not a client error."
            )
        return {
            **existing,
            "reversal_id": existing["id"],
            "action": "already reversed; nothing changed",
        }

    try:
        entry = domain.reverse(
            disbursement_id=body.disbursement_id,
            entitlement_id=UUID(context["entitlement_id"]),
            amount_lkr_cents=int(context["amount_lkr_cents"]),
            reason=body.reason,
            rail_reference=body.rail_reference or context["payment_ref"],
            correlation_id=correlation_id,
            # The caller is a machine, so a reason that is a judgement about what somebody
            # did rather than an observation of what a bank returned is refused here.
            by_machine=principal.is_machine,
        )
    except domain.ReversalRefused as error:
        raise ValidationFailed(str(error)) from error

    stored = await chain_writer.append(
        session,
        schema="aid",
        table="disbursement_reversal",
        columns=entry.as_columns(),
        hashed_payload=entry.hashed_payload(),
    )

    # The household is told what happened and what to do about it, in all three languages.
    # Raised before the entitlement is reopened so that a failure here rolls back the whole
    # transaction rather than leaving money on the books with nobody informed.
    new_grievance = grievance_domain.from_failed_transfer(
        household_id=UUID(context["household_id"]),
        disbursement_id=body.disbursement_id,
        description=entry.grievance_description(),
        assigned_ds_division_code=context["gn_division_code"],
        correlation_id=correlation_id,
    )
    grievance_id = uuid7()
    grievance = await queries.insert_grievance(
        session, **new_grievance.as_columns(grievance_id=grievance_id)
    )
    await queries.attach_grievance_to_reversal(
        session, reversal_id=entry.id, grievance_id=grievance_id
    )

    # Back to APPROVED, not REJECTED. The approvals still stand — what failed was the
    # transfer, not the decision — so the entitlement is payable again the moment somebody
    # has better bank details. Leaving it DISBURSED would bar the household permanently.
    await queries.set_entitlement_status(session, UUID(context["entitlement_id"]), "APPROVED")

    publish(
        session,
        catalogue.AID_DISBURSEMENT_REVERSED,
        {
            "reversal_id": str(entry.id),
            "disbursement_id": str(body.disbursement_id),
            "entitlement_id": context["entitlement_id"],
            "household_id": context["household_id"],
            "amount_lkr_cents": entry.amount_lkr_cents,
            "reason": entry.reason.value,
            "needs_new_bank_details": entry.reason.needs_new_bank_details,
            "grievance_id": str(grievance_id),
            "grievance_ref": grievance["public_ref"],
            "seq": stored["seq"],
            "entry_hash": stored["entry_hash"],
            "simulated": True,
        },
        subject=str(body.disbursement_id),
    )
    _log.info(
        "disbursement_reversed",
        disbursement_id=str(body.disbursement_id),
        entitlement_id=context["entitlement_id"],
        amount_lkr_cents=entry.amount_lkr_cents,
        reason=entry.reason.value,
        seq=stored["seq"],
        grievance_ref=grievance["public_ref"],
    )

    return {
        "reversal_id": str(entry.id),
        "disbursement_id": str(body.disbursement_id),
        "entitlement_id": context["entitlement_id"],
        "amount_lkr_cents": entry.amount_lkr_cents,
        "reason": entry.reason.value,
        "seq": stored["seq"],
        "entry_hash": stored["entry_hash"],
        "grievance_id": str(grievance_id),
        "grievance_ref": grievance["public_ref"],
        "action": "compensating entry written, grievance raised, entitlement reopened",
    }
