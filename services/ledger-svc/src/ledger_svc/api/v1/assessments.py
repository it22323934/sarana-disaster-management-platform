"""Damage assessments, including the offline sync endpoint the Field Companion pushes to.

An assessment is one GN officer's record of what one household lost. It is written offline,
often for a day or two, and pushed when the device next sees a network - so `/sync` is
written on the assumption that it will be called with the same batch more than once, from
more than one network, possibly at the same time.

**Assessments arrive SUBMITTED and are never auto-accepted.** Acceptance attaches evidence
and starts the money moving, and the officer who wrote the assessment is not the person who
decides it is sound.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from ledger_svc.adapters.events import publish
from ledger_svc.api.deps import CorrelationDep, SessionDep
from ledger_svc.domain import sync
from ledger_svc.repo import DAMAGE_CATEGORIES, queries
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.domain.ids import short_code, uuid7
from sarana_shared.errors import Conflict, NotFound, ValidationFailed
from sarana_shared.events import catalogue

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["assessments"])

ReadPrincipal = Depends(require(Scope.ASSESSMENT_READ))
WritePrincipal = Depends(require(Scope.ASSESSMENT_WRITE))
# Accepting an assessment is not the disbursement gate, but it is the point at which a
# figure becomes payable, so it sits with the officers who can approve rather than the one
# who wrote it. Segregation is enforced below.
ReviewPrincipal = Depends(require(Scope.ENTITLEMENT_CALCULATE))


class AssessmentPayload(BaseModel):
    """One household's loss, as recorded in the field."""

    model_config = ConfigDict(extra="forbid")

    household_id: UUID
    gn_division_id: UUID
    gn_division_code: str = Field(max_length=16)
    hazard_event_id: UUID
    category: str = Field(description=f"One of: {', '.join(DAMAGE_CATEGORIES)}")
    subcategory: str = Field(default="", max_length=48)
    cost_estimate_lkr_cents: int = Field(ge=0)
    assessed_at: datetime | None = None
    evidence_photo_uris: list[str] | None = None
    evidence_hash: str | None = None
    # Where the officer stood, not where the household is. Compared against the division
    # as one input to anomaly detection: an assessment filed from thirty kilometres away
    # is worth a look.
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    gps_accuracy_m: int | None = Field(default=None, gt=0)


class CreateAssessmentRequest(AssessmentPayload):
    """A single assessment submitted directly rather than through a sync batch."""

    client_operation_id: str = Field(
        max_length=64,
        description="Idempotency key from the device operation log. Resubmitting is safe.",
    )


class SyncOperationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_operation_id: str = Field(max_length=64)
    op: str = Field(description="create or update")
    seq: int = Field(ge=1)
    target: str | None = None
    payload: AssessmentPayload


class SyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(max_length=64)
    operations: list[SyncOperationIn]


class SyncResultOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    client_operation_id: str
    status: str
    server_id: str | None = None
    conflict: dict[str, Any] | None = None
    detail: str | None = None


class SyncResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    device_id: str
    results: list[SyncResultOut]
    applied: int
    device_cursor: int
    missing_seq: int | None = Field(
        default=None,
        description="Set when a gap paused this device. Send this seq, then retry.",
    )


class AssessmentSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    public_ref: str
    household_id: str
    gn_division_code: str
    hazard_event_id: str
    assessed_by: str
    assessed_at: datetime
    category: str
    cost_estimate_lkr_cents: int
    status: str


class CreatedAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    public_ref: str
    status: str
    duplicate: bool = Field(
        default=False,
        description="True when this operation id was already stored. Not an error.",
    )


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=1000)


def _columns(
    payload: AssessmentPayload,
    *,
    client_operation_id: str,
    assessed_by: UUID,
    correlation_id: str,
) -> dict[str, Any]:
    """Everything `aid.damage_assessment` needs for one insert.

    `assessed_by` comes from the token, never the body. An officer cannot file an
    assessment under somebody else's name, which is what makes the segregation check at
    release time mean anything.
    """
    return {
        "id": uuid7(),
        "public_ref": short_code("DMG"),
        "household_id": payload.household_id,
        "gn_division_id": payload.gn_division_id,
        "gn_division_code": payload.gn_division_code,
        "hazard_event_id": payload.hazard_event_id,
        "assessed_by": assessed_by,
        "assessed_at": payload.assessed_at,
        "category": payload.category,
        "subcategory": payload.subcategory,
        "cost_estimate_lkr_cents": payload.cost_estimate_lkr_cents,
        "evidence_photo_uris": payload.evidence_photo_uris,
        "evidence_hash": payload.evidence_hash,
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "gps_accuracy_m": payload.gps_accuracy_m,
        "client_operation_id": client_operation_id,
        # Never ACCEPTED on arrival. Acceptance is a separate decision by a different
        # person, and it is what makes the figure payable.
        "status": "SUBMITTED",
        "correlation_id": correlation_id,
    }


