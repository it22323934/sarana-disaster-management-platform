"""SQLAlchemy models for the `incident` schema.

All persistence goes through this package (ADR-002). Importing it registers every table
on `Base.metadata`, which is what Alembic autogenerate reads.
"""

from incident_svc.repo.base import (
    DISPATCH_STATUSES,
    EMBEDDING_DIMENSIONS,
    INCIDENT_SCHEMA,
    INCIDENT_STATUSES,
    INTAKE_CHANNELS,
    LOCATION_SOURCES,
    PROCESSING_STATUSES,
)
from incident_svc.repo.dispatch import (
    RESPONDER_STATUSES,
    RESPONDER_TYPES,
    DispatchPlan,
    Responder,
)
from incident_svc.repo.incidents import (
    INCIDENT_TYPES,
    Incident,
    ReportIncidentLink,
    TriageScore,
)
from incident_svc.repo.reports import (
    HUMAN_REVIEW_CONFIDENCE_THRESHOLD,
    RawReport,
    ReportEmbedding,
    ReportTranscription,
)
from sarana_shared.db.outbox import make_outbox_model

# incident-svc's own outbox table: outbox.incident_svc_event.
OutboxEvent = make_outbox_model("incident_svc")

__all__ = [
    "DISPATCH_STATUSES",
    "EMBEDDING_DIMENSIONS",
    "HUMAN_REVIEW_CONFIDENCE_THRESHOLD",
    "INCIDENT_SCHEMA",
    "INCIDENT_STATUSES",
    "INCIDENT_TYPES",
    "INTAKE_CHANNELS",
    "LOCATION_SOURCES",
    "PROCESSING_STATUSES",
    "RESPONDER_STATUSES",
    "RESPONDER_TYPES",
    "DispatchPlan",
    "Incident",
    "OutboxEvent",
    "RawReport",
    "ReportEmbedding",
    "ReportIncidentLink",
    "ReportTranscription",
    "Responder",
    "TriageScore",
]
