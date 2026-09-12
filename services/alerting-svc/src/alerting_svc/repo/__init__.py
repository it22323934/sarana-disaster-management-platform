"""SQLAlchemy models for the `alerting` schema."""

from alerting_svc.repo.alerts import Alert, AlertDispatch, AlertTemplate, DeliveryReceipt
from alerting_svc.repo.base import (
    ALERT_STATUSES,
    ALERTING_SCHEMA,
    CAP_CERTAINTIES,
    CAP_SEVERITIES,
    CAP_URGENCIES,
    DELIVERY_STATUSES,
    DISPATCH_CHANNELS,
    DISPATCH_STATUSES,
    HAZARD_TYPES,
    TEMPLATE_STATUSES,
)
from sarana_shared.events.outbox import make_outbox_model

# alerting-svc's own outbox table: outbox.alerting_svc_event.
OutboxEvent = make_outbox_model("alerting_svc")

__all__ = [
    "ALERTING_SCHEMA",
    "ALERT_STATUSES",
    "CAP_CERTAINTIES",
    "CAP_SEVERITIES",
    "CAP_URGENCIES",
    "DELIVERY_STATUSES",
    "DISPATCH_CHANNELS",
    "DISPATCH_STATUSES",
    "HAZARD_TYPES",
    "TEMPLATE_STATUSES",
    "Alert",
    "AlertDispatch",
    "AlertTemplate",
    "DeliveryReceipt",
    "OutboxEvent",
]
