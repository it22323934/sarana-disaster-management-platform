"""Exactly-once side effects, built from at-least-once delivery.

No broker gives exactly-once delivery. What a system can have is at-least-once delivery
plus idempotent consumers, and the combination is indistinguishable from exactly-once at
the only place it matters: the side effects.

The guard is a row. A handler records the event id in `processed_event` **in the same
transaction as its own writes**, so either both commit or neither does. A redelivery then
finds the row and returns without doing anything. Recording it in a separate transaction
would leave a window where the work committed and the record did not, which is precisely
the case that produces a duplicate payment.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, Final, cast
from uuid import UUID

import structlog
from sqlalchemy import CursorResult, DateTime, Index, String, Text, func, select, update
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from sarana_shared.db.base import Base
from sarana_shared.events.envelope import EventEnvelope

_log = structlog.get_logger(__name__)

PROCESSED_SCHEMA: Final = "outbox"

# Kept for 30 days, then partitioned away. Long enough to cover any redelivery a broker
# will produce and any replay window an operator will ask for; short enough that the
# table does not become the largest thing in the database.
RETENTION: Final = timedelta(days=30)


class ProcessedEvent(Base):
    """One (consumer group, event) pair that has already been handled.

    Keyed on the group as well as the event: two consumer groups both process every
    event, and they are independent. A single-column key would mean whichever group got
    there first silently suppressed the other.
    """

    __tablename__ = "processed_event"
    __table_args__ = (
        Index("ix_processed_event_processed_at", "processed_at"),
        {"schema": PROCESSED_SCHEMA},
    )

    consumer_group: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)

    event_type: Mapped[str] = mapped_column(String(200), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # What the handler did, for an operator reconstructing a run. Never the payload.
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)


async def seen(session: AsyncSession, group: str, event_id: UUID) -> bool:
    """Whether this consumer group has already handled this event."""
    result = await session.execute(
        select(ProcessedEvent.event_id).where(
            ProcessedEvent.consumer_group == group,
            ProcessedEvent.event_id == event_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def mark_processed(
    session: AsyncSession,
    group: str,
    envelope: EventEnvelope,
    *,
    outcome: str | None = None,
) -> bool:
    """Record that this group handled this event. Returns False if it already had.

    `ON CONFLICT DO NOTHING` rather than a check-then-insert: a hundred concurrent
    deliveries of the same envelope all reach the check at once and all pass it, and the
    unique constraint is the only thing that actually serialises them.
    """
    statement = (
        insert(ProcessedEvent)
        .values(
            consumer_group=group,
            event_id=envelope.event_id,
            event_type=envelope.event_type,
            correlation_id=envelope.correlation_id,
            outcome=outcome,
        )
        .on_conflict_do_nothing(index_elements=["consumer_group", "event_id"])
        .returning(ProcessedEvent.event_id)
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none() is not None


async def once(
    session: AsyncSession,
    group: str,
    envelope: EventEnvelope,
    handler: Callable[[AsyncSession, EventEnvelope], Awaitable[str | None]],
) -> bool:
    """Run a handler at most once per (group, event), in one transaction.

    Returns True if the handler ran, False if this delivery was a duplicate.

    The claim marker is inserted *first*. Two concurrent deliveries race on the unique
    constraint, exactly one wins, and the loser returns without touching anything. Doing
    the work first and recording afterwards would let both do the work.

    This function does not commit. The caller commits, which is what puts the handler's
    writes and the claim in the same transaction - the whole point of the pattern.
    """
    claimed = await mark_processed(session, group, envelope)
    if not claimed:
        _log.debug(
            "event_already_processed",
            consumer_group=group,
            event_id=str(envelope.event_id),
            event_type=envelope.event_type,
        )
        return False

    outcome = await handler(session, envelope)
    if outcome is not None:
        await session.execute(
            update(ProcessedEvent)
            .where(
                ProcessedEvent.consumer_group == group,
                ProcessedEvent.event_id == envelope.event_id,
            )
            .values(outcome=outcome)
        )
    return True


async def prune(session: AsyncSession, *, older_than: timedelta = RETENTION) -> int:
    """Delete idempotency records past their retention. Returns how many.

    Run on a schedule. The table only needs to remember long enough to cover any
    redelivery a broker will produce and any replay window an operator will ask for.
    """
    from sqlalchemy import delete

    from sarana_shared.domain.time import utc_now

    result = cast(
        "CursorResult[Any]",
        await session.execute(
            delete(ProcessedEvent).where(ProcessedEvent.processed_at < utc_now() - older_than)
        ),
    )
    return int(result.rowcount or 0)
