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
    "NAMING_CONVENTION",
    "SERIALIZABLE",
    "Base",
    "CorrelationMixin",
    "DatabaseSettings",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "check_connection",
    "confidence_range",
    "create_engine",
    "create_session_factory",
    "dispose_engine",
    "in_list",
    "localised",
    "no_individual_named",
    "session_scope",
]
