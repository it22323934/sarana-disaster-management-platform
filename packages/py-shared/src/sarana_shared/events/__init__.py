"""Event envelope, bus port and type registry.

ADR-003: Postgres transactional outbox is the source of truth; this package is the
transport and the contract layer on top of it.
"""

from sarana_shared.events.bus import (
    EventBus,
    EventHandler,
    InMemoryEventBus,
    RedisStreamsEventBus,
    Subscription,
    matches,
)
from sarana_shared.events.envelope import EventEnvelope
from sarana_shared.events.registry import (
    UnknownEventType,
    export_json_schemas,
    parse_payload,
    payload_model,
    register,
    registered_types,
    write_json_schemas,
)

__all__ = [
    "EventBus",
    "EventEnvelope",
    "EventHandler",
    "InMemoryEventBus",
    "RedisStreamsEventBus",
    "Subscription",
    "UnknownEventType",
    "export_json_schemas",
    "matches",
    "parse_payload",
    "payload_model",
    "register",
    "registered_types",
    "write_json_schemas",
]
