"""Incidents: the queue a dispatcher works from.

The queue endpoint says how it was ordered. That is not decoration - a dispatcher who
believes an ordered list came from a model when it came from a rule (or the reverse) will
trust it wrongly in both directions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from incident_svc.api.deps import CorrelationDep, SessionDep
from incident_svc.domain import state_machine, triage
from incident_svc.repo import queries
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.errors import Conflict, NotFound, ValidationFailed

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["incidents"])

ReadPrincipal = Depends(require(Scope.INCIDENT_READ))
WritePrincipal = Depends(require(Scope.INCIDENT_WRITE))
VerifyPrincipal = Depends(require(Scope.INCIDENT_VERIFY))


class IncidentSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    public_ref: str
    gn_division_code: str
    type: str
    status: str
    people_at_risk: int
    severity: int
    first_reported_at: datetime
    lon: float | None = None
    lat: float | None = None


class QueueEntry(IncidentSummary):
    """One incident in the dispatcher's queue, with why it sits where it does."""

    score: float | None = None
    model_version: str | None = None
    factors: dict[str, Any] | None = None


class QueueResponse(BaseModel):
    """The queue, and an unmissable statement of how it was ordered."""

    model_config = ConfigDict(frozen=True)

    assisted: bool = Field(
        description="True only when agent-assisted ranking produced these scores."
    )
    banner: str | None = Field(
        default=None,
        description="Shown verbatim in the console when assisted triage is unavailable.",
    )
    ordering: str = Field(description="The rule or model that ordered this list.")
    entries: list[QueueEntry]


class StatusPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(max_length=24)


class MergeRequest(BaseModel):
    """Fold one incident into another. Always a human decision."""

    model_config = ConfigDict(extra="forbid")

    into_incident_id: UUID
    reason: str = Field(min_length=3, max_length=500)


