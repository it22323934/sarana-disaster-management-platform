"""Killing the publisher mid-batch must lose nothing and duplicate no side effects.

Named in the Definition of Done. The scenario is a deploy, an OOM kill, or a Fargate task
being rotated while the outbox has a backlog - all of which happen, and the last of which
happens most during a surge, which is exactly when losing an event matters most.

The property: a row is marked published only after its publish returns. Anything the
process had not acknowledged when it died is still unpublished, so the next process picks
it up. The duplicate that produces downstream is absorbed by `processed_event`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sarana_shared.domain.ids import uuid7
from sarana_shared.events.envelope import EventEnvelope
from sarana_shared.events.impl.in_memory import InMemoryEventBus
from sarana_shared.events.outbox import OutboxPublisher, enqueue
from tests.events.conftest import OutboxEvent

pytestmark = pytest.mark.asyncio(loop_scope="session")


class DyingBus(InMemoryEventBus):
    """A bus that stops working part-way through, the way a killed process does."""

    def __init__(self, die_after: int) -> None:
        super().__init__()
        self.die_after = die_after
        self.attempts = 0

    async def publish(self, envelope: EventEnvelope) -> None:
        self.attempts += 1
        if self.attempts > self.die_after:
            raise ConnectionError("broker unreachable: the publisher died here")
        await super().publish(envelope)


async def _fill(
    session_factory: async_sessionmaker[AsyncSession], count: int
) -> list[EventEnvelope]:
    envelopes = [
        EventEnvelope(
            event_type="sarana.incident.report.received",
            producer="core-api",
            correlation_id=uuid7(),
            payload={"report_id": str(uuid7()), "channel": "SMS"},
        )
        for _ in range(count)
    ]
    async with session_factory() as session:
        for envelope in envelopes:
            enqueue(session, OutboxEvent, envelope)
        await session.commit()
    return envelopes


async def test_a_publisher_that_dies_mid_batch_loses_nothing(
    session_factory: async_sessionmaker[AsyncSession], clean_outbox: None
) -> None:
    """Six events, a publisher that dies after four, then a fresh one."""
    envelopes = await _fill(session_factory, 6)

    dying = DyingBus(die_after=4)
    await OutboxPublisher(session_factory, dying, OutboxEvent, batch_size=10).drain_once()

    assert len(dying.published) == 4

    # A new process, a working bus. The two it never acknowledged are still queued.
    healthy = InMemoryEventBus()
    recovered = await OutboxPublisher(session_factory, healthy, OutboxEvent).drain()

    assert recovered == 2
    delivered = {e.event_id for e in dying.published} | {e.event_id for e in healthy.published}
    assert delivered == {e.event_id for e in envelopes}


async def test_every_event_arrives_exactly_once_across_the_crash(
    session_factory: async_sessionmaker[AsyncSession], clean_outbox: None
) -> None:
    """No event is published twice, and none is skipped."""
    envelopes = await _fill(session_factory, 10)

    dying = DyingBus(die_after=3)
    await OutboxPublisher(session_factory, dying, OutboxEvent, batch_size=10).drain_once()

    healthy = InMemoryEventBus()
    await OutboxPublisher(session_factory, healthy, OutboxEvent).drain()

    all_delivered = [e.event_id for e in dying.published] + [e.event_id for e in healthy.published]

    assert len(all_delivered) == len(envelopes)
    assert len(set(all_delivered)) == len(envelopes), "an event was delivered twice"


async def test_a_failed_row_records_why_and_is_retried(
    session_factory: async_sessionmaker[AsyncSession], clean_outbox: None
) -> None:
    """A stuck event is evidence. The reason has to be on the row, not only in a log."""
    await _fill(session_factory, 1)

    await OutboxPublisher(session_factory, DyingBus(die_after=0), OutboxEvent).drain_once()

    async with session_factory() as session:
        result = await session.execute(
            text("SELECT attempts, last_error, published_at FROM outbox.core_api_event")
        )
        attempts, last_error, published_at = result.one()

    assert attempts == 1
    assert "broker unreachable" in last_error
    assert published_at is None

    healthy = InMemoryEventBus()
    assert await OutboxPublisher(session_factory, healthy, OutboxEvent).drain() == 1


async def test_a_row_that_exhausts_its_retries_is_kept_not_dropped(
    session_factory: async_sessionmaker[AsyncSession], clean_outbox: None
) -> None:
    """A state change committed and the platform never heard about it.

    That is a thing an operator must be able to find, so the row stays and stops being
    retried rather than disappearing into a log line.
    """
    from sarana_shared.events.outbox import (
        MAX_PUBLISH_ATTEMPTS,
        reset_stuck_events,
        stuck_event_count,
    )

    await _fill(session_factory, 1)

    dead = DyingBus(die_after=0)
    publisher = OutboxPublisher(session_factory, dead, OutboxEvent)
    for _ in range(MAX_PUBLISH_ATTEMPTS + 2):
        await publisher.drain_once()

    async with session_factory() as session:
        stuck = await stuck_event_count(session, OutboxEvent)
        rows = await session.execute(text("SELECT count(*) FROM outbox.core_api_event"))

    assert stuck == 1
    assert rows.scalar_one() == 1, "the event was dropped instead of kept for an operator"

    # After the cause is fixed, an operator clears the counter and it flows again.
    async with session_factory() as session:
        reset = await reset_stuck_events(session, OutboxEvent)
        await session.commit()

    assert reset == 1
    healthy = InMemoryEventBus()
    assert await OutboxPublisher(session_factory, healthy, OutboxEvent).drain() == 1
