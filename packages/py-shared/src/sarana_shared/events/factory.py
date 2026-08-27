"""Builds the EventBus a service should use, from its settings.

One place that knows which implementation goes with which environment, so a service's
lifespan says `build_event_bus(settings)` and nothing else needs to care. Adding the
Phase 2 MSK implementation (ADR-003) is a branch here and a new module - no caller
changes.
"""

from __future__ import annotations

import structlog

from sarana_shared.events.bus import BusKind, EventBus

_log = structlog.get_logger(__name__)


def build_event_bus(
    *,
    kind: BusKind,
    redis_url: str,
    stream_prefix: str = "sarana",
    bus_name: str = "sarana",
    region: str = "ap-south-1",
) -> EventBus:
    """Construct the configured bus.

    Raises:
        NotImplementedError: for a kind that is a documented seam rather than a built
            implementation. Failing at construction is the point - a service that
            silently fell back to a different bus would publish into a void.
    """
    match kind:
        case BusKind.REDIS:
            from redis.asyncio import Redis

            from sarana_shared.events.impl.redis_streams import RedisStreamsEventBus

            _log.info("event_bus_selected", kind=kind.value, prefix=stream_prefix)
            return RedisStreamsEventBus(Redis.from_url(redis_url), prefix=stream_prefix)

        case BusKind.EVENTBRIDGE:
            from sarana_shared.events.impl.eventbridge import EventBridgeEventBus

            _log.info("event_bus_selected", kind=kind.value, bus_name=bus_name)
            return EventBridgeEventBus(bus_name=bus_name, region=region)

        case BusKind.MEMORY:
            from sarana_shared.events.impl.in_memory import InMemoryEventBus

            _log.info("event_bus_selected", kind=kind.value)
            return InMemoryEventBus()

    raise NotImplementedError(f"no EventBus implementation for {kind!r}")
