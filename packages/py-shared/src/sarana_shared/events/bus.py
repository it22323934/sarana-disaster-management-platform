"""The EventBus port.

ADR-003: the Postgres transactional outbox is the source of truth. This is the transport
that carries a committed outbox row onward - Redis Streams locally, EventBridge on AWS,
in-memory in tests. Everything publishes through this port, so an `MSKEventBus` can be
dropped in for Phase 2 without touching a single caller.

No agent calls another agent directly. That is what makes the platform recoverable: an
agent that dies mid-run leaves no half-finished conversation, only events that were either
published or not.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from sarana_shared.events.envelope import EventEnvelope

EventHandler = Callable[[EventEnvelope], Awaitable[None]]


class BusKind(StrEnum):
    """Which implementation `SARANA_EVENT_BUS` selects."""

    REDIS = "redis"
    EVENTBRIDGE = "eventbridge"
    MEMORY = "memory"


@dataclass(frozen=True, slots=True)
class Subscription:
    """A durable subscription: one consumer group reading one or more event types.

    Two processes sharing a `group` split the stream between them; two different groups
    each receive every event.

    `side_effect_free` is the important field. A consumer that sends an SMS, moves money
    or dispatches a crew declares False, and the bus then refuses to hand it a replayed
    envelope. Getting this wrong on a consumer means a replay re-sends real messages to
    real people, so it has no default - every subscription states it.
    """

    group: str
    consumer: str
    event_types: tuple[str, ...]
    side_effect_free: bool
    from_beginning: bool = False


@dataclass(frozen=True, slots=True)
class ReplayHandle:
    """A running or finished replay.

    Returned rather than a bare count so an operator can see what a replay is doing while
    it runs, and so the admin endpoint can refuse to start a second one.
    """

    replay_id: UUID
    target_group: str
    event_types: tuple[str, ...]
    since: datetime
    until: datetime | None
    requested_by: str
    started_at: datetime
    delivered: int = 0
    refused: int = 0
    finished_at: datetime | None = None

    @property
    def is_running(self) -> bool:
        """Whether this replay is still delivering."""
        return self.finished_at is None


@runtime_checkable
class EventBus(Protocol):
    """The port. Implementations must be safe to share across asyncio tasks."""

    async def publish(self, envelope: EventEnvelope) -> None:
        """Deliver one event. Must be idempotent on `event_id`."""
        ...

    async def publish_many(self, envelopes: list[EventEnvelope]) -> None:
        """Deliver a batch, preserving order within it."""
        ...

    async def subscribe(self, subscription: Subscription, handler: EventHandler) -> None:
        """Consume until cancelled, invoking `handler` once per event.

        The handler raising means the event is not acknowledged and will be redelivered.
        Implementations must not swallow handler exceptions silently.
        """
        ...

    async def replay(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
        event_types: tuple[str, ...] | None = None,
        target_group: str,
        requested_by: str,
    ) -> ReplayHandle:
        """Re-deliver a window of history to one consumer group.

        Scoped by time, type and target group. There is deliberately no call that replays
        everything to everyone: the blast radius of that mistake, on a platform that sends
        SMS and moves money, is not recoverable.
        """
        ...

    async def close(self) -> None:
        """Release connections."""
        ...


def matches(event_type: str, patterns: tuple[str, ...]) -> bool:
    """Whether an event type matches any subscription pattern.

    A pattern is either an exact type or a dotted prefix ending in `*`.
    """
    for pattern in patterns:
        if pattern in ("*", event_type):
            return True
        if pattern.endswith("*") and event_type.startswith(pattern[:-1]):
            return True
    return False


def refuses_replay(subscription: Subscription, envelope: EventEnvelope) -> bool:
    """Whether this subscription must refuse this envelope.

    A replayed envelope reaching a side-effecting consumer means an SMS is re-sent to a
    citizen about a cyclone that passed three weeks ago, or money is released twice. Both
    are worse than the problem the replay was run to fix.
    """
    return envelope.is_replay and not subscription.side_effect_free
