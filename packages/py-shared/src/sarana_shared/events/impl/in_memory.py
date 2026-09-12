"""In-process event bus for unit tests and the seed loader.

Keeps every published envelope so a test can assert on the whole chain, and implements
replay with exactly the same semantics as the Redis and EventBridge buses - including the
refusal of replayed envelopes by side-effecting consumers. A test bus that skipped that
would let the one rule most worth testing go untested.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

import structlog

from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now
from sarana_shared.events.bus import (
    EventHandler,
    ReplayHandle,
    Subscription,
    matches,
    refuses_replay,
)
from sarana_shared.events.envelope import EventEnvelope

_log = structlog.get_logger(__name__)


@dataclass
class InMemoryEventBus:
    """An in-process bus. Not durable, and not meant to be."""

    published: list[EventEnvelope] = field(default_factory=list)
    refused_replays: list[EventEnvelope] = field(default_factory=list)
    _handlers: list[tuple[Subscription, EventHandler]] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def publish(self, envelope: EventEnvelope) -> None:
        async with self._lock:
            if any(seen.event_id == envelope.event_id for seen in self.published):
                return
            self.published.append(envelope)
            targets = [
                (subscription, handler)
                for subscription, handler in self._handlers
                if matches(envelope.event_type, subscription.event_types)
            ]

        for subscription, handler in targets:
            await self._deliver(subscription, handler, envelope)

    async def _deliver(
        self, subscription: Subscription, handler: EventHandler, envelope: EventEnvelope
    ) -> None:
        """Hand one envelope to one consumer, unless it must refuse it."""
        if refuses_replay(subscription, envelope):
            self.refused_replays.append(envelope)
            _log.warning(
                "replay_refused",
                consumer_group=subscription.group,
                event_type=envelope.event_type,
                event_id=str(envelope.event_id),
                replay_of=str(envelope.replay_of),
                reason="consumer has real-world side effects",
            )
            return
        await handler(envelope)

    async def publish_many(self, envelopes: list[EventEnvelope]) -> None:
        for envelope in envelopes:
            await self.publish(envelope)

    async def subscribe(self, subscription: Subscription, handler: EventHandler) -> None:
        if subscription.from_beginning:
            for envelope in list(self.published):
                if matches(envelope.event_type, subscription.event_types):
                    await self._deliver(subscription, handler, envelope)
        async with self._lock:
            self._handlers.append((subscription, handler))

    async def replay(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
        event_types: tuple[str, ...] | None = None,
        target_group: str,
        requested_by: str,
    ) -> ReplayHandle:
        started = utc_now()
        delivered = 0
        refused = 0

        targets = [
            (subscription, handler)
            for subscription, handler in self._handlers
            if subscription.group == target_group
        ]

        for original in list(self.published):
            if original.occurred_at < since:
                continue
            if until is not None and original.occurred_at > until:
                continue
            if event_types is not None and not matches(original.event_type, event_types):
                continue

            replayed = original.as_replay(at=started)
            for subscription, handler in targets:
                if not matches(replayed.event_type, subscription.event_types):
                    continue
                if refuses_replay(subscription, replayed):
                    refused += 1
                    self.refused_replays.append(replayed)
                    _log.warning(
                        "replay_refused",
                        consumer_group=subscription.group,
                        event_type=replayed.event_type,
                        replay_of=str(replayed.replay_of),
                    )
                    continue
                await handler(replayed)
                delivered += 1

        return ReplayHandle(
            replay_id=uuid7(),
            target_group=target_group,
            event_types=event_types or ("*",),
            since=since,
            until=until,
            requested_by=requested_by,
            started_at=started,
            delivered=delivered,
            refused=refused,
            finished_at=utc_now(),
        )

    async def close(self) -> None:
        self._handlers.clear()

    def events_of_type(self, event_type: str) -> list[EventEnvelope]:
        """Test helper: every published event of one type, in order."""
        return [e for e in self.published if e.event_type == event_type]

    def clear(self) -> None:
        """Test helper: forget everything published."""
        self.published.clear()
        self.refused_replays.clear()
