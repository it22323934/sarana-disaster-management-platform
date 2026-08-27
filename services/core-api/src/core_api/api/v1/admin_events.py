"""Operator endpoints for replay and dead letters.

Both are ADMIN-only, both write an audit entry, and both are deliberately awkward in the
same way: they name exactly what they will touch. A replay states its window, its event
types and its one target group; a redrive names one dead letter. Neither has a
do-everything form, because the mistakes those would enable are not recoverable on a
platform that sends messages to citizens and moves money to households.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from core_api.api.deps import SessionDep
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.errors import Conflict, NotFound
from sarana_shared.events import dlq
from sarana_shared.events.replay import ReplayInProgress, ReplayRefused

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["operations"])

AdminPrincipal = Depends(require(Scope.SYSTEM_ADMIN))


class ReplayRequest(BaseModel):
    """A replay, scoped to a window, some event types and one consumer group."""

    model_config = ConfigDict(extra="forbid")

    since: datetime
    until: datetime | None = None
    event_types: list[str] = Field(
        min_length=1,
        description="Which events to replay. There is no replay-everything form.",
    )
    target_group: str = Field(min_length=1, description="Exactly one consumer group")
    allow_wide_window: bool = Field(
        default=False,
        description="Override the 30-day guard. Usually a typo, occasionally intended.",
    )


class ReplayResponse(BaseModel):
    """What a replay did."""

    model_config = ConfigDict(frozen=True)

    replay_id: UUID
    target_group: str
    event_types: list[str]
    delivered: int
    refused: int = Field(description="Envelopes a side-effecting consumer declined. Not an error.")
    started_at: datetime
    finished_at: datetime | None


class DeadLetterSummary(BaseModel):
    """One dead letter, without its payload.

    The envelope is deliberately omitted from the list view: a DLQ listing is read on a
    dashboard by whoever is on call, and it should not put every failed event's contents
    on a screen in an operations room.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID
    consumer_group: str
    event_type: str
    event_id: UUID
    correlation_id: UUID
    attempts: int
    created_at: datetime
    last_error: str | None


class RedriveRequest(BaseModel):
    """Retry one dead letter after the underlying cause is fixed."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(
        default=None, max_length=500, description="What was fixed. Recorded on the row."
    )


@router.post("/replay", response_model=ReplayResponse)
async def start_replay(
    body: ReplayRequest,
    request: Request,
    principal: Principal = AdminPrincipal,
) -> ReplayResponse:
    """Re-deliver a window of history to one consumer group.

    Consumers with real-world side effects refuse replayed envelopes, so a replay cannot
    re-send an SMS about a cyclone that passed or re-release a payment. The refusal count
    comes back in the response rather than being hidden: an operator should see that some
    consumers declined, and that it was on purpose.

    One replay runs at a time. Two overlapping ones would make the delivered counts
    meaningless and could double-deliver to the same group.
    """
    coordinator = request.app.state.replay_coordinator

    try:
        handle = await coordinator.start(
            since=body.since,
            until=body.until,
            event_types=tuple(body.event_types),
            target_group=body.target_group,
            requested_by=principal.subject_id,
            allow_wide_window=body.allow_wide_window,
        )
    except ReplayInProgress as exc:
        raise Conflict(str(exc), context={"subject_id": principal.subject_id}) from exc
    except ReplayRefused as exc:
        from sarana_shared.errors import ValidationFailed

        raise ValidationFailed(str(exc), context={"subject_id": principal.subject_id}) from exc

    _log.info(
        "replay_requested",
        replay_id=str(handle.replay_id),
        requested_by=principal.subject_id,
        target_group=handle.target_group,
        event_types=list(handle.event_types),
        delivered=handle.delivered,
        refused=handle.refused,
    )

    return ReplayResponse(
        replay_id=handle.replay_id,
        target_group=handle.target_group,
        event_types=list(handle.event_types),
        delivered=handle.delivered,
        refused=handle.refused,
        started_at=handle.started_at,
        finished_at=handle.finished_at,
    )


@router.get("/dlq", response_model=list[DeadLetterSummary])
async def list_dead_letters(
    session: SessionDep,
    principal: Principal = AdminPrincipal,
    consumer_group: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[DeadLetterSummary]:
    """Events no consumer could handle.

    A non-empty list means something committed and the platform never acted on it. It
    raises an alarm as well as appearing here, because the failure mode this guards
    against is nobody looking.
    """
    letters = await dlq.pending(session, consumer_group=consumer_group, limit=limit)

    return [
        DeadLetterSummary(
            id=letter.id,
            consumer_group=letter.consumer_group,
            event_type=letter.event_type,
            event_id=letter.event_id,
            correlation_id=letter.correlation_id,
            attempts=letter.attempts,
            created_at=letter.created_at,
            last_error=letter.failures[-1].get("error") if letter.failures else None,
        )
        for letter in letters
    ]


@router.post("/dlq/{letter_id}/redrive", status_code=status.HTTP_202_ACCEPTED)
async def redrive_dead_letter(
    letter_id: UUID,
    body: RedriveRequest,
    request: Request,
    session: SessionDep,
    principal: Principal = AdminPrincipal,
) -> dict[str, str]:
    """Retry one dead letter after the cause is fixed.

    An explicit operator action, never an automatic retry: an automatic one would hide
    the problem for another cycle, which is how a DLQ ends up quietly full.

    The event is republished as a first delivery, not a replay. It never reached its
    consumer, so there is no side effect to guard against repeating.
    """
    try:
        envelope = await dlq.redrive(
            session, letter_id, requested_by=principal.subject_id, note=body.note
        )
    except LookupError as exc:
        raise NotFound(str(exc), context={"dead_letter_id": str(letter_id)}) from exc

    await request.app.state.event_bus.publish(envelope)

    _log.info(
        "dead_letter_redriven",
        dead_letter_id=str(letter_id),
        event_type=envelope.event_type,
        requested_by=principal.subject_id,
    )
    return {"status": "republished", "event_id": str(envelope.event_id)}
