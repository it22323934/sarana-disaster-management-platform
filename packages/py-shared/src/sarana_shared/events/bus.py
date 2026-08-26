"""EventBus protocol — publish, subscribe, replay.

This is the interface only, as scoped by docs/build-prompts/03-monorepo-scaffold.md. The
concrete implementations (RedisStreamsEventBus, EventBridgeEventBus, InMemoryEventBus),
the transactional outbox, idempotency tracking, replay, and dead-lettering are
docs/build-prompts/06-event-bus.md's job — deliberately not built here. No service should
import a concrete bus implementation directly; depend on this Protocol and inject one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol, runtime_checkable

from sarana_shared.events.envelope import EventEnvelope

Handler = Callable[[EventEnvelope], Awaitable[None]]


@runtime_checkable
class ReplayHandle(Protocol):
    """Returned by `replay()` — lets a caller check on or cancel an in-flight replay."""

    async def status(self) -> str: ...  # "running" | "completed" | "failed"
    async def cancel(self) -> None: ...


@runtime_checkable
class EventBus(Protocol):
    async def publish(self, envelope: EventEnvelope) -> None:
        """Publish one event. Callers are expected to have already written it to their
        own transactional outbox (docs/build-prompts/06) — this call is the outbox
        publisher's job, not a general-purpose "fire an event" call from business logic."""
        ...

    async def subscribe(self, event_types: list[str], group: str, handler: Handler) -> None:
        """Register a durable, idempotent consumer. `group` is the consumer group —
        ordering is guaranteed per correlation_id only, never globally."""
        ...

    async def replay(
        self,
        *,
        since: datetime,
        until: datetime | None,
        event_types: list[str] | None,
        target_group: str,
    ) -> ReplayHandle:
        """Re-deliver a time-windowed slice of history to one consumer group. A
        side-effect-having consumer (SMS send, payment release) must refuse a replayed
        envelope — see EventEnvelope.is_replay()."""
        ...
