"""Event wiring for incident-svc.

Everything this service publishes goes through the outbox, never straight to the bus. A
domain write and its event commit together or not at all, so an event can never describe
a state change that did not happen - and a rolled-back transaction emits nothing.

Everything it consumes goes through `handle_idempotently`, which claims the event in
`processed_event` in the same transaction as the handler's own writes. A redelivery then
finds the claim and does nothing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from incident_svc.repo import OutboxEvent
from sarana_shared.domain.ids import ensure_correlation_uuid
from sarana_shared.events.envelope import EventEnvelope
from sarana_shared.events.idempotency import once
from sarana_shared.events.outbox import enqueue

_log = structlog.get_logger(__name__)

PRODUCER = "incident-svc"

# Every consumer group this service registers. Named for what it does, not for the
# service it lives in: a group outlives the process that happens to run it.
CONSUMER_GROUP = "incident_svc"


def publish(
    session: AsyncSession,
    event_type: str,
    payload: dict[str, Any],
    *,
    subject: str | None = None,
    causation: EventEnvelope | None = None,
    schema_version: int = 1,
) -> EventEnvelope:
    """Queue an event in this service's outbox, inside the caller's transaction.

    Does not commit and does not touch the bus. The publisher picks the row up once the
    caller's transaction commits, which is what makes the emission conditional on the
    write actually having happened.

    Pass `causation` when this event follows from one being handled, so the chain from
    the original citizen report stays intact.
    """
    if causation is not None:
        envelope = causation.caused(
            event_type,
            payload,
            producer=PRODUCER,
            subject=subject,
            schema_version=schema_version,
        )
    else:
        envelope = EventEnvelope(
            event_type=event_type,
            schema_version=schema_version,
            correlation_id=ensure_correlation_uuid(),
            producer=PRODUCER,
            subject=subject,
            payload=payload,
        )

    enqueue(session, OutboxEvent, envelope)
    _log.debug(
        "event_queued",
        event_type=envelope.event_type,
        event_id=str(envelope.event_id),
        correlation_id=str(envelope.correlation_id),
    )
    return envelope


async def handle_idempotently(
    session: AsyncSession,
    envelope: EventEnvelope,
    handler: Callable[[AsyncSession, EventEnvelope], Awaitable[str | None]],
    *,
    group: str = CONSUMER_GROUP,
) -> bool:
    """Run a handler at most once for this event. Returns False on a redelivery.

    Does not commit: the caller does, which is what puts the handler's writes and the
    idempotency claim in one transaction.
    """
    return await once(session, group, envelope, handler)
