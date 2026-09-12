"""Exactly-once side effects from at-least-once delivery.

No broker gives exactly-once delivery. What a system can have is at-least-once plus
idempotent consumers, and the result is indistinguishable at the only place it matters.

The concurrency case is the one that actually bites. A hundred deliveries of the same
envelope all reach a `has this been handled?` check at the same moment and all pass it.
Only a unique constraint serialises them, which is why the claim is inserted before the
work rather than recorded after it.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sarana_shared.domain.ids import uuid7
from sarana_shared.events.envelope import EventEnvelope
from sarana_shared.events.idempotency import mark_processed, once, seen

pytestmark = pytest.mark.asyncio(loop_scope="session")

GROUP = "test-consumer"
OTHER_GROUP = "other-consumer"


def an_envelope() -> EventEnvelope:
    return EventEnvelope(
        event_type="sarana.aid.disbursement.released",
        producer="ledger-svc",
        correlation_id=uuid7(),
        payload={"disbursement_id": str(uuid7())},
    )


async def test_a_second_delivery_is_a_no_op(
    session_factory: async_sessionmaker[AsyncSession], clean_outbox: None
) -> None:
    envelope = an_envelope()
    calls: list[str] = []

    async def handler(_session: AsyncSession, _envelope: EventEnvelope) -> str:
        calls.append("ran")
        return "ok"

    async with session_factory() as session:
        assert await once(session, GROUP, envelope, handler) is True
        await session.commit()

    async with session_factory() as session:
        assert await once(session, GROUP, envelope, handler) is False
        await session.commit()

    assert calls == ["ran"]


async def test_a_hundred_concurrent_deliveries_produce_one_set_of_side_effects(
    session_factory: async_sessionmaker[AsyncSession], clean_outbox: None
) -> None:
    """The third required case. This is the one a check-then-act would fail."""
    envelope = an_envelope()
    side_effects: list[int] = []

    async def deliver(attempt: int) -> bool:
        async def handler(_session: AsyncSession, _envelope: EventEnvelope) -> str:
            side_effects.append(attempt)
            return "released"

        async with session_factory() as session:
            try:
                ran = await once(session, GROUP, envelope, handler)
                await session.commit()
            except Exception:  # noqa: BLE001 - any loser of the constraint race
                # A loser of the unique-constraint race. Not an error: it means another
                # delivery is doing the work.
                await session.rollback()
                return False
            return ran

    results = await asyncio.gather(*(deliver(i) for i in range(100)))

    assert sum(results) == 1, f"{sum(results)} deliveries ran the handler"
    assert len(side_effects) == 1, f"{len(side_effects)} sets of side effects"


async def test_two_consumer_groups_each_get_the_event(
    session_factory: async_sessionmaker[AsyncSession], clean_outbox: None
) -> None:
    """Groups are independent. A single-column key would silently suppress one of them."""
    envelope = an_envelope()
    ran: list[str] = []

    async def handler_for(group: str):  # type: ignore[no-untyped-def]  # test closure
        async def handler(_session: AsyncSession, _envelope: EventEnvelope) -> None:
            ran.append(group)

        return handler

    for group in (GROUP, OTHER_GROUP):
        async with session_factory() as session:
            assert await once(session, group, envelope, await handler_for(group)) is True
            await session.commit()

    assert sorted(ran) == sorted([GROUP, OTHER_GROUP])


async def test_the_claim_and_the_work_commit_together(
    session_factory: async_sessionmaker[AsyncSession], clean_outbox: None
) -> None:
    """A handler that fails must leave no claim, or the event is lost forever.

    Recording the claim in its own transaction would mean a handler that crashed after
    the claim committed could never be retried - the event would be permanently marked
    handled and permanently not handled.
    """
    envelope = an_envelope()

    async def failing(_session: AsyncSession, _envelope: EventEnvelope) -> None:
        raise RuntimeError("the payment rail rejected it")

    with pytest.raises(RuntimeError, match="payment rail"):
        async with session_factory() as session:
            await once(session, GROUP, envelope, failing)
            await session.commit()

    async with session_factory() as session:
        assert await seen(session, GROUP, envelope.event_id) is False

    # And so a retry can still run.
    async def succeeding(_session: AsyncSession, _envelope: EventEnvelope) -> None:
        return None

    async with session_factory() as session:
        assert await once(session, GROUP, envelope, succeeding) is True
        await session.commit()


async def test_marking_records_what_it_was_for(
    session_factory: async_sessionmaker[AsyncSession], clean_outbox: None
) -> None:
    """An operator reconstructing a run needs the type and the chain, not the payload."""
    envelope = an_envelope()

    async with session_factory() as session:
        await mark_processed(session, GROUP, envelope, outcome="disbursed")
        await session.commit()

    async with session_factory() as session:
        result = await session.execute(
            text(
                "SELECT event_type, correlation_id, outcome FROM outbox.processed_event "
                "WHERE consumer_group = :g"
            ),
            {"g": GROUP},
        )
        event_type, correlation_id, outcome = result.one()

    assert event_type == "sarana.aid.disbursement.released"
    assert correlation_id == envelope.correlation_id
    assert outcome == "disbursed"
