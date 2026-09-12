"""Grievances: a household disputing what the system decided about it.

ADR-008 makes this Phase 1 rather than future work. Sphere and the Core Humanitarian
Standard both require a complaints mechanism, and a platform that is auditable by
outsiders but not contestable by the affected household is not transparent to the person
who matters most.

Two design points show up repeatedly below:

**Filing is deliberately easy and resolving is deliberately not.** Any household may raise
a grievance through any channel with a sentence of description. Closing one requires a
trilingual resolution that is sent back to them, because a grievance closed with an
internal note is a grievance the household never learns the answer to.

**An open grievance blocks its own entitlement and nothing else.** A complaints process
that halts unrelated aid across a district teaches everyone in that district not to
complain.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from ledger_svc.adapters.events import publish
from ledger_svc.api.deps import CorrelationDep, SessionDep
from ledger_svc.domain import grievance as domain
from ledger_svc.repo import GRIEVANCE_CHANNELS, GRIEVANCE_SUBJECTS, queries
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.domain.ids import uuid7
from sarana_shared.errors import Conflict, NotFound, ValidationFailed
from sarana_shared.events import catalogue

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["grievances"])

FilePrincipal = Depends(require(Scope.GRIEVANCE_FILE))
ReadPrincipal = Depends(require(Scope.GRIEVANCE_READ))
ResolvePrincipal = Depends(require(Scope.GRIEVANCE_RESOLVE))


class RaiseRequest(BaseModel):
    """A household disputing something.

    `description` is trilingual because it is quoted back to the household in their own
    language when the grievance is answered, and because the same record is read by a DS
    officer who may not share their language.
    """

    model_config = ConfigDict(extra="forbid")

    household_id: UUID
    subject_type: str = Field(description=f"One of: {', '.join(GRIEVANCE_SUBJECTS)}")
    subject_id: UUID | None = Field(
        default=None,
        description="The disputed record. Null only for EXCLUSION - being left out has no id.",
    )
    channel: str = Field(description=f"One of: {', '.join(GRIEVANCE_CHANNELS)}")
    description: dict[str, str]
    assigned_ds_division_code: str | None = Field(default=None, max_length=16)


class AssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ds_division_code: str = Field(max_length=16)
    ds_division_id: UUID | None = None
    status: str = Field(default="UNDER_REVIEW")


class ResolveRequest(BaseModel):
    """Closing a grievance, one way or the other.

    `resolution` is sent to the household, so it exists in all three languages. REJECTED
    is a legitimate outcome and needs the same explanation as RESOLVED - a household told
    only "rejected" has learned nothing they can act on.
    """

    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="RESOLVED", description="RESOLVED or REJECTED")
    resolution: dict[str, str]


class GrievanceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    public_ref: str
    household_id: str
    subject_type: str
    subject_id: str | None
    channel: str
    raised_at: datetime
    status: str
    assigned_ds_division_code: str | None
    sla_due_at: datetime
    resolved_at: datetime | None = None
    sla_breached: bool = False


class RaiseResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    public_ref: str = Field(description="Quote this. Readable aloud over a phone.")
    status: str
    raised_at: datetime
    sla_due_at: datetime


def _refuse(error: domain.GrievanceRefused) -> ValidationFailed:
    """Turn a domain refusal into the one error shape, message intact.

    The messages are written for the person on the other end - a citizen on a phone or an
    officer in a DS office - so they are passed through rather than replaced with a
    generic validation failure.
    """
    return ValidationFailed(str(error))


@router.post("/grievances", response_model=RaiseResponse, status_code=201)
async def raise_grievance(
    body: RaiseRequest,
    session: SessionDep,
    correlation_id: CorrelationDep,
    principal: Principal = FilePrincipal,
) -> Any:
    """File a grievance from the app or the web.

    `Scope.GRIEVANCE_FILE` is held by CITIZEN, so a household files its own. Nothing here
    checks that the caller owns the household: that belongs to row-level security on the
    household table, and duplicating it as an ownership check would refuse the legitimate
    case of a neighbour or a GN officer filing on behalf of someone who cannot.
    """
    try:
        new = domain.raise_grievance(
            household_id=body.household_id,
            subject_type=body.subject_type,
            subject_id=body.subject_id,
            channel=body.channel,
            description=body.description,
            assigned_ds_division_code=body.assigned_ds_division_code,
            correlation_id=correlation_id,
        )
    except domain.GrievanceRefused as error:
        raise _refuse(error) from error

    grievance_id = uuid7()
    stored = await queries.insert_grievance(session, **new.as_columns(grievance_id=grievance_id))

    publish(
        session,
        catalogue.AID_GRIEVANCE_RAISED,
        {
            "grievance_id": stored["id"],
            "public_ref": stored["public_ref"],
            "subject_type": new.subject_type,
            "subject_id": str(new.subject_id) if new.subject_id else None,
            "channel": new.channel,
            "sla_due_at": new.sla_due_at.isoformat(),
        },
        subject=stored["id"],
    )
    _log.info("grievance_raised", public_ref=stored["public_ref"], channel=new.channel)
    return stored


@router.get("/grievances", response_model=list[GrievanceSummary])
async def list_grievances(
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    status: str | None = Query(default=None),
    ds: str | None = Query(default=None, max_length=16),
    household_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Grievances in the caller's scope, soonest SLA deadline first.

    Ordered by deadline rather than by date raised, because the list exists to stop
    somebody being forgotten and the oldest grievance is not always the most overdue.
    """
    return await queries.list_grievances(
        session, status=status, ds=ds, household_id=household_id, limit=limit, offset=offset
    )


