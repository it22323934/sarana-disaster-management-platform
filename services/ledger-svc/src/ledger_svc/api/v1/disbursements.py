"""**HUMAN GATE.** Releasing money.

The second of the two mandatory gates, and the most consequential endpoint in the platform.
A payment sent to the wrong household is not coming back, so every check is a refusal by
default and the checks run in a fixed order that `domain.disbursement_gate` owns and
`tests/ledger/test_disbursement_gate.py` asserts.

Three things are deliberately absent and none of them is "not yet implemented":

**No amount field.** The amount comes from the entitlement, which came from the
calculation, which came from the pinned schedule. A releaser who could type a number would
make the whole trace decorative.

**No bulk release.** One mis-selected filter away from paying a district twice. If bulk is
ever added it releases one at a time under one step-up with an explicit per-item list and a
hard cap - but not now, and not behind a checkbox that says "apply to all".

**No override.** There is no flag that skips the grievance check or the segregation check.
An override that exists is an override that gets used at 3am during a cyclone.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ledger_svc.adapters.events import publish
from ledger_svc.adapters.rails import RAIL_DESCRIPTIONS, build_rail
from ledger_svc.api.deps import CorrelationDep, SessionDep
from ledger_svc.domain import disbursement_gate as gate
from ledger_svc.domain.ledger_entry import public_entry
from ledger_svc.repo import chain_writer, queries
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.domain.ids import uuid7
from sarana_shared.errors import (
    Conflict,
    Forbidden,
    HumanGateRequired,
    NotFound,
    Unauthenticated,
    UpstreamUnavailable,
    ValidationFailed,
)
from sarana_shared.events import catalogue

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["disbursements"])

ReadPrincipal = Depends(require(Scope.DISBURSEMENT_READ))

# The gate. `require` refuses every machine principal on this scope outright, and
# `strip_human_gates` removed it from every agent token at mint time, so an agent cannot
# reach this endpoint even if something upstream is misconfigured.
ReleasePrincipal = Depends(require(Scope.DISBURSEMENT_RELEASE, allow_machine=False))


class ReleaseRequest(BaseModel):
    """A district approver releasing one entitlement.

    Note what is not here. No amount, no override, no list of entitlements. The only thing
    the caller chooses is which rail the money goes out on.
    """

    model_config = ConfigDict(extra="forbid")

    entitlement_id: UUID
    payment_rail: str = Field(
        default="BANK_TRANSFER", description=f"One of: {', '.join(sorted(RAIL_DESCRIPTIONS))}"
    )
    acknowledged: bool = Field(
        default=True, description="Reserved for the console confirmation dialogue."
    )


class DisbursementOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    id: str
    entitlement_id: str
    amount_lkr_cents: int
    released_by: str
    released_at: datetime
    payment_rail: str
    payment_ref: str | None
    prev_hash: str
    entry_hash: str
    citizen_confirmed: bool = False
    simulated: bool = Field(
        default=True,
        description="Every payment rail in Phase 1 is a mock, and every reference says so.",
    )


@router.post("/disbursements", response_model=DisbursementOut, status_code=201)
async def release_disbursement(
    body: ReleaseRequest,
    request: Request,
    session: SessionDep,
    correlation_id: CorrelationDep,
    principal: Principal = ReleasePrincipal,
) -> Any:
    """**HUMAN GATE.** Release the money for one entitlement.

    Six independent things must all hold, and each fails differently on purpose:

      - `Scope.DISBURSEMENT_RELEASE` for the entitlement's district, refused to every
        machine principal (403);
      - a second factor verified within the last five minutes (401 - the caller may hold
        the scope; what is missing is proof of who is at the keyboard);
      - the releaser is neither the assessor nor an approver (409);
      - every required approval is present and not superseded (409);
      - no open grievance on this entitlement (409);
      - the payment rail accepts it (502, and nothing is written).

    The entitlement is read once into a `ReleaseContext` and the gate decides from that
    alone. It never reaches back into the database mid-decision, which is what makes the
    order of its checks testable rather than merely documented.
    """
    if body.payment_rail not in RAIL_DESCRIPTIONS:
        raise ValidationFailed(
            f"{body.payment_rail!r} is not a payment rail; expected one of "
            f"{', '.join(sorted(RAIL_DESCRIPTIONS))}"
        )

    row = await queries.release_context_row(session, body.entitlement_id)
    if row is None:
        raise NotFound("No such entitlement.")

    # The area check. Done here rather than in the dependency because only this service
    # can get from an entitlement to the division it belongs to, and the area must come
    # from the stored record rather than anything the caller sent.
    if not principal.can(Scope.DISBURSEMENT_RELEASE, row["gn_division_code"]):
        raise Forbidden("Releasing a disbursement in this area is outside your scope.")

    approvals = [
        gate.Approval(
            level=gate.ApprovalLevel(approval["level"]),
            approver_id=UUID(approval["approver_id"]),
            decision=approval["decision"],
            # An approval attached to a recalculated entitlement approved a different
            # number. Recalculation supersedes the entitlement rather than the approval,
            # so a superseded entitlement makes its approvals superseded too.
            superseded=row["entitlement_status"] == "REJECTED",
        )
        for approval in await queries.approvals_for(session, body.entitlement_id)
    ]
    open_grievances = await queries.open_grievances_for(session, body.entitlement_id)

    context = gate.ReleaseContext(
        entitlement_id=body.entitlement_id,
        amount_lkr_cents=int(row["calculated_lkr_cents"]),
        district_code=row["gn_division_code"],
        assessor_id=UUID(row["assessor_id"]),
        approvals=approvals,
        open_grievance_ids=[UUID(item["id"]) for item in open_grievances],
        already_released=bool(row["already_released"]),
    )
    rail = build_rail(body.payment_rail)

    try:
        decision = await gate.release(context, principal=principal, rail=rail)
    except gate.StepUpRequired as error:
        # 401 rather than 403: the caller may well hold the scope. What is missing is
        # proof of who is at the keyboard.
        raise Unauthenticated(
            str(error), context={"reason": "step_up_required", "scope": "disbursement:release"}
        ) from error
    except gate.AlreadyReleased as error:
        raise Conflict(str(error)) from error
    except gate.SegregationViolated as error:
        raise Conflict(str(error)) from error
    except gate.ApprovalsIncomplete as error:
        raise HumanGateRequired(str(error)) from error
    except gate.GrievanceOpen as error:
        raise Conflict(str(error)) from error
    except gate.ReleaseRefused as error:
        # The rail. Nothing has been written, and the message says so.
        raise UpstreamUnavailable(str(error)) from error

    columns = {
        "id": uuid7(),
        "entitlement_id": body.entitlement_id,
        "amount_lkr_cents": decision.amount_lkr_cents,
        "released_by": decision.released_by,
        "released_at": decision.at,
        "payment_rail": body.payment_rail,
        "payment_ref": decision.payment_ref,
        "correlation_id": correlation_id,
    }
    # What the chain covers: the payment, in the one shape `/ledger/public` publishes and
    # the anchor job hashes. The confirmation columns are outside it on purpose - a
    # household replying to an SMS is evidence about this entry, not part of it, and a
    # ledger whose hash changed when somebody answered would fail verification for an
    # honest reason.
    hashed = public_entry(
        entitlement_id=body.entitlement_id,
        amount_lkr_cents=decision.amount_lkr_cents,
        released_by=decision.released_by,
        released_at=decision.at,
        payment_rail=body.payment_rail,
        payment_ref=decision.payment_ref,
    )

    stored = await chain_writer.append(
        session, schema="aid", table="disbursement", columns=columns, hashed_payload=hashed
    )
    await queries.set_entitlement_status(session, body.entitlement_id, "DISBURSED")

    publish(
        session,
        catalogue.AID_DISBURSEMENT_RELEASED,
        {
            "disbursement_id": str(columns["id"]),
            "entitlement_id": str(body.entitlement_id),
            "household_id": row["household_id"],
            "amount_lkr_cents": decision.amount_lkr_cents,
            "released_by": str(decision.released_by),
            "payment_rail": body.payment_rail,
            "payment_ref": decision.payment_ref,
            "seq": stored["seq"],
            "entry_hash": stored["entry_hash"],
            # alerting-svc listens for this and sends the confirmation SMS. The household
            # is asked whether the money arrived, which is the only independent evidence
            # this platform ever gets that it did.
            "confirmation_required": True,
            "simulated": True,
        },
        subject=str(columns["id"]),
    )
    _log.info(
        "disbursement_released",
        disbursement_id=str(columns["id"]),
        entitlement_id=str(body.entitlement_id),
        amount_lkr_cents=decision.amount_lkr_cents,
        seq=stored["seq"],
        rail=body.payment_rail,
    )

    return {
        **columns,
        "id": str(columns["id"]),
        "entitlement_id": str(body.entitlement_id),
        "released_by": str(decision.released_by),
        **stored,
        "citizen_confirmed": False,
        "simulated": True,
    }


@router.get("/disbursements/{disbursement_id}", response_model=DisbursementOut)
async def read_disbursement(
    disbursement_id: UUID,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
) -> Any:
    found = await queries.get_disbursement(session, disbursement_id)
    if found is None:
        raise NotFound("No such disbursement.")
    return {**found, "simulated": True}


@router.get("/disbursements", response_model=list[DisbursementOut])
async def list_disbursements(
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    from_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> Any:
    rows = await queries.ledger_page(session, from_seq=from_seq, limit=limit)
    return [{**row, "simulated": True} for row in rows]
