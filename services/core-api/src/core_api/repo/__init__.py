"""SQLAlchemy models for the four schemas core-api owns.

All persistence goes through this package (ADR-002). Importing it registers every table
on `Base.metadata`, which is what Alembic autogenerate reads.
"""

from core_api.repo.admin import (
    AppUser,
    District,
    DSDivision,
    GNDivision,
    Household,
    Province,
    Role,
    UserRole,
)
from core_api.repo.audit import ACTOR_TYPES, AuditEntry
from core_api.repo.auth import (
    DEVICE_PLATFORMS,
    REVOCATION_REASONS,
    SECURITY_EVENT_KINDS,
    Device,
    LoginAttempt,
    MFAEnrolment,
    OTPChallenge,
    RefreshToken,
    SecurityEvent,
)
from core_api.repo.base import (
    ADMIN_SCHEMA,
    AUDIT_SCHEMA,
    EMBEDDING_DIMENSIONS,
    RESILIENCE_SCHEMA,
)
from core_api.repo.resilience import (
    ENTITY_TYPES,
    RELATION_TYPES,
    RGEntity,
    RGObservation,
    RGRelation,
)
from sarana_shared.db.outbox import make_outbox_model

# core-api's own outbox table: outbox.core_api_event.
OutboxEvent = make_outbox_model("core_api")

__all__ = [
    "ACTOR_TYPES",
    "ADMIN_SCHEMA",
    "AUDIT_SCHEMA",
    "DEVICE_PLATFORMS",
    "EMBEDDING_DIMENSIONS",
    "ENTITY_TYPES",
    "RELATION_TYPES",
    "RESILIENCE_SCHEMA",
    "REVOCATION_REASONS",
    "SECURITY_EVENT_KINDS",
    "AppUser",
    "AuditEntry",
    "DSDivision",
    "Device",
    "District",
    "GNDivision",
    "Household",
    "LoginAttempt",
    "MFAEnrolment",
    "OTPChallenge",
    "OutboxEvent",
    "Province",
    "RGEntity",
    "RGObservation",
    "RGRelation",
    "RefreshToken",
    "Role",
    "SecurityEvent",
    "UserRole",
]
