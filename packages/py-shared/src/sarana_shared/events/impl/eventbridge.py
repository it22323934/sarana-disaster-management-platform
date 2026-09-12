"""EventBridge + SQS + Archive. The AWS implementation.

ADR-003 chose this over MSK. The proposal's stated reason for Kafka was "full replay so
any failed agent task can be safely retried from the last known event" - EventBridge
Archive gives exactly that, natively, at a fraction of the cost and operational load. MSK
Serverless carries a meaningful monthly floor even at zero traffic, which is fatal for a
platform whose whole pitch is surviving the quiet years between disasters.

Shape of it:

  publish    PutEvents onto the bus. Rules fan out to one SQS queue per consumer group.
  subscribe  Long-poll that group's queue; delete the message only after the handler
             returns, so a crash redelivers rather than loses.
  replay     StartReplay from the Archive into a dedicated replay queue, so replayed
             traffic never lands in the live queues by accident.

`correlation_id` is the partition key, matching the Redis implementation. Ordering is
per correlation id only, never global.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Final

import structlog

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

# EventBridge caps a PutEvents call at 10 entries.
PUT_EVENTS_BATCH: Final = 10

# Long-poll rather than spin. 20s is the SQS maximum and the cheapest way to wait.
RECEIVE_WAIT_SECONDS: Final = 20

SOURCE: Final = "lk.sarana"


class EventBridgeEventBus:
    """The AWS bus.

    boto3 is synchronous, so every call runs in a worker thread. Wrapping it rather than
    taking an async AWS SDK dependency keeps one SDK in the image and one set of
    credential-resolution behaviour to reason about.
    """

    def __init__(
        self,
        *,
        bus_name: str,
        region: str,
        queue_url_for_group: dict[str, str] | None = None,
        replay_queue_arn: str | None = None,
        archive_name: str | None = None,
    ) -> None:
        self._bus_name = bus_name
        self._region = region
        self._queues = queue_url_for_group or {}
        self._replay_queue_arn = replay_queue_arn
        self._archive_name = archive_name or f"{bus_name}-archive"
        self._events_client: Any = None
        self._sqs_client: Any = None

    def _events(self) -> Any:
        if self._events_client is None:
            import boto3

            self._events_client = boto3.client("events", region_name=self._region)
        return self._events_client

    def _sqs(self) -> Any:
        if self._sqs_client is None:
            import boto3

            self._sqs_client = boto3.client("sqs", region_name=self._region)
        return self._sqs_client

    def _entry(self, envelope: EventEnvelope) -> dict[str, Any]:
        """One PutEvents entry.

        `DetailType` carries the event type so an EventBridge rule can route on it
        without parsing the detail, which is what keeps the rules readable in the console.
        """
        return {
            "EventBusName": self._bus_name,
            "Source": SOURCE,
            "DetailType": envelope.event_type,
            "Detail": envelope.model_dump_json(),
            "Time": envelope.occurred_at,
            "TraceHeader": envelope.trace_context.get("traceparent", ""),
        }

    async def publish(self, envelope: EventEnvelope) -> None:
        await self.publish_many([envelope])

    async def publish_many(self, envelopes: list[EventEnvelope]) -> None:
        """Put a batch, failing loudly on partial failure.

        EventBridge returns per-entry failures rather than raising. Ignoring them would
        mean the outbox marks a row published that never reached the bus - exactly the
        silent loss the outbox exists to prevent.
        """
        if not envelopes:
            return

        for start in range(0, len(envelopes), PUT_EVENTS_BATCH):
            chunk = envelopes[start : start + PUT_EVENTS_BATCH]
            entries = [self._entry(envelope) for envelope in chunk]
            response = await asyncio.to_thread(self._events().put_events, Entries=entries)

            failed = int(response.get("FailedEntryCount", 0))
            if failed:
                reasons = [
                    entry.get("ErrorMessage", "unknown")
                    for entry in response.get("Entries", [])
                    if entry.get("ErrorCode")
                ]
                raise RuntimeError(
                    f"EventBridge rejected {failed} of {len(chunk)} entries: "
                    f"{'; '.join(reasons[:3])}"
                )

    async def subscribe(self, subscription: Subscription, handler: EventHandler) -> None:
        """Long-poll this group's queue until cancelled.

        The message is deleted only after the handler returns. A crash between handling
        and deleting redelivers, which is safe because every consumer is idempotent -
        and is strictly better than deleting first and losing the work.
        """
        queue_url = self._queues.get(subscription.group)
        if queue_url is None:
            raise ValueError(
                f"no SQS queue configured for consumer group {subscription.group!r}. "
                "Each group gets its own queue, created by the Terraform module."
            )

        _log.info(
            "subscription_started",
            group=subscription.group,
            side_effect_free=subscription.side_effect_free,
            queue_url=queue_url,
        )

        while True:
            response = await asyncio.to_thread(
                self._sqs().receive_message,
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=RECEIVE_WAIT_SECONDS,
                MessageAttributeNames=["All"],
            )
            for message in response.get("Messages", []):
                await self._handle(subscription, handler, queue_url, message)

    async def _handle(
        self,
        subscription: Subscription,
        handler: EventHandler,
        queue_url: str,
        message: dict[str, Any],
    ) -> None:
        """Decode one SQS message, run the handler, delete only on success."""
        receipt = message["ReceiptHandle"]

        try:
            body = json.loads(message["Body"])
            envelope = EventEnvelope.model_validate_json(body["detail"])
        except (KeyError, ValueError, json.JSONDecodeError):
            # Nothing can be done with a message that is not an envelope. Delete it
            # rather than let it cycle through the queue forever; the log line is the
            # record that it happened.
            await asyncio.to_thread(
                self._sqs().delete_message, QueueUrl=queue_url, ReceiptHandle=receipt
            )
            _log.warning("event_message_malformed", queue_url=queue_url)
            return

        if not matches(envelope.event_type, subscription.event_types):
            await asyncio.to_thread(
                self._sqs().delete_message, QueueUrl=queue_url, ReceiptHandle=receipt
            )
            return

        if refuses_replay(subscription, envelope):
            # Deleted, because redelivering it would produce the same refusal forever.
            await asyncio.to_thread(
                self._sqs().delete_message, QueueUrl=queue_url, ReceiptHandle=receipt
            )
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
        await asyncio.to_thread(
            self._sqs().delete_message, QueueUrl=queue_url, ReceiptHandle=receipt
        )

    async def replay(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
        event_types: tuple[str, ...] | None = None,
        target_group: str,
        requested_by: str,
    ) -> ReplayHandle:
        """Start an EventBridge Archive replay into the dedicated replay queue.

        Replayed traffic goes to its own destination rather than the live queues. A
        replay landing in the queue that feeds the SMS sender is exactly the accident
        this whole mechanism exists to prevent, and routing is a stronger guarantee than
        remembering to check a flag.
        """
        if not event_types:
            raise ValueError(
                "a replay must name its event types. There is no replay-everything call: "
                "on a platform that sends SMS and moves money, that mistake is not "
                "recoverable."
            )
        if self._replay_queue_arn is None:
            raise ValueError(
                "no replay queue configured. Replayed events must not land in the live "
                "consumer queues, so a dedicated destination is required."
            )

        started = utc_now()
        replay_id = uuid7()

        await asyncio.to_thread(
            self._events().start_replay,
            ReplayName=f"sarana-{replay_id}",
            EventSourceArn=self._archive_name,
            EventStartTime=since,
            EventEndTime=until or started,
            Destination={
                "Arn": self._replay_queue_arn,
                "FilterArns": [],
            },
        )

        _log.info(
            "replay_started",
            replay_id=str(replay_id),
            target_group=target_group,
            requested_by=requested_by,
            event_types=list(event_types),
        )

        # EventBridge replays run asynchronously, so the handle comes back still running.
        # The admin endpoint polls DescribeReplay for progress.
        return ReplayHandle(
            replay_id=replay_id,
            target_group=target_group,
            event_types=event_types,
            since=since,
            until=until,
            requested_by=requested_by,
            started_at=started,
        )

    async def close(self) -> None:
        """boto3 clients hold no connections that need explicit release."""
        return None