@router.get("/grievances/{grievance_id}", response_model=GrievanceSummary)
async def read_grievance(
    grievance_id: UUID,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
) -> Any:
    found = await queries.get_grievance(session, grievance_id)
    if found is None:
        raise NotFound("No such grievance.")
    return {**found, "sla_breached": False}


@router.post("/grievances/{grievance_id}/assign", response_model=GrievanceSummary)
async def assign_grievance(
    grievance_id: UUID,
    body: AssignRequest,
    session: SessionDep,
    principal: Principal = ResolvePrincipal,
) -> Any:
    """Route a grievance to the DS division that will answer it.

    The SLA clock does not restart. It started when the household complained, and an
    assignment that reset it would let a grievance be kept indefinitely fresh by passing
    it between offices.
    """
    found = await queries.get_grievance(session, grievance_id)
    if found is None:
        raise NotFound("No such grievance.")

    try:
        domain.assert_transition(found["status"], body.status)
    except domain.GrievanceRefused as error:
        raise Conflict(str(error)) from error

    updated = await queries.assign_grievance(
        session,
        grievance_id=grievance_id,
        division_id=body.ds_division_id,
        division_code=body.ds_division_code,
        status=body.status,
    )
    if updated is None:
        raise Conflict("The grievance could not be assigned; re-read it and try again.")

    return {**found, **updated, "sla_breached": False}


@router.post("/grievances/{grievance_id}/resolve", response_model=GrievanceSummary)
async def resolve_grievance(
    grievance_id: UUID,
    body: ResolveRequest,
    session: SessionDep,
    principal: Principal = ResolvePrincipal,
) -> Any:
    """Close a grievance with an explanation the household will actually receive.

    Refused if the resolution is not written in all three languages, and refused if the
    grievance is already dispositioned - a resolution that could be replaced is a
    resolution that can be quietly withdrawn.
    """
    if body.status not in {"RESOLVED", "REJECTED"}:
        raise ValidationFailed(
            f"{body.status!r} does not close a grievance; use RESOLVED or REJECTED. To "
            "move it between open states, assign it."
        )

    found = await queries.get_grievance(session, grievance_id)
    if found is None:
        raise NotFound("No such grievance.")

    try:
        domain.assert_transition(found["status"], body.status)
        domain.assert_resolution_is_trilingual(body.resolution)
    except domain.GrievanceRefused as error:
        if "cannot be reopened" in str(error):
            raise Conflict(str(error)) from error
        raise _refuse(error) from error

    updated = await queries.resolve_grievance(
        session,
        grievance_id=grievance_id,
        status=body.status,
        resolution=json.dumps(body.resolution, ensure_ascii=False),
    )
    if updated is None:
        raise Conflict("This grievance has already been dispositioned.")

    elapsed = updated["resolved_at"] - updated["raised_at"]
    publish(
        session,
        catalogue.AID_GRIEVANCE_RESOLVED,
        {
            "grievance_id": updated["id"],
            "public_ref": updated["public_ref"],
            "status": updated["status"],
            "resolution": body.resolution,
            "resolution_seconds": int(elapsed.total_seconds()),
            "within_sla": updated["resolved_at"] <= updated["sla_due_at"],
        },
        subject=updated["id"],
    )
    _log.info(
        "grievance_resolved",
        public_ref=updated["public_ref"],
        status=updated["status"],
        within_sla=updated["resolved_at"] <= updated["sla_due_at"],
    )
    return {**found, **updated, "sla_breached": updated["resolved_at"] > updated["sla_due_at"]}
