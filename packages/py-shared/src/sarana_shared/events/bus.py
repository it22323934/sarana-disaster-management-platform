"""The EventBus port and its local implementations.

ADR-003: the Postgres transactional outbox is the source of truth. This bus is the
transport that carries an outbox row onward - Redis Streams locally, EventBridge + SQS on
AWS. Everything publishes through this port, so an `MSKEventBus` can be dropped in for
Phase 2 without touching a service.

`replay` exists because the platform's retry guarantee is "resume from the last known
event". Redis Streams gives it from the stream itself; on AWS it is EventBridge Archive.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, cast, runtime_checkable

import structlog
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from sarana_shared.domain.ids import set_correlation_id
from sarana_shared.events.envelope import EventEnvelope

_log = structlog.get_logger(__name__)

EventHandler = Callable[[EventEnvelope], Awaitable[None]]

# Redis stream key and entry-id, as accepted by redis-py's stream commands.
type StreamName = bytes | str | memoryview[int]
type StreamId = int | bytes | str | memoryview[int]


@dataclass(frozen=True, slots=True)
class Subscription:
    """A durable subscription: one consumer group reading one or more event types.

    `group` is the consumer group name. Two processes sharing a group split the stream
    between them; two different groups each receive every event.
    """

    group: str
    consumer: str
    event_types: tuple[str, ...]
    # Glob-style suffix wildcards are allowed: "sarana.incident.*" matches the domain.
    from_beginning: bool = False


@runtime_checkable
class EventBus(Protocol):
    """The port. Implementations must be safe to share across asyncio tasks."""

    async def publish(self, event: EventEnvelope) -> None:
        """Deliver one event. Must be idempotent on `event_id`."""
        ...

    async def publish_many(self, events: list[EventEnvelope]) -> None:
        """Deliver a batch, preserving order within the batch."""
        ...

    async def subscribe(self, subscription: Subscription, handler: EventHandler) -> None:
        """Consume until cancelled, invoking `handler` once per event.

        The handler raising means the event is not acknowledged and will be redelivered.
        Implementations must not swallow handler exceptions silently.
        """
        ...

    async def replay(
        self,
        event_types: tuple[str, ...],
        since: datetime,
        until: datetime | None = None,
    ) -> AsyncIterator[EventEnvelope]:
        """Re-read historical events in original order, without acknowledging them."""
        ...

    async def close(self) -> None:
        """Release connections."""
        ...


def matches(event_type: str, patterns: tuple[str, ...]) -> bool:
    """Whether an event type matches any subscription pattern.

    A pattern is either an exact type or a dotted prefix ending in `*`.
    """
    for pattern in patterns:
        if pattern == "*" or pattern == event_type:
            return True
        if pattern.endswith("*") and event_type.startswith(pattern[:-1]):
            return True
    return False


@dataclass
class InMemoryEventBus:
    """An in-process bus for unit tests and the seed loader.

    Keeps every published event so a test can assert on the chain, and so `replay` works
    exactly as it does against Redis.
    """

    published: list[EventEnvelope] = field(default_factory=list)
    _handlers: list[tuple[Subscription, EventHandler]] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def publish(self, event: EventEnvelope) -> None:
        async with self._lock:
            if any(existing.event_id == event.event_id for existing in self.published):
                return
            self.published.append(event)
            targets = [
                handler
                for subscription, handler in self._handlers
                if matches(event.type, subscription.event_types)
            ]
        for handler in targets:
            await handler(event)

    async def publish_many(self, events: list[EventEnvelope]) -> None:
        for event in events:
            await self.publish(event)

    async def subscribe(self, subscription: Subscription, handler: EventHandler) -> None:
        if subscription.from_beginning:
            for event in list(self.published):
                if matches(event.type, subscription.event_types):
                    await handler(event)
        async with self._lock:
            self._handlers.append((subscription, handler))

    async def replay(
        self,
        event_types: tuple[str, ...],
        since: datetime,
        until: datetime | None = None,
    ) -> AsyncIterator[EventEnvelope]:
        for event in list(self.published):
            if not matches(event.type, event_types):
                continue
            if event.occurred_at < since:
                continue
            if until is not None and event.occurred_at > until:
                continue
            yield event

    async def close(self) -> None:
        self._handlers.clear()

    def events_of_type(self, event_type: str) -> list[EventEnvelope]:
        """Test helper: every published event of one type, in order."""
        return [event for event in self.published if event.type == event_type]

    def clear(self) -> None:
        """Test helper: forget every published event."""
        self.published.clear()


# Redis Streams response shapes. redis-py types these loosely because the same call can
# return decoded or raw values depending on the client; SARANA always uses a bytes
# client, so the concrete shape is pinned here rather than re-derived at every call site.
type StreamEntry = tuple[bytes, dict[bytes, bytes]]
type StreamBatch = list[tuple[bytes, list[StreamEntry]]]


class RedisStreamsEventBus:
    """The local-development bus, backed by Redis Streams.

    One stream per event domain (`{prefix}:events:incident`), so a subscriber to
    `sarana.incident.*` reads a single stream. Type filtering inside a domain happens
    client-side, which is cheap at development volume and keeps the key space small.

    Delivery is at-least-once: an event is acknowledged only after its handler returns.
    A handler that raises leaves the entry pending and it is redelivered.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        prefix: str = "sarana",
        block_ms: int = 5_000,
        batch_size: int = 64,
        max_stream_length: int = 100_000,
    ) -> None:
        self._redis = redis
        self._prefix = prefix
        self._block_ms = block_ms
        self._batch_size = batch_size
        self._max_stream_length = max_stream_length

    def _stream_key(self, domain: str) -> str:
        return f"{self._prefix}:events:{domain}"

    def _domains_for(self, patterns: tuple[str, ...]) -> list[str]:
        """Resolve subscription patterns to the stream keys that can satisfy them."""
        domains: set[str] = set()
        for pattern in patterns:
            if pattern == "*":
                raise ValueError(
                    "subscribe to at least a domain, e.g. sarana.incident.*, "
                    "rather than every event on the bus"
                )
            parts = pattern.split(".")
            if len(parts) < 2 or parts[0] != "sarana":
                raise ValueError(f"unusable subscription pattern: {pattern!r}")
            domains.add(parts[1])
        return sorted(domains)

    async def publish(self, event: EventEnvelope) -> None:
        await self._redis.xadd(
            self._stream_key(event.domain),
            {"envelope": event.model_dump_json()},
            maxlen=self._max_stream_length,
            approximate=True,
        )
        _log.debug(
            "event_published",
            event_type=event.type,
            event_id=str(event.event_id),
            correlation_id=event.correlation_id,
        )

    async def publish_many(self, events: list[EventEnvelope]) -> None:
        if not events:
            return
        async with self._redis.pipeline(transaction=False) as pipe:
            for event in events:
                pipe.xadd(
                    self._stream_key(event.domain),
                    {"envelope": event.model_dump_json()},
                    maxlen=self._max_stream_length,
                    approximate=True,
                )
            await pipe.execute()

    async def _ensure_group(self, stream: str, group: str, from_beginning: bool) -> None:
        """Create the consumer group, tolerating the race where it already exists."""
        try:
            await self._redis.xgroup_create(
                name=stream,
                groupname=group,
                id="0" if from_beginning else "$",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def subscribe(self, subscription: Subscription, handler: EventHandler) -> None:
        domains = self._domains_for(subscription.event_types)
        for domain in domains:
            await self._ensure_group(
                self._stream_key(domain), subscription.group, subscription.from_beginning
            )

        stream_ids: dict[StreamName, StreamId] = {
            self._stream_key(domain): ">" for domain in domains
        }
        _log.info(
            "subscription_started",
            group=subscription.group,
            consumer=subscription.consumer,
            streams=sorted(self._stream_key(domain) for domain in domains),
        )

        while True:
            batch = cast(
                "StreamBatch",
                await self._redis.xreadgroup(
                    groupname=subscription.group,
                    consumername=subscription.consumer,
                    streams=stream_ids,
                    count=self._batch_size,
                    block=self._block_ms,
                ),
            )
            if not batch:
                continue

            for raw_stream_key, entries in batch:
                stream_key = _as_str(raw_stream_key)
                for entry_id, fields in entries:
                    await self._dispatch(subscription, handler, stream_key, entry_id, fields)

    async def _dispatch(
        self,
        subscription: Subscription,
        handler: EventHandler,
        stream_key: str,
        entry_id: bytes,
        fields: dict[bytes, bytes],
    ) -> None:
        """Decode one entry, run the handler, acknowledge only on success."""
        raw = _envelope_field(fields)
        if raw is None:
            # Nothing can be done with an entry that carries no envelope. Acknowledge it
            # rather than block the whole consumer group forever on one bad write.
            await self._redis.xack(stream_key, subscription.group, entry_id)
            _log.warning("event_entry_malformed", stream=stream_key, entry_id=_as_str(entry_id))
            return

        event = EventEnvelope.model_validate_json(raw)
        if not matches(event.type, subscription.event_types):
            await self._redis.xack(stream_key, subscription.group, entry_id)
            return

        set_correlation_id(event.correlation_id)
        await handler(event)
        await self._redis.xack(stream_key, subscription.group, entry_id)

    async def replay(
        self,
        event_types: tuple[str, ...],
        since: datetime,
        until: datetime | None = None,
    ) -> AsyncIterator[EventEnvelope]:
        """Re-read history straight from the streams, without touching consumer groups.

        Stream entry IDs are millisecond timestamps, so the time window becomes an
        XRANGE bound and only the type filter runs client-side.
        """
        start_id = f"{int(since.timestamp() * 1000)}-0"
        end_id = f"{int(until.timestamp() * 1000)}-99999" if until else "+"

        for domain in self._domains_for(event_types):
            cursor = start_id
            while True:
                entries = cast(
                    "list[StreamEntry]",
                    await self._redis.xrange(
                        self._stream_key(domain),
                        min=cursor,
                        max=end_id,
                        count=self._batch_size,
                    ),
                )
                if not entries:
                    break

                for _entry_id, fields in entries:
                    raw = _envelope_field(fields)
                    if raw is None:
                        continue
                    event = EventEnvelope.model_validate_json(raw)
                    if matches(event.type, event_types):
                        yield event

                millis, _, sequence = _as_str(entries[-1][0]).partition("-")
                cursor = f"{millis}-{int(sequence) + 1}"

    async def close(self) -> None:
        await self._redis.aclose()


def _as_str(value: bytes | str) -> str:
    """Redis returns bytes on a raw client and str on a decoding one. Accept both."""
    return value.decode() if isinstance(value, bytes) else value


def _envelope_field(fields: dict[bytes, bytes]) -> bytes | str | None:
    """Pull the serialised envelope out of a stream entry, bytes or str client."""
    raw: object = fields.get(b"envelope")
    if raw is None:
        raw = cast("dict[str, object]", fields).get("envelope")
    return raw if isinstance(raw, bytes | str) else None