class SplitRequest(BaseModel):
    """Undo a bad automatic dedup."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


ASSISTED_UNAVAILABLE_BANNER = "Assisted triage unavailable - manual ordering"


def _parse_bbox(raw: str | None) -> tuple[float, float, float, float] | None:
    if raw is None:
        return None
    parts = raw.split(",")
    if len(parts) != 4:
        raise ValidationFailed(
            "bbox must be four comma-separated numbers: min_lon,min_lat,max_lon,max_lat"
        )
    try:
        min_lon, min_lat, max_lon, max_lat = (float(part) for part in parts)
    except ValueError as error:
        raise ValidationFailed("bbox values must be numbers") from error
    if min_lon >= max_lon or min_lat >= max_lat:
        raise ValidationFailed("bbox minimums must be smaller than its maximums")
    return min_lon, min_lat, max_lon, max_lat


@router.get("/incidents", response_model=list[IncidentSummary])
async def list_incidents(
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    status_filter: str | None = Query(default=None, alias="status", max_length=24),
    gn: str | None = Query(default=None, max_length=16),
    bbox: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Any:
    return await queries.list_incidents(
        session,
        status=status_filter,
        gn=gn,
        since=since,
        bbox=_parse_bbox(bbox),
        limit=limit,
        offset=offset,
    )


@router.get("/incidents/queue", response_model=QueueResponse)
async def incident_queue(
    request: Request,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    limit: int = Query(default=200, ge=1, le=1000),
) -> Any:
    """The dispatcher's main view, ordered most urgent first.

    Incidents with no stored score are ranked by the same published rule rather than being
    dropped to the bottom. An unranked incident at the end of a long queue is one nobody
    reaches, which is the failure this endpoint exists to prevent.
    """
    rows = await queries.queue_rows(session)
    assisted = bool(getattr(request.app.state, "assisted_triage", False))

    entries: list[dict[str, Any]] = []
    for row in rows:
        stored = row.get("score")
        factors: Any = row.get("factors")
        model_version: str | None
        if stored is None:
            # Never dropped to the bottom. An incident nobody has scored is still an
            # incident, and one sitting unranked at the end of a long queue is one nobody
            # reaches.
            computed = triage.score_row(row)
            score = computed.score
            factors = computed.factors
            model_version = computed.model_version
        else:
            score = float(stored)
            model_version = row.get("model_version")
        entries.append({**row, "score": score, "factors": factors, "model_version": model_version})

    entries.sort(key=lambda entry: (-(entry["score"] or 0.0), entry["first_reported_at"]))

    return {
        "assisted": assisted,
        "banner": None if assisted else ASSISTED_UNAVAILABLE_BANNER,
        "ordering": "agent-assisted" if assisted else triage.MODEL_VERSION,
        "entries": entries[:limit],
    }


@router.get("/incidents/{incident_id}")
async def get_incident(
    incident_id: UUID,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
) -> Any:
    """One incident, with its linked reports and triage factors."""
    row = await queries.get_incident(session, incident_id)
    if row is None:
        raise NotFound("No such incident.", context={"incident_id": str(incident_id)})
    return row


@router.patch("/incidents/{incident_id}", response_model=IncidentSummary)
async def patch_incident(
    incident_id: UUID,
    body: StatusPatch,
    session: SessionDep,
    correlation_id: CorrelationDep,
    principal: Principal = VerifyPrincipal,
) -> Any:
    """Move an incident through the state machine.

    An illegal transition is a 409 naming both states, and it is audited. Silently
    accepting one would let a resolved incident be reopened by a stale client and quietly
    re-enter the queue.
    """
    current = await queries.get_incident(session, incident_id)
    if current is None:
        raise NotFound("No such incident.", context={"incident_id": str(incident_id)})

    try:
        state_machine.assert_transition(
            "incident", str(incident_id), current["status"], body.status
        )
    except state_machine.IllegalTransition as error:
        _log.warning(
            "illegal_incident_transition",
            incident_id=str(incident_id),
            current=current["status"],
            requested=body.status,
            actor=principal.subject_id,
        )
        raise Conflict(
            str(error),
            context={
                "incident_id": str(incident_id),
                "current": current["status"],
                "requested": body.status,
            },
        ) from error

    await queries.set_incident_status(session, incident_id, body.status)
    return await queries.get_incident(session, incident_id)


@router.post("/incidents/{incident_id}/merge", response_model=IncidentSummary)
async def merge_incident(
    incident_id: UUID,
    body: MergeRequest,
    session: SessionDep,
    principal: Principal = VerifyPrincipal,
) -> Any:
    """Fold this incident into another. Requires a reason, and is audited.

    Never automatic. A wrong merge hides a second emergency behind the first: one team is
    sent, and the other household waits for someone who is not coming.
    """
    current = await queries.get_incident(session, incident_id)
    if current is None:
        raise NotFound("No such incident.", context={"incident_id": str(incident_id)})
    target = await queries.get_incident(session, body.into_incident_id)
    if target is None:
        raise NotFound(
            "No such incident to merge into.",
            context={"incident_id": str(body.into_incident_id)},
        )
    if incident_id == body.into_incident_id:
        raise ValidationFailed("an incident cannot be merged into itself")

    try:
        state_machine.assert_transition(
            "incident", str(incident_id), current["status"], "DUPLICATE"
        )
    except state_machine.IllegalTransition as error:
        raise Conflict(str(error)) from error

    cluster_id = target.get("cluster_id") or body.into_incident_id
    await queries.set_cluster(
        session, body.into_incident_id, cluster_id=UUID(str(cluster_id)), primary=True
    )
    await queries.set_cluster(session, incident_id, cluster_id=UUID(str(cluster_id)), primary=False)
    await queries.set_incident_status(session, incident_id, "DUPLICATE")

    _log.info(
        "incident_merged",
        incident_id=str(incident_id),
        into=str(body.into_incident_id),
        reason=body.reason,
        actor=principal.subject_id,
    )
    return await queries.get_incident(session, incident_id)


@router.post("/incidents/{incident_id}/split", response_model=IncidentSummary)
async def split_incident(
    incident_id: UUID,
    body: SplitRequest,
    session: SessionDep,
    principal: Principal = VerifyPrincipal,
) -> Any:
    """Undo a merge, returning the incident to the queue.

    Back to TRIAGED rather than to where it started: it is a real incident that has been
    waiting, and sending it to the back of the queue would punish it for our mistake.
    """
    current = await queries.get_incident(session, incident_id)
    if current is None:
        raise NotFound("No such incident.", context={"incident_id": str(incident_id)})

    try:
        state_machine.assert_transition("incident", str(incident_id), current["status"], "TRIAGED")
    except state_machine.IllegalTransition as error:
        raise Conflict(str(error)) from error

    await queries.set_cluster(session, incident_id, cluster_id=None, primary=True)
    await queries.set_incident_status(session, incident_id, "TRIAGED")

    _log.info(
        "incident_split",
        incident_id=str(incident_id),
        reason=body.reason,
        actor=principal.subject_id,
    )
    return await queries.get_incident(session, incident_id)
