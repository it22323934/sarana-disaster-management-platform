"""Reports: the citizen-facing intake surface.

An `Idempotency-Key` is required. A phone on a failing network retries, and a retry must
not become a second emergency in the queue - two teams sent to one house means one house
somewhere else gets nobody.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, ConfigDict, Field

from incident_svc.adapters.channels.intake import ReportIntake
from incident_svc.api.deps import CorrelationDep, SessionDep
from incident_svc.domain import media
from incident_svc.repo import queries
from incident_svc.service import intake as intake_service
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.errors import IdempotencyKeyRequired, NotFound, ValidationFailed

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["reports"])

WritePrincipal = Depends(require(Scope.INCIDENT_WRITE))
ReadPrincipal = Depends(require(Scope.INCIDENT_READ))


class ReportRequest(BaseModel):
    """A report submitted through the app or by an officer."""

    model_config = ConfigDict(extra="forbid")

    incident_type: str | None = Field(default=None, max_length=48)
    text: str | None = Field(default=None, max_length=4000)
    language: str | None = Field(default=None, max_length=2)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    location_accuracy_m: int | None = Field(default=None, gt=0, le=100_000)
    location_source: str | None = Field(default=None, max_length=16)
    people_at_risk: int | None = Field(default=None, ge=0, le=10_000)
    channel: str = Field(default="APP", max_length=16)


class DuplicateFlag(BaseModel):
    """A possible duplicate, for a human to judge."""

    model_config = ConfigDict(frozen=True)

    incident_id: str
    distance_m: float | None
    minutes_apart: float
    reason: str


class ReportResponse(BaseModel):
    """What a submitted report produced."""

    model_config = ConfigDict(frozen=True)

    report_id: str
    incident_id: str | None
    public_ref: str | None
    placed: bool = Field(
        description="False when the report could not be assigned a division. It is kept."
    )
    assisted_triage: bool = Field(
        description="False means the queue position came from the published rule, not a model."
    )
    duplicate_candidates: list[DuplicateFlag] = Field(
        default_factory=list,
        description="Flagged for a human. Nothing is merged automatically.",
    )


class ReportDetail(BaseModel):
    """One stored report."""

    model_config = ConfigDict(frozen=True)

    id: str
    channel: str
    processing_status: str
    raw_text: str | None
    reported_language: str | None
    lon: float | None
    lat: float | None
    location_accuracy_m: int | None
    location_source: str | None


class MediaRequest(BaseModel):
    """A client declaring what it is about to upload."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description="photo or audio")
    content_type: str = Field(max_length=80)
    size_bytes: int = Field(gt=0)
    duration_seconds: float | None = Field(default=None, gt=0)


class MediaGrant(BaseModel):
    """Where the client may put it."""

    model_config = ConfigDict(frozen=True)

    key: str
    content_type: str
    max_bytes: int
    expires_in: int


@router.post("/reports", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
async def submit_report(
    body: ReportRequest,
    request: Request,
    session: SessionDep,
    correlation_id: CorrelationDep,
    principal: Principal = WritePrincipal,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    """Accept one report.

    The key is required rather than optional. A retry on a flaky network is the normal
    case here, not an edge case, and a duplicated SOS costs a dispatcher's attention at
    the moment they have least of it.
    """
    if not idempotency_key:
        raise IdempotencyKeyRequired(
            "An Idempotency-Key header is required when submitting a report, so a retry "
            "on a failing network cannot become a second emergency in the queue."
        )

    if (body.lat is None) != (body.lng is None):
        raise ValidationFailed("lat and lng must be supplied together, or not at all")

    report = ReportIntake(
        channel=body.channel,
        correlation_id=correlation_id or str(idempotency_key),
        raw_text=body.text,
        reported_language=body.language,
        incident_type=body.incident_type,
        people_at_risk=body.people_at_risk,
        lon=body.lng,
        lat=body.lat,
        location_accuracy_m=body.location_accuracy_m,
        location_source=body.location_source,
        channel_metadata={"idempotency_key": idempotency_key},
    )

    result = await intake_service.accept(
        session,
        report,
        core_api=request.app.state.core_api,
        assisted=getattr(request.app.state, "assisted_triage", False),
    )

    return {
        "report_id": result.report_id,
        "incident_id": result.incident_id,
        "public_ref": result.public_ref,
        "placed": result.placed,
        "assisted_triage": result.assisted,
        "duplicate_candidates": result.duplicate_candidates,
    }


@router.get("/reports/{report_id}", response_model=ReportDetail)
async def get_report(
    report_id: UUID,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
) -> Any:
    row = await queries.get_report(session, report_id)
    if row is None:
        raise NotFound("No such report.", context={"report_id": str(report_id)})
    return row


@router.post("/reports/{report_id}/media", response_model=MediaGrant)
async def presign_media(
    report_id: UUID,
    body: MediaRequest,
    session: SessionDep,
    principal: Principal = WritePrincipal,
) -> Any:
    """Grant one upload, or refuse it before any bytes move.

    Refusing here rather than after the upload is the whole point: a citizen on a failing
    network who has just spent four minutes sending a photo should not then be told it
    was too large.
    """
    row = await queries.get_report(session, report_id)
    if row is None:
        raise NotFound("No such report.", context={"report_id": str(report_id)})

    request_model = media.UploadRequest(
        content_type=body.content_type,
        size_bytes=body.size_bytes,
        duration_seconds=body.duration_seconds,
    )

    try:
        if body.kind == "photo":
            grant = media.grant_for_photo(report_id, request_model)
        elif body.kind == "audio":
            grant = media.grant_for_audio(report_id, request_model)
        else:
            raise ValidationFailed(f"unknown media kind {body.kind!r}; expected photo or audio")
    except media.MediaRefused as error:
        raise ValidationFailed(str(error), context={"kind": body.kind}) from error

    return {
        "key": grant.key,
        "content_type": grant.content_type,
        "max_bytes": grant.max_bytes,
        "expires_in": grant.expires_in,
    }
