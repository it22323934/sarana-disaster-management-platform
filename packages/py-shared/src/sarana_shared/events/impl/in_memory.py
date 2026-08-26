"""InMemoryEventBus — the only EventBus implementation built at scaffold stage.

Exists so `sarana_shared.testing`'s `event_bus` fixture has something real to hand
tests, without pulling Redis or AWS into unit tests. `RedisStreamsEventBus` (dev) and
`EventBridgeEventBus` (AWS), plus real idempotency/DLQ handling, are
docs/build-prompts/06-event-bus.md's job — this implementation does not survive a
process restart and is not meant to.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sarana_shared.events.bus import Handler
from sarana_shared.events.envelope import EventEnvelope


@dataclass
class _ReplayHandle:
    _status: str = "completed"  # in-memory replay is synchronous, so it's done immediately

    async def status(self) -> str:
        return self._status

    async def cancel(self) -> None:
        self._status = "cancelled"


@dataclass
class InMemoryEventBus:
    """Fan-out to every matching subscriber, in-process, synchronously. Matches the
    `EventBus` protocol structurally (see events/bus.py) without inheriting from it —
    Protocol is duck-typed by design.
    """

    _log: list[EventEnvelope] = field(default_factory=list)
    _subscribers: dict[str, list[tuple[str, Handler]]] = field(
        default_factory=lambda: defaultdict(list)
    )

    async def publish(self, envelope: EventEnvelope) -> None:
        self._log.append(envelope)
        for _group, handler in self._subscribers.get(envelope.event_type, []):
            await handler(envelope)

    async def subscribe(self, event_types: list[str], group: str, handler: Handler) -> None:
        for event_type in event_types:
            self._subscribers[event_type].append((group, handler))

    async def replay(
        self,
        *,
        since: datetime,
        until: datetime | None,
        event_types: list[str] | None,
        target_group: str,
    ) -> _ReplayHandle:
        matching = [
            e
            for e in self._log
            if e.occurred_at >= since
            and (until is None or e.occurred_at <= until)
            and (event_types is None or e.event_type in event_types)
        ]
        for envelope in matching:
            replayed = envelope.model_copy(
                update={"replay_of": envelope.event_id, "replayed_at": _now()}
            )
            for group, handler in self._subscribers.get(envelope.event_type, []):
                if group == target_group:
                    await handler(replayed)
        return _ReplayHandle()

    def published(self) -> list[EventEnvelope]:
        """Test-only helper: everything published so far, in order."""
        return list(self._log)

    def reset(self) -> None:
        self._log.clear()
        self._subscribers.clear()


def _now() -> datetime:
    from sarana_shared.domain.time import now_utc

    return now_utc()
