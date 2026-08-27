"""The event backbone: envelope, contracts, bus, outbox, idempotency, replay, dead letters.

No agent calls another agent directly. Every event is replayable. A crashed consumer
resumes from the last known event with no data loss and no duplicate side effects.

That is the claim the proposal makes about Kafka. ADR-003 delivers the claim without it.
"""

from sarana_shared.events.bus import (
    BusKind,
    EventBus,
    EventHandler,
    ReplayHandle,
    Subscription,
    matches,
    refuses_replay,
)
from sarana_shared.events.dlq import (
    MAX_ATTEMPTS,
    DeadLetter,
    backoff_for,
    pending,
    pending_count,
    record_failure,
    redrive,
)
from sarana_shared.events.envelope import EventEnvelope
from sarana_shared.events.idempotency import (
    ProcessedEvent,
    mark_processed,
    once,
    prune,
    seen,
)
from sarana_shared.events.impl.in_memory import InMemoryEventBus
from sarana_shared.events.impl.redis_streams import RedisStreamsEventBus
from sarana_shared.events.outbox import (
    MAX_PUBLISH_ATTEMPTS,
    OUTBOX_SCHEMA,
    OutboxEventBase,
    OutboxPublisher,
    OutboxWorker,
    enqueue,
    make_outbox_model,
    reset_stuck_events,
    stuck_event_count,
)
from sarana_shared.events.registry import (
    SchemaIncompatible,
    UnknownEventType,
    assert_compatible,
    check_compatibility,
    export_json_schemas,
    parse_payload,
    payload_model,
    register,
    registered_types,
    write_json_schemas,
)
from sarana_shared.events.replay import (
    ReplayCoordinator,
    ReplayInProgress,
    ReplayRefused,
)

__all__ = [
    "MAX_ATTEMPTS",
    "MAX_PUBLISH_ATTEMPTS",
    "OUTBOX_SCHEMA",
    "BusKind",
    "DeadLetter",
    "EventBus",
    "EventEnvelope",
    "EventHandler",
    "InMemoryEventBus",
    "OutboxEventBase",
    "OutboxPublisher",
    "OutboxWorker",
    "ProcessedEvent",
    "RedisStreamsEventBus",
    "ReplayCoordinator",
    "ReplayHandle",
    "ReplayInProgress",
    "ReplayRefused",
    "SchemaIncompatible",
    "Subscription",
    "UnknownEventType",
    "assert_compatible",
    "backoff_for",
    "check_compatibility",
    "enqueue",
    "export_json_schemas",
    "make_outbox_model",
    "mark_processed",
    "matches",
    "once",
    "parse_payload",
    "payload_model",
    "pending",
    "pending_count",
    "prune",
    "record_failure",
    "redrive",
    "refuses_replay",
    "register",
    "registered_types",
    "reset_stuck_events",
    "seen",
    "stuck_event_count",
    "write_json_schemas",
]