def _emit_submitted(session: Any, stored: dict[str, Any], payload: AssessmentPayload) -> None:
    publish(
        session,
        catalogue.AID_ASSESSMENT_SUBMITTED,
        {
            "assessment_id": stored["id"],
            "public_ref": stored["public_ref"],
            "household_id": str(payload.household_id),
            "gn_division_code": payload.gn_division_code,
            "hazard_event_id": str(payload.hazard_event_id),
            "category": payload.category,
            "cost_estimate_lkr_cents": payload.cost_estimate_lkr_cents,
        },
        subject=stored["id"],
    )


@router.post("/assessments", response_model=CreatedAssessment, status_code=201)
async def create_assessment(
    body: CreateAssessmentRequest,
    session: SessionDep,
    correlation_id: CorrelationDep,
    principal: Principal = WritePrincipal,
) -> Any:
    """Submit one assessment.

    A repeated `client_operation_id` returns the stored record with `duplicate: true`
    rather than an error. The device that retried did the right thing and should not have
    to interpret a 409 to find that out.
    """
    if body.category not in DAMAGE_CATEGORIES:
        raise ValidationFailed(
            f"{body.category!r} is not a damage category; expected one of "
            f"{', '.join(DAMAGE_CATEGORIES)}"
        )

    columns = _columns(
        body,
        client_operation_id=body.client_operation_id,
        assessed_by=UUID(principal.subject_id),
        correlation_id=correlation_id,
    )
    stored = await queries.insert_assessment(session, **columns)

    if stored is None:
        existing = await queries.assessment_by_operation_id(session, body.client_operation_id)
        if existing is not None:
            return {**existing, "duplicate": True}
        raise Conflict(
            "this operation id is already on record but the assessment it created is not "
            "visible from your scope"
        )

    _emit_submitted(session, stored, body)
    return {**stored, "duplicate": False}


@router.post("/assessments/sync", response_model=SyncResponse)
async def sync_assessments(
    body: SyncRequest,
    session: SessionDep,
    correlation_id: CorrelationDep,
    principal: Principal = WritePrincipal,
) -> Any:
    """Apply a batch from one field device, in sequence order, stopping at the first gap.

    Safe to replay in full, and expected to be. Operations already stored come back as
    `duplicate`; a gap in the device sequence reports the missing `seq` and holds
    everything after it as `blocked` rather than applying out of order.

    The device cursor is locked for the length of the transaction, so five concurrent
    copies of the same fifty-operation batch leave exactly fifty assessments.
    """
    cursor = await queries.lock_device_cursor(session, body.device_id)

    operations = [
        sync.SyncOperation(
            client_operation_id=item.client_operation_id,
            op=item.op,
            seq=item.seq,
            payload=item.payload.model_dump(),
            target=item.target,
        )
        for item in body.operations
    ]
    by_id = {item.client_operation_id: item for item in body.operations}

    already = await queries.applied_operation_ids(
        session, [item.client_operation_id for item in body.operations]
    )

    try:
        planned = sync.plan(
            operations,
            last_applied_seq=int(cursor["last_applied_seq"]),
            already_applied=already,
        )
    except sync.SyncRefused as error:
        raise ValidationFailed(str(error)) from error

    results = list(planned.results)
    applied_seq = int(cursor["last_applied_seq"])

    for operation in planned.to_apply:
        item = by_id[operation.client_operation_id]

        if item.payload.category not in DAMAGE_CATEGORIES:
            results.append(
                sync.SyncResult(
                    operation.client_operation_id,
                    sync.OperationStatus.CONFLICT,
                    conflict={"reason": "unknown_category", "category": item.payload.category},
                    detail=(
                        f"{item.payload.category!r} is not a damage category. The device "
                        "is running against a schedule this server does not have."
                    ),
                )
            )
            continue

        columns = _columns(
            item.payload,
            client_operation_id=operation.client_operation_id,
            assessed_by=UUID(principal.subject_id),
            correlation_id=correlation_id,
        )
        stored = await queries.insert_assessment(session, **columns)

        if stored is None:
            # Another copy of this batch won the race between the read and the insert.
            # A duplicate, not a failure - the assessment exists either way.
            results.append(
                sync.SyncResult(operation.client_operation_id, sync.OperationStatus.DUPLICATE)
            )
        else:
            _emit_submitted(session, stored, item.payload)
            results.append(
                sync.SyncResult(
                    operation.client_operation_id,
                    sync.OperationStatus.APPLIED,
                    server_id=UUID(stored["id"]),
                )
            )
        applied_seq = max(applied_seq, operation.seq)

    # Duplicates advance the cursor too: they are on record, so holding the cursor behind
    # them would make a device replay its whole log on every sync forever.
    for result in results:
        if result.status is sync.OperationStatus.DUPLICATE:
            applied_seq = max(applied_seq, by_id[result.client_operation_id].seq)

    saved = await queries.save_device_cursor(
        session,
        device_id=body.device_id,
        last_applied_seq=applied_seq,
        blocked_on_seq=planned.missing_seq,
    )

    if planned.paused:
        _log.warning(
            "device_sync_paused",
            device_id=body.device_id,
            missing_seq=planned.missing_seq,
            cursor=saved["last_applied_seq"],
        )

    ordered = {item.client_operation_id: index for index, item in enumerate(body.operations)}
    results.sort(key=lambda result: ordered.get(result.client_operation_id, 0))

    return {
        "device_id": body.device_id,
        "results": [result.as_dict() for result in results],
        "applied": sum(1 for r in results if r.status is sync.OperationStatus.APPLIED),
        "device_cursor": int(saved["last_applied_seq"]),
        "missing_seq": planned.missing_seq,
    }


