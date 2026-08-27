"""SQLAlchemy models for the `hazard` schema."""

from agent_svc.repo.base import (
    FORECAST_METHODS,
    HAZARD_SCHEMA,
    HAZARD_SOURCES,
    HAZARD_STATUSES,
    HAZARD_TYPES,
    TRIGGER_ACTIONS,
)
from agent_svc.repo.hazard import (
    AnticipatoryTrigger,
    HazardEvent,
    HazardFeedReading,
    ImpactForecast,
)
from sarana_shared.events.outbox import make_outbox_model

# agent-svc's own outbox table: outbox.agent_svc_event.
OutboxEvent = make_outbox_model("agent_svc")

__all__ = [
    "FORECAST_METHODS",
    "HAZARD_SCHEMA",
    "HAZARD_SOURCES",
    "HAZARD_STATUSES",
    "HAZARD_TYPES",
    "TRIGGER_ACTIONS",
    "AnticipatoryTrigger",
    "HazardEvent",
    "HazardFeedReading",
    "ImpactForecast",
    "OutboxEvent",
]
