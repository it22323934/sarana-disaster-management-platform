"""Dead letters, and why they must not be silent.

A silent DLQ is the failure mode that kills trust in an event system. Someone looks at a
dashboard, sees no errors, and concludes the pipeline is healthy - while a hundred
assessments quietly failed to become entitlements and a hundred households are waiting for
money that is not coming.

So: the full envelope is kept, every failure's traceback is kept, the count is a metric,
and a redrive is an explicit operator action after a fix.
"""

from __future__ import annotations

import random
import traceback
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sarana_shared.domain.ids import uuid7
from sarana_shared.events.dlq import (
    MAX_ATTEMPTS,
    backoff_for,
    pending,
    pending_count,
    record_failure,
    redrive,
)
from sarana_shared.events.envelope import EventEnvelope

pytestmark = pytest.mark.asyncio(loop_scope="session")

GROUP = "entitlement-calculator"


def an_envelope() -> EventEnvelope:
    return EventEnvelope(
        event_type="sarana.aid.assessment.submitted",
        producer="ledger-svc",
        correlation_id=uuid7(),
        payload={"assessment_id": str(uuid7()), "category": "HOUSE_FULL"},
    )


async def _fail(session: AsyncSession, envelope: EventEnvelope, attempt: int, message: str) -> None:
    """Record one failed attempt.

    The exception is raised and caught rather than merely constructed, because an
    un-raised exception carries no traceback and the point of the DLQ is the traceback.
    """
    try:
        raise RuntimeError(message)
    except RuntimeError as error:
        await record_failure(
            session,
            consumer_group=GROUP,
            envelope=envelope,
            error=error,
            attempt=attempt,
            traceback_text="".join(traceback.format_exception(error)),
        )


async def test_backoff_doubles_and_is_jittered() -> None:
    """Without jitter a hundred failures retry in lockstep and look like an outage."""
    rng = random.Random(7)  # noqa: S311 - seeded for a reproducible assertion
    delays = [backoff_for(attempt, rng=rng) for attempt in range(1, 4)]

    assert delays[0] < delays[1] < delays[2]
    assert all(delay > timedelta(0) for delay in delays)

    spread = {
        backoff_for(1, rng=random.Random(seed))  # noqa: S311 - seeded, not a credential
        for seed in range(20)
    }
    assert len(spread) > 1, "every retry would fire at exactly the same moment"


async def test_the_first_failure_creates_the_dead_letter(
    session_factory: async_sessionmaker[AsyncSession], clean_outbox: None
) -> None:
    envelope = an_envelope()

    async with session_factory() as session:
        await _fail(session, envelope, 1, "cost schedule not published yet")
        await session.commit()

    async with session_factory() as session:
        letters = await pending(session, consumer_group=GROUP)

    assert len(letters) == 1
    assert letters[0].event_id == envelope.event_id
    assert letters[0].attempts == 1


async def test_every_attempt_is_kept_not_just_the_last(
    session_factory: async_sessionmaker[AsyncSession], clean_outbox: None
) -> None:
    """Three failures the same way is a broken dependency. Three different ways is a
    broken message. An operator can only tell them apart if all three are kept."""
    envelope = an_envelope()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        async with session_factory() as session:
            await _fail(session, envelope, attempt, f"failure number {attempt}")
            await session.commit()

    async with session_factory() as session:
        letters = await pending(session, consumer_group=GROUP)

    assert len(letters) == 1, "each attempt created its own dead letter"
    assert len(letters[0].failures) == MAX_ATTEMPTS
    assert letters[0].attempts == MAX_ATTEMPTS
    assert "failure number 1" in letters[0].failures[0]["error"]
    assert "Traceback" in letters[0].failures[0]["traceback"]


async def test_the_count_is_available_as_a_metric(
    session_factory: async_sessionmaker[AsyncSession], clean_outbox: None
) -> None:
    """A non-empty DLQ raises an alarm. That needs a number, not a log line."""
    async with session_factory() as session:
        assert await pending_count(session) == 0

    async with session_factory() as session:
        await _fail(session, an_envelope(), 1, "boom")
        await _fail(session, an_envelope(), 1, "boom")
        await session.commit()

    async with session_factory() as session:
        assert await pending_count(session) == 2


async def test_a_redrive_returns_the_original_envelope_intact(
    session_factory: async_sessionmaker[AsyncSession], clean_outbox: None
) -> None:
    """The whole envelope is stored, so a redrive needs nothing else to work."""
    envelope = an_envelope()

    async with session_factory() as session:
        await _fail(session, envelope, 1, "cost schedule not published yet")
        await session.commit()

    async with session_factory() as session:
        letters = await pending(session, consumer_group=GROUP)
        restored = await redrive(
            session, letters[0].id, requested_by="operator-1", note="schedule published"
        )
        await session.commit()

    assert restored.event_id == envelope.event_id
    assert restored.correlation_id == envelope.correlation_id
    assert restored.payload == envelope.payload
    # A redrive is a fresh delivery of an event that never arrived, not a replay of one
    # that did - so there is no side effect to guard against repeating.
    assert restored.is_replay is False


async def test_a_redriven_letter_leaves_the_queue(
    session_factory: async_sessionmaker[AsyncSession], clean_outbox: None
) -> None:
    envelope = an_envelope()

    async with session_factory() as session:
        await _fail(session, envelope, 1, "boom")
        await session.commit()

    async with session_factory() as session:
        letters = await pending(session, consumer_group=GROUP)
        await redrive(session, letters[0].id, requested_by="operator-1")
        await session.commit()

    async with session_factory() as session:
        assert await pending_count(session) == 0


async def test_redriving_twice_is_refused(
    session_factory: async_sessionmaker[AsyncSession], clean_outbox: None
) -> None:
    """Two operators reading the same DLQ page must not both redrive the same letter."""
    envelope = an_envelope()

    async with session_factory() as session:
        await _fail(session, envelope, 1, "boom")
        await session.commit()

    async with session_factory() as session:
        letters = await pending(session, consumer_group=GROUP)
        letter_id = letters[0].id
        await redrive(session, letter_id, requested_by="operator-1")
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(LookupError, match="already redriven"):
            await redrive(session, letter_id, requested_by="operator-2")
