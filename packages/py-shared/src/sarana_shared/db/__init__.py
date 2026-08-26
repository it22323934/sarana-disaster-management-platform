"""Persistence foundations: declarative base, session lifecycle, transactional outbox."""

from sarana_shared.db.base import (
    NAMING_CONVENTION,
    Base,
    CorrelationMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from sarana_shared.db.outbox import (
    MAX_PUBLISH_ATTEMPTS,
    OUTBOX_SCHEMA,
    OutboxEvent,
    OutboxRelay,
    enqueue,
    reset_stuck_events,
    stuck_event_count,
)
from sarana_shared.db.session import (
    SERIALIZABLE,
    DatabaseSettings,
    check_connection,
    create_engine,
    create_session_factory,
    dispose_engine,
    session_scope,
)

__all__ = [
    "MAX_PUBLISH_ATTEMPTS",
    "NAMING_CONVENTION",
    "OUTBOX_SCHEMA",
    "SERIALIZABLE",
    "Base",
    "CorrelationMixin",
    "DatabaseSettings",
    "OutboxEvent",
    "OutboxRelay",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "check_connection",
    "create_engine",
    "create_session_factory",
    "dispose_engine",
    "enqueue",
    "reset_stuck_events",
    "session_scope",
    "stuck_event_count",
]
