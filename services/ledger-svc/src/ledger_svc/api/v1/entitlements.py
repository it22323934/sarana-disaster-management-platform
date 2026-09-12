"""Entitlements: what an accepted assessment is worth, and who signed for it.

The trace is the product. A number without its working is exactly the opacity this ledger
exists to replace, so `calculation_trace` is written with the entitlement, is NOT NULL, and
is never edited. Recalculation creates a new entitlement and supersedes the old one.

Approvals are hash-chained. They go through `repo.chain_writer` rather than a plain INSERT,
because `prev_hash` is an input to `entry_hash` and so has to be computed against the
current tail before the row is written - the trigger refuses anything else.
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
from ledger_svc.domain import entitlement as calc
from ledger_svc.domain.approval import (
    DEFAULT_DISTRICT_THRESHOLD_CENTS,
    ApprovalIncomplete,
    ApprovalLevel,
    ApprovalState,
    SelfApproval,
    is_ready_to_release,
)
from ledger_svc.repo import chain_writer, queries
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now
from sarana_shared.errors import Conflict, Forbidden, NotFound, ValidationFailed
from sarana_shared.events import catalogue

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["entitlements"])

ReadPrincipal = Depends(require(Scope.ENTITLEMENT_READ))
CalculatePrincipal = Depends(require(Scope.ENTITLEMENT_CALCULATE))


class CalculateRequest(BaseModel):
    """Value one accepted assessment against the schedule in force when it was written.

    There is no amount field and no schedule override. The schedule is chosen by the
    assessment date, so a schedule published after the cyclone cannot move an entitlement
    somebody has already been told about.
    """

    model_config = ConfigDict(extra="forbid")

    assessment_id: UUID
    units: int = Field(default=1, ge=0, description="How many of the assessed unit were lost.")


class ApproveRequest(BaseModel):
    """One approval decision.

    Carries no TOTP code: the second factor is verified by core-api's step-up endpoint,
    which owns the MFA secrets, and this request is authorised by the step-up stamp on the
    token it arrives with.
    """

    model_config = ConfigDict(extra="forbid")

    level: ApprovalLevel
    decision: str = Field(default="APPROVED", description="APPROVED, REJECTED or RETURNED")
    reason: str | None = Field(default=None, max_length=1000)


class EntitlementOut(BaseModel):
    """An entitlement with the full working attached."""

    model_config = ConfigDict(frozen=True)

    id: str
    assessment_id: str
    assessment_ref: str
    household_id: str
    gn_division_code: str
    cost_schedule_version: str
    calculated_lkr_cents: int
    calculation_trace: dict[str, Any]
    calculated_at: datetime
    status: str
    requires_district_approval: bool
    approvals: list[dict[str, Any]] = Field(default_factory=list)


class EntitlementSummary(BaseModel):
    """One entitlement in a work queue.

    Deliberately without `calculation_trace`. The trace is the product and it belongs on
    the detail view where somebody is about to act on it; carrying it in a list of two
    hundred rows would make the queue expensive to load and would not be read on the way
    past.

    `approved_levels` and `released` are what a queue is filtered on, and both are computed
    from the tables that are the record rather than from a denormalised column that can
    disagree with them.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    assessment_id: str
    assessment_ref: str
    household_id: str
    gn_division_code: str
    category: str
    cost_schedule_version: str
    calculated_lkr_cents: int
    calculated_at: datetime
    status: str
    approved_levels: list[str] = Field(default_factory=list)
    released: bool = False


class ApprovalOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    entitlement_id: str
    level: str
    approver_id: str
    decision: str
    decided_at: datetime
    prev_hash: str
    entry_hash: str


