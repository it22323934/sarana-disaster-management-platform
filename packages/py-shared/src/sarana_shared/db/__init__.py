"""Persistence foundations: declarative base, session lifecycle, transactional outbox."""

from sarana_shared.db.base import (
    NAMING_CONVENTION,
    Base,
    CorrelationMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from sarana_shared.db.constraints import (
    confidence_range,
    in_list,
    localised,
    no_individual_named,
)
from sarana_shared.db.outbox import (
    MAX_PUBLISH_ATTEMPTS,
    OUTBOX_SCHEMA,
    OutboxEventBase,
    OutboxRelay,
    enqueue,
    make_outbox_model,
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
    "OutboxEventBase",
    "OutboxRelay",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "check_connection",
    "confidence_range",
    "create_engine",
    "create_session_factory",
    "dispose_engine",
    "enqueue",
    "in_list",
    "localised",
    "make_outbox_model",
    "no_individual_named",
    "reset_stuck_events",
    "session_scope",
    "stuck_event_count",
]
