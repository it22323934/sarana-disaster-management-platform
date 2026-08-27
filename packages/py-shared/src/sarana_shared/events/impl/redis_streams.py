"""Redis Streams event bus. Local development and CI.

One stream per event domain (`{prefix}:events:incident`), so a subscriber to
`sarana.incident.*` reads a single stream. Type filtering inside a domain happens
client-side, which is cheap at development volume and keeps the key space small.

Delivery is at-least-once: an event is acknowledged only after its handler returns. A
handler that raises leaves the entry pending and it is redelivered - which is safe
because every consumer is idempotent (`events/idempotency.py`).

Replay reads the streams directly by entry id, which is a millisecond timestamp, so a time
window becomes an XRANGE bound rather than a scan.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

import structlog
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from sarana_shared.domain.ids import set_correlation_id, uuid7
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

# Redis Streams response shapes. redis-py types these loosely because the same call can
# return decoded or raw values; SARANA always uses a bytes client, so the concrete shape
# is pinned here rather than re-derived at every call site.
type StreamEntry = tuple[bytes, dict[bytes, bytes]]
type StreamBatch = list[tuple[bytes, list[StreamEntry]]]
type StreamName = bytes | str | memoryview[int]
type StreamId = int | bytes | str | memoryview[int]


class RedisStreamsEventBus:
    """The local-development bus."""

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
        """Resolve subscription patterns to the streams that can satisfy them."""
        domains: set[str] = set()
        for pattern in patterns:
            if pattern == "*":
                raise ValueError(
                    "subscribe to at least a domain, e.g. sarana.incident.*, rather than "
                    "every event on the bus"
                )
            parts = pattern.split(".")
            if len(parts) < 2 or parts[0] != "sarana":
                raise ValueError(f"unusable subscription pattern: {pattern!r}")
            domains.add(parts[1])
        return sorted(domains)

    async def publish(self, envelope: EventEnvelope) -> None:
        await self._redis.xadd(
            self._stream_key(envelope.domain),
            {"envelope": envelope.model_dump_json()},
            maxlen=self._max_stream_length,
            approximate=True,
        )
        _log.debug(
            "event_published",
            event_type=envelope.event_type,
            event_id=str(envelope.event_id),
            correlation_id=str(envelope.correlation_id),
        )

    async def publish_many(self, envelopes: list[EventEnvelope]) -> None:
        if not envelopes:
            return
        async with self._redis.pipeline(transaction=False) as pipe:
            for envelope in envelopes:
                pipe.xadd(
                    self._stream_key(envelope.domain),
                    {"envelope": envelope.model_dump_json()},
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
            side_effect_free=subscription.side_effect_free,
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
            # Nothing can be done with an entry carrying no envelope. Acknowledge it
            # rather than block the whole consumer group forever on one bad write.
            await self._redis.xack(stream_key, subscription.group, entry_id)
            _log.warning("event_entry_malformed", stream=stream_key, entry_id=_as_str(entry_id))
            return

        envelope = EventEnvelope.model_validate_json(raw)
        if not matches(envelope.event_type, subscription.event_types):
            await self._redis.xack(stream_key, subscription.group, entry_id)
            return

        if refuses_replay(subscription, envelope):
            # Acknowledged, because redelivering it would produce the same refusal
            # forever. The refusal itself is the record that it happened.
            await self._redis.xack(stream_key, subscription.group, entry_id)
            _log.warning(
                "replay_refused",
                consumer_group=subscription.group,
                event_type=envelope.event_type,
                event_id=str(envelope.event_id),
                replay_of=str(envelope.replay_of),
                reason="consumer has real-world side effects",
            )
            return

        set_correlation_id(str(envelope.correlation_id))
        await handler(envelope)
        await self._redis.xack(stream_key, subscription.group, entry_id)

    async def replay(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
        event_types: tuple[str, ...] | None = None,
        target_group: str,
        requested_by: str,
    ) -> ReplayHandle:
        """Re-publish a window of history, marked as a replay.

        Entry ids are millisecond timestamps, so the window is an XRANGE bound rather
        than a scan of the whole stream.
        """
        started = utc_now()
        patterns = event_types or ("*",)
        delivered = 0

        start_id = f"{int(since.timestamp() * 1000)}-0"
        end_id = f"{int(until.timestamp() * 1000)}-99999" if until else "+"

        domains = self._domains_for(patterns) if event_types else []
        if not domains:
            raise ValueError(
                "a replay must name its event types. There is no call that replays "
                "everything to everyone: on a platform that sends SMS and moves money, "
                "the blast radius of that mistake is not recoverable."
            )

        for domain in domains:
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
                    original = EventEnvelope.model_validate_json(raw)
                    if not matches(original.event_type, patterns):
                        continue
                    await self.publish(original.as_replay(at=started))
                    delivered += 1

                millis, _, sequence = _as_str(entries[-1][0]).partition("-")
                cursor = f"{millis}-{int(sequence) + 1}"

        _log.info(
            "replay_completed",
            target_group=target_group,
            requested_by=requested_by,
            event_types=list(patterns),
            delivered=delivered,
        )
        return ReplayHandle(
            replay_id=uuid7(),
            target_group=target_group,
            event_types=patterns,
            since=since,
            until=until,
            requested_by=requested_by,
            started_at=started,
            delivered=delivered,
            finished_at=utc_now(),
        )

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
