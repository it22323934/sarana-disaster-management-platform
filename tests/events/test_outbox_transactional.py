"""The outbox's central promise: an event exists exactly when the write it describes does.

This is what the pattern is for. Publishing to a broker inside a transaction that then
rolls back would tell the whole platform something happened that did not; committing the
write and then failing to publish would leave the platform never hearing about something
that did. One transaction covering both removes the window in either direction.
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


def an_envelope(event_type: str = "sarana.incident.report.received") -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        producer="core-api",
        correlation_id=uuid7(),
        payload={"report_id": str(uuid7()), "channel": "SMS"},
    )


async def test_a_rolled_back_transaction_emits_nothing(
    session_factory: async_sessionmaker[AsyncSession],
    bus: InMemoryEventBus,
    clean_outbox: None,
) -> None:
    """The first required case: publish inside a transaction that then rolls back."""
    async with session_factory() as session:
        enqueue(session, OutboxEvent, an_envelope())
        await session.flush()
        await session.rollback()

    published = await OutboxPublisher(session_factory, bus, OutboxEvent).drain()

    assert published == 0
    assert bus.published == []


async def test_a_committed_transaction_emits_exactly_once(
    session_factory: async_sessionmaker[AsyncSession],
    bus: InMemoryEventBus,
    clean_outbox: None,
) -> None:
    async with session_factory() as session:
        enqueue(session, OutboxEvent, an_envelope())
        await session.commit()

    publisher = OutboxPublisher(session_factory, bus, OutboxEvent)

    assert await publisher.drain() == 1
    # Draining again publishes nothing: the row is marked, not deleted.
    assert await publisher.drain() == 0
    assert len(bus.published) == 1


async def test_the_domain_write_and_its_event_commit_together(
    session_factory: async_sessionmaker[AsyncSession],
    bus: InMemoryEventBus,
    clean_outbox: None,
) -> None:
    """A failure after the domain write must take the event with it."""
    with pytest.raises(RuntimeError, match="payment rail unreachable"):
        async with session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO admin.province (id, code, name) VALUES "
                    '(:id, \'LK-P09\', \'{"si":"a","ta":"b","en":"c"}\'::jsonb)'
                ),
                {"id": uuid7()},
            )
            enqueue(session, OutboxEvent, an_envelope())
            await session.flush()
            raise RuntimeError("payment rail unreachable")

    async with session_factory() as session:
        rows = await session.execute(text("SELECT count(*) FROM outbox.core_api_event"))
        provinces = await session.execute(
            text("SELECT count(*) FROM admin.province WHERE code = 'LK-P09'")
        )

    assert rows.scalar_one() == 0, "the event outlived the write that justified it"
    assert provinces.scalar_one() == 0, "the write outlived the transaction"


async def test_the_envelope_survives_the_round_trip(
    session_factory: async_sessionmaker[AsyncSession],
    bus: InMemoryEventBus,
    clean_outbox: None,
) -> None:
    """What comes off the outbox must be what went in, field for field.

    The chain from a citizen report to a disbursement is only reconstructable if the
    correlation and causation ids survive storage.
    """
    original = an_envelope()
    follow_on = original.caused(
        "sarana.incident.verified",
        {
            "incident_id": str(uuid7()),
            "public_ref": "INC-251128-K3M9PQ",
            "gn_division_code": "LK-11-03-045",
            "incident_type": "FLOOD",
            "severity": 4,
            "people_at_risk": 12,
        },
        producer="incident-svc",
    )

    async with session_factory() as session:
        enqueue(session, OutboxEvent, follow_on)
        await session.commit()

    await OutboxPublisher(session_factory, bus, OutboxEvent).drain()

    delivered = bus.published[0]
    assert delivered.event_id == follow_on.event_id
    assert delivered.correlation_id == original.correlation_id
    assert delivered.causation_id == original.event_id
    assert delivered.producer == "incident-svc"
    assert delivered.payload["severity"] == 4