@router.get("/assessments", response_model=list[AssessmentSummary])
async def list_assessments(
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    status: str | None = Query(default=None),
    division: str | None = Query(default=None, max_length=16),
    hazard_event_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    return await queries.list_assessments(
        session,
        status=status,
        division=division,
        hazard_event_id=hazard_event_id,
        limit=limit,
        offset=offset,
    )


@router.get("/assessments/{assessment_id}", response_model=AssessmentSummary)
async def read_assessment(
    assessment_id: UUID,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
) -> Any:
    found = await queries.get_assessment(session, assessment_id)
    if found is None:
        raise NotFound("No such assessment.")
    return found


@router.post("/assessments/{assessment_id}/accept", response_model=AssessmentSummary)
async def accept_assessment(
    assessment_id: UUID,
    body: ReviewRequest,
    session: SessionDep,
    correlation_id: CorrelationDep,
    principal: Principal = ReviewPrincipal,
) -> Any:
    """Accept an assessment, making it eligible for calculation.

    Refused if the reviewer wrote it. One person who can assess and accept has removed the
    first of the three checks that stand between a damage figure and a payment, and there
    is no reason for that path to exist.
    """
    found = await queries.get_assessment(session, assessment_id)
    if found is None:
        raise NotFound("No such assessment.")

    if found["assessed_by"] == principal.subject_id:
        raise Conflict(
            "the officer who wrote this assessment may not also accept it; ask a "
            "colleague to review it"
        )

    if found["evidence_hash"] is None:
        raise ValidationFailed(
            "this assessment carries no evidence hash, and an accepted assessment must. "
            "Upload the photographs and retry - a figure nobody can check is the opacity "
            "this ledger exists to replace."
        )

    updated = await queries.set_assessment_status(session, assessment_id, "ACCEPTED")
    if updated is None:
        raise Conflict(
            f"this assessment is {found['status']}, and only a SUBMITTED or UNDER_REVIEW "
            "assessment can be accepted"
        )

    _log.info("assessment_accepted", public_ref=updated["public_ref"])
    return {**found, **updated}


@router.post("/assessments/{assessment_id}/reject", response_model=AssessmentSummary)
async def reject_assessment(
    assessment_id: UUID,
    body: ReviewRequest,
    session: SessionDep,
    principal: Principal = ReviewPrincipal,
) -> Any:
    """Reject an assessment. The reason is required and reaches the household.

    A rejection without a reason is not reviewable, and leaves the household no grounds on
    which to raise a grievance - which is the point of having one.
    """
    if not (body.reason or "").strip():
        raise ValidationFailed(
            "a rejection needs a reason. The household can dispute this decision, and a "
            "refusal that gives no grounds leaves them nothing to dispute."
        )

    found = await queries.get_assessment(session, assessment_id)
    if found is None:
        raise NotFound("No such assessment.")

    updated = await queries.set_assessment_status(session, assessment_id, "REJECTED")
    if updated is None:
        raise Conflict(f"this assessment is {found['status']} and cannot be rejected")

    _log.info(
        "assessment_rejected",
        public_ref=updated["public_ref"],
        reason_length=len(body.reason or ""),
    )
    return {**found, **updated}