@router.get("/entitlements", response_model=list[EntitlementSummary])
async def list_entitlements(
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    status: str | None = Query(default=None, max_length=24),
    division: str | None = Query(default=None, max_length=16),
    awaiting_release: bool = Query(
        default=False,
        description="Only entitlements carrying every approval they need and not yet paid.",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Entitlements, oldest first.

    The queue behind both money screens. Without it a district approver has no way to ask
    what is waiting, and a console rendering an empty list would be telling them no money
    is waiting when there might be a hundred households.

    `awaiting_release` is decided by `domain.approval.is_ready_to_release` rather than by a
    WHERE clause, so the queue and the disbursement gate answer from the same rule. A
    second copy of it in SQL is a second copy that can drift, and the way that drift
    presents is a queue offering an approver work the gate then refuses.
    """
    rows = await queries.list_entitlements(
        session, status=status, division=division, limit=limit, offset=offset
    )
    if not awaiting_release:
        return rows

    return [
        row
        for row in rows
        if not row["released"]
        and is_ready_to_release(int(row["calculated_lkr_cents"]), row["approved_levels"])
    ]


@router.post("/entitlements", response_model=EntitlementOut, status_code=201)
async def calculate_entitlement(
    body: CalculateRequest,
    session: SessionDep,
    correlation_id: CorrelationDep,
    principal: Principal = CalculatePrincipal,
) -> Any:
    """Calculate an entitlement from an accepted assessment.

    Refused if the assessment is not ACCEPTED. Calculating from a submitted assessment
    would produce a figure attached to damage nobody has reviewed, and the number is what
    people remember regardless of the status beside it.
    """
    assessment = await queries.get_assessment(session, body.assessment_id)
    if assessment is None:
        raise NotFound("No such assessment.")

    if assessment["status"] != "ACCEPTED":
        raise Conflict(
            f"this assessment is {assessment['status']}. Only an ACCEPTED assessment can "
            "be valued - a figure calculated from unreviewed damage is the number people "
            "will remember whatever status sits beside it."
        )

    schedule_row = await queries.schedule_in_force(session, assessment["assessed_at"].date())
    if schedule_row is None:
        raise Conflict(
            f"no cost schedule was in force on {assessment['assessed_at'].date()}. An "
            "entitlement cannot be calculated against a schedule that does not exist."
        )

    lines = [
        line
        for line in await queries.cost_schedule_lines(session)
        if line["cost_schedule_id"] == schedule_row["id"]
    ]
    matching = [line for line in lines if line["category"] == assessment["category"]]
    if not matching:
        raise Conflict(
            f"schedule {schedule_row['version']} has no line for {assessment['category']}. "
            "The assessment cannot be valued until the schedule covers this category."
        )

    line = matching[0]
    schedule = calc.CostSchedule(
        version=schedule_row["version"],
        lines={
            line["category"]: calc.ScheduleLine(
                line_id=UUID(line["id"]),
                category=line["category"],
                unit_amount_cents=int(line["rate_lkr_cents"]),
                max_units=int(line["formula"].get("max_units", 1)),
                formula=str(line["formula"].get("expression", "units * unit_amount")),
            )
        },
    )

    try:
        trace = calc.calculate(
            [calc.AssessedItem(category=assessment["category"], units=body.units)], schedule
        )
    except calc.CalculationRefused as error:
        raise ValidationFailed(str(error)) from error

    entitlement_id = uuid7()
    stored = await queries.insert_entitlement(
        session,
        id=entitlement_id,
        assessment_id=body.assessment_id,
        cost_schedule_id=UUID(schedule_row["id"]),
        cost_schedule_version=schedule_row["version"],
        calculated_lkr_cents=trace.result_lkr_cents,
        calculation_trace=json.dumps(trace.as_dict(), ensure_ascii=False),
        status="CALCULATED",
        correlation_id=correlation_id,
    )

    publish(
        session,
        catalogue.AID_ENTITLEMENT_CALCULATED,
        {
            "entitlement_id": stored["id"],
            "assessment_id": str(body.assessment_id),
            "calculated_lkr_cents": trace.result_lkr_cents,
            "cost_schedule_version": schedule_row["version"],
            "calculation_trace": trace.as_dict(),
        },
        subject=stored["id"],
    )
    _log.info(
        "entitlement_calculated",
        entitlement_id=stored["id"],
        amount_lkr_cents=trace.result_lkr_cents,
        schedule_version=schedule_row["version"],
    )

    found = await queries.get_entitlement(session, entitlement_id)
    return {
        **(found or {}),
        "requires_district_approval": (trace.result_lkr_cents > DEFAULT_DISTRICT_THRESHOLD_CENTS),
        "approvals": [],
    }


@router.get("/entitlements/{entitlement_id}", response_model=EntitlementOut)
async def read_entitlement(
    entitlement_id: UUID,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
) -> Any:
    """One entitlement, including the full calculation trace and every approval.

    The trace comes back to everyone who can read the entitlement, not only to auditors.
    A household that can see the schedule line, the inputs and each step can check the
    arithmetic themselves, which is what makes the figure contestable.
    """
    found = await queries.get_entitlement(session, entitlement_id)
    if found is None:
        raise NotFound("No such entitlement.")

    approvals = await queries.approvals_for(session, entitlement_id)
    return {
        **found,
        "requires_district_approval": (
            int(found["calculated_lkr_cents"]) > DEFAULT_DISTRICT_THRESHOLD_CENTS
        ),
        "approvals": approvals,
    }


@router.post("/entitlements/{entitlement_id}/approve", response_model=ApprovalOut, status_code=201)
async def approve_entitlement(
    entitlement_id: UUID,
    body: ApproveRequest,
    session: SessionDep,
    principal: Principal = CalculatePrincipal,
) -> Any:
    """Record one approval, hash-chained.

    Not the human gate - that is the release - but the signature the gate checks for. Two
    things are refused here rather than at release, because catching them now tells the
    officer something they can act on:

      - approving your own assessment, or approving at both levels;
      - a refusal with no reason, which leaves the household nothing to dispute.
    """
    if body.decision not in {"APPROVED", "REJECTED", "RETURNED"}:
        raise ValidationFailed(
            f"{body.decision!r} is not an approval decision; expected APPROVED, REJECTED "
            "or RETURNED"
        )
    if body.decision != "APPROVED" and not (body.reason or "").strip():
        raise ValidationFailed(
            "a refusal needs a reason. The household can dispute this decision, and one "
            "that gives no grounds leaves them nothing to dispute."
        )

    required = (
        Scope.ENTITLEMENT_APPROVE_DS
        if body.level is ApprovalLevel.DS
        else Scope.ENTITLEMENT_APPROVE_DISTRICT
    )
    found = await queries.get_entitlement(session, entitlement_id)
    if found is None:
        raise NotFound("No such entitlement.")

    if not principal.can(required, found["gn_division_code"]):
        raise Forbidden(
            f"approving at {body.level.value} level in this area requires {required.value}."
        )

    existing = await queries.approvals_for(session, entitlement_id)
    state = ApprovalState(
        amount_lkr_cents=int(found["calculated_lkr_cents"]),
        assessed_by=UUID(found["assessed_by"]),
        ds_approver_id=next((UUID(a["approver_id"]) for a in existing if a["level"] == "DS"), None),
        district_approver_id=next(
            (UUID(a["approver_id"]) for a in existing if a["level"] == "DISTRICT"), None
        ),
    )

    approver_id = UUID(principal.subject_id)
    try:
        state.assert_may_approve(approver_id, body.level)
    except SelfApproval as error:
        raise Conflict(str(error)) from error

    decided_at = utc_now()
    columns = {
        "id": uuid7(),
        "entitlement_id": entitlement_id,
        "level": body.level.value,
        "approver_id": approver_id,
        "decision": body.decision,
        "decided_at": decided_at,
        "reason": body.reason,
    }
    # What the chain covers: the decision itself. Storage details - the row id, when the
    # row happened to be written - are excluded, so a replica that differs in those still
    # verifies.
    hashed = {
        "entitlement_id": str(entitlement_id),
        "level": body.level.value,
        "approver_id": str(approver_id),
        "decision": body.decision,
        "decided_at": decided_at.isoformat(),
        "reason": body.reason,
    }

    stored = await chain_writer.append(
        session, schema="aid", table="approval", columns=columns, hashed_payload=hashed
    )

    if body.decision == "APPROVED":
        state = ApprovalState(
            amount_lkr_cents=state.amount_lkr_cents,
            assessed_by=state.assessed_by,
            ds_approver_id=(
                approver_id if body.level is ApprovalLevel.DS else state.ds_approver_id
            ),
            district_approver_id=(
                approver_id if body.level is ApprovalLevel.DISTRICT else state.district_approver_id
            ),
        )
        try:
            state.assert_ready_to_disburse()
            next_status = "APPROVED"
        except ApprovalIncomplete:
            next_status = "AWAITING_DISTRICT" if state.requires_district() else "AWAITING_DS"
    else:
        next_status = "REJECTED"

    await queries.set_entitlement_status(session, entitlement_id, next_status)

    publish(
        session,
        catalogue.AID_APPROVAL_RECORDED,
        {
            "entitlement_id": str(entitlement_id),
            "level": body.level.value,
            "decision": body.decision,
            "seq": stored["seq"],
            "entry_hash": stored["entry_hash"],
            "entitlement_status": next_status,
        },
        subject=str(entitlement_id),
    )
    _log.info(
        "approval_recorded",
        entitlement_id=str(entitlement_id),
        level=body.level.value,
        decision=body.decision,
        seq=stored["seq"],
    )

    return {
        **columns,
        "entitlement_id": str(entitlement_id),
        "approver_id": str(approver_id),
        **stored,
    }
