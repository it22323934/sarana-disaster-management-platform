"""Dead letters: what happens to an event no consumer could handle.

Three attempts with exponential backoff and jitter, then the envelope and every failure's
traceback go to the dead-letter queue.

A silent DLQ is the failure mode that kills trust in an event system. Someone looks at a
dashboard, sees no errors, and concludes the pipeline is healthy - while a hundred
assessments quietly failed to become entitlements. So a non-empty DLQ raises an alarm, and
a redrive is an explicit operator action after a fix, not an automatic retry that hides the
problem for another cycle.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

import structlog
from sqlalchemy import DateTime, Index, Integer, String, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from sarana_shared.db.base import Base
from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now
from sarana_shared.events.envelope import EventEnvelope

_log = structlog.get_logger(__name__)

DLQ_SCHEMA: Final = "outbox"

MAX_ATTEMPTS: Final = 3

BASE_BACKOFF: Final = timedelta(seconds=2)

# Jitter stops a batch of failures retrying in lockstep. Without it, a hundred consumers
# that failed together retry together, hit the same still-broken dependency together, and
# fail together again - a thundering herd that looks like the dependency getting worse.
JITTER_FRACTION: Final = 0.25


def backoff_for(attempt: int, *, rng: random.Random | None = None) -> timedelta:
    """Delay before retry `attempt`, doubling with jitter.

    Attempt 1 is the first retry, not the first delivery.
    """
    if attempt < 1:
        return timedelta(0)
    base: timedelta = BASE_BACKOFF * (2 ** (attempt - 1))
    source = rng or random.SystemRandom()
    jitter: timedelta = base * (JITTER_FRACTION * (source.random() * 2 - 1))
    delayed: timedelta = base + jitter
    return delayed if delayed > timedelta(0) else timedelta(0)


class DeadLetter(Base):
    """One envelope that could not be handled, with the full failure history.

    The envelope is stored whole so a redrive needs nothing else, and the tracebacks are
    kept together so an operator can see whether three attempts failed the same way or
    three different ways - which is usually the difference between a broken dependency
    and a broken message.
    """

    __tablename__ = "dead_letter"
    __table_args__ = (
        Index("ix_dead_letter_unresolved", "created_at", "consumer_group"),
        {"schema": DLQ_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    consumer_group: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    failures: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    redriven_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    redriven_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)


async def record_failure(
    session: AsyncSession,
    *,
    consumer_group: str,
    envelope: EventEnvelope,
    error: BaseException,
    attempt: int,
    traceback_text: str,
) -> DeadLetter:
    """Append a failure. Creates the dead letter on the first one.

    Called on every failed attempt, not only the last, so the row shows the whole
    history rather than just how it ended.
    """
    result = await session.execute(
        select(DeadLetter).where(
            DeadLetter.consumer_group == consumer_group,
            DeadLetter.event_id == envelope.event_id,
            DeadLetter.redriven_at.is_(None),
        )
    )
    letter = result.scalar_one_or_none()

    failure = {
        "attempt": attempt,
        "at": utc_now().isoformat(),
        "error": f"{type(error).__name__}: {error}"[:2000],
        "traceback": traceback_text[:8000],
    }

    if letter is None:
        letter = DeadLetter(
            id=uuid7(),
            consumer_group=consumer_group,
            event_id=envelope.event_id,
            event_type=envelope.event_type,
            correlation_id=envelope.correlation_id,
            envelope=envelope.model_dump(mode="json"),
            failures=[failure],
            attempts=attempt,
        )
        session.add(letter)
    else:
        letter.failures = [*letter.failures, failure]
        letter.attempts = attempt

    _log.error(
        "event_handling_failed",
        consumer_group=consumer_group,
        event_type=envelope.event_type,
        event_id=str(envelope.event_id),
        correlation_id=str(envelope.correlation_id),
        attempt=attempt,
        exhausted=attempt >= MAX_ATTEMPTS,
    )
    return letter


async def pending(
    session: AsyncSession, *, consumer_group: str | None = None, limit: int = 100
) -> list[DeadLetter]:
    """Dead letters awaiting an operator. `GET /admin/dlq` reads this."""
    statement = select(DeadLetter).where(DeadLetter.redriven_at.is_(None))
    if consumer_group is not None:
        statement = statement.where(DeadLetter.consumer_group == consumer_group)
    result = await session.execute(statement.order_by(DeadLetter.created_at).limit(limit))
    return list(result.scalars().all())


async def pending_count(session: AsyncSession) -> int:
    """How many dead letters are waiting.

    Exported as a metric. A non-empty DLQ raises an alarm, because the alternative is a
    dashboard that looks healthy while a hundred assessments never became entitlements.
    """
    result = await session.execute(
        select(func.count()).select_from(DeadLetter).where(DeadLetter.redriven_at.is_(None))
    )
    return int(result.scalar_one())


async def redrive(
    session: AsyncSession, letter_id: UUID, *, requested_by: str, note: str | None = None
) -> EventEnvelope:
    """Mark one dead letter for retry and return its envelope.

    An explicit operator action after a fix, never an automatic retry. The caller
    republishes the returned envelope; marking and republishing are separate so both
    happen in the caller's transaction.

    Raises:
        LookupError: if the dead letter does not exist or was already redriven.
    """
    result = await session.execute(select(DeadLetter).where(DeadLetter.id == letter_id))
    letter = result.scalar_one_or_none()
    if letter is None:
        raise LookupError(f"no dead letter {letter_id}")
    if letter.redriven_at is not None:
        raise LookupError(
            f"dead letter {letter_id} was already redriven at "
            f"{letter.redriven_at.isoformat()} by {letter.redriven_by}"
        )

    letter.redriven_at = utc_now()
    letter.redriven_by = requested_by
    letter.resolution_note = note

    _log.info(
        "dead_letter_redriven",
        dead_letter_id=str(letter_id),
        event_type=letter.event_type,
        requested_by=requested_by,
    )
    # Redriving is a fresh delivery of the original event, not a replay: the event never
    # reached its consumer, so there is no side effect to guard against repeating.
    return EventEnvelope.model_validate(letter.envelope)
