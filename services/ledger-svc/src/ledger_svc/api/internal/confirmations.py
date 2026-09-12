"""The citizen confirmation loop, arriving from the SMS gateway.

After every release the household gets a message in their own language naming the amount,
the date and the reference, and asking them to reply YES if it arrived and NO if it did
not. This endpoint is where that reply lands.

**This is the highest-signal input the platform receives.** A ledger that records only what
the state believes it paid is not evidence that anyone was paid. The reply costs the sender
one message and tells us the one thing no dashboard can.

Three answers, kept distinct:

  YES           the household confirms receipt.
  NO            a grievance is created automatically and the DS is notified.
  no reply      recorded as `unconfirmed` after seven days. **Not** as failed - a dead
                phone, an SMS that never arrived, or a message nobody understood are not
                evidence the money is missing, and reporting them as failures would
                overstate one problem while hiding another.

Anything unrecognised goes to a person. Guessing YES closes a case nobody confirmed;
guessing NO puts a false dispute on a household's record.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ledger_svc.adapters.events import publish
from ledger_svc.api.deps import CorrelationDep, SessionDep
from ledger_svc.domain import grievance as domain
from ledger_svc.repo import queries
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.domain.ids import uuid7
from sarana_shared.errors import NotFound
from sarana_shared.events import catalogue

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["internal"])

# The SMS gateway adapter is a machine principal. It may record a reply and nothing else -
# it cannot read the ledger, approve anything, or release money.
GatewayPrincipal = Depends(require(Scope.GRIEVANCE_FILE))


class ConfirmationReplyIn(BaseModel):
    """One inbound reply, as the gateway received it."""

    model_config = ConfigDict(extra="forbid")

    disbursement_id: UUID
    body: str = Field(max_length=1600, description="The reply text, exactly as it arrived.")
    channel: str = Field(default="SMS", description="SMS or USSD")
    received_from: str | None = Field(
        default=None,
        max_length=32,
        description="Masked MSISDN, for the gateway's own reconciliation. Never logged.",
    )


class ConfirmationOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    disbursement_id: str
    reply: str = Field(description="YES, NO or UNRECOGNISED. Never guessed.")
    confirmed: bool
    grievance_id: str | None = None
    grievance_ref: str | None = None
    action: str = Field(description="What was done, in words, for the gateway's log.")


@router.post("/grievances/sms", response_model=ConfirmationOut)
async def record_confirmation_reply(
    body: ConfirmationReplyIn,
    session: SessionDep,
    correlation_id: CorrelationDep,
    principal: Principal = GatewayPrincipal,
) -> Any:
    """Record a household's answer to the confirmation message.

    Never fails on an unrecognised reply. The gateway has done its job by delivering it,
    and a 400 here would make an unparseable message look like a transport problem and get
    retried until it was dropped. The reply is reported back as UNRECOGNISED and goes to a
    person.
    """
    disbursement = await queries.get_disbursement(session, body.disbursement_id)
    if disbursement is None:
        raise NotFound("No such disbursement.")

    reply = domain.parse_confirmation(body.body)

    if reply is domain.ConfirmationReply.YES:
        recorded = await queries.record_citizen_confirmation(
            session, disbursement_id=body.disbursement_id, channel=body.channel
        )
        if recorded is None:
            # Already confirmed. A repeated YES is not an error - a household that replies
            # twice has done nothing wrong.
            return {
                "disbursement_id": str(body.disbursement_id),
                "reply": reply.value,
                "confirmed": True,
                "action": "already confirmed; nothing changed",
            }

        publish(
            session,
            catalogue.AID_DISBURSEMENT_CITIZEN_CONFIRMED,
            {
                "disbursement_id": str(body.disbursement_id),
                "entitlement_id": recorded["entitlement_id"],
                "channel": body.channel,
                "confirmed_at": recorded["citizen_confirmed_at"].isoformat(),
            },
            subject=str(body.disbursement_id),
        )
        _log.info("citizen_confirmed", disbursement_id=str(body.disbursement_id))
        return {
            "disbursement_id": str(body.disbursement_id),
            "reply": reply.value,
            "confirmed": True,
            "action": "receipt confirmed by the household",
        }

    if reply is domain.ConfirmationReply.NO:
        new = domain.from_confirmation_reply(
            household_id=UUID(disbursement["household_id"]),
            disbursement_id=body.disbursement_id,
            body=body.body,
            assigned_ds_division_code=disbursement["gn_division_code"],
            correlation_id=correlation_id,
        )
        # `from_confirmation_reply` returns None for anything but NO, and we are inside the
        # NO branch, so this cannot be None. Asserted rather than assumed because the
        # alternative is a silent 500 on the one path that matters most.
        if new is None:  # pragma: no cover - unreachable, kept as a guard
            raise NotFound("The reply could not be turned into a grievance.")

        grievance_id = uuid7()
        stored = await queries.insert_grievance(
            session, **new.as_columns(grievance_id=grievance_id)
        )

        publish(
            session,
            catalogue.AID_GRIEVANCE_RAISED,
            {
                "grievance_id": stored["id"],
                "public_ref": stored["public_ref"],
                "subject_type": "DISBURSEMENT",
                "subject_id": str(body.disbursement_id),
                "channel": body.channel,
                "sla_due_at": new.sla_due_at.isoformat(),
                "assigned_ds_division_code": disbursement["gn_division_code"],
                # The DS is notified because this is a household saying money they were
                # told about did not arrive, and every day of that is a day they go
                # without it.
                "notify_ds": True,
                "source": "citizen_confirmation_reply",
            },
            subject=stored["id"],
        )
        _log.warning(
            "citizen_reported_non_receipt",
            disbursement_id=str(body.disbursement_id),
            grievance_ref=stored["public_ref"],
        )
        return {
            "disbursement_id": str(body.disbursement_id),
            "reply": reply.value,
            "confirmed": False,
            "grievance_id": stored["id"],
            "grievance_ref": stored["public_ref"],
            "action": "grievance raised and the DS notified",
        }

    _log.info(
        "citizen_reply_unrecognised",
        disbursement_id=str(body.disbursement_id),
        # The body is not logged. It is a citizen's message and may contain anything.
        body_length=len(body.body),
    )
    return {
        "disbursement_id": str(body.disbursement_id),
        "reply": reply.value,
        "confirmed": False,
        "action": (
            "the reply was not YES or NO in any of the three languages; nothing was "
            "concluded and it needs a person to read it"
        ),
    }
