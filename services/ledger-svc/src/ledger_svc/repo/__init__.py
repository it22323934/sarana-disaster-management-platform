"""SQLAlchemy models for the `aid` schema - the Transparent Aid Ledger."""

from ledger_svc.repo.accountability import AnomalyFlag, Grievance
from ledger_svc.repo.assessments import (
    CostSchedule,
    CostScheduleLine,
    DamageAssessment,
    DeviceSyncCursor,
    Entitlement,
)
from ledger_svc.repo.base import (
    AID_SCHEMA,
    ANOMALY_DISPOSITIONS,
    ANOMALY_SUBJECTS,
    APPROVAL_DECISIONS,
    APPROVAL_LEVELS,
    ASSESSMENT_STATUSES,
    DAMAGE_CATEGORIES,
    ENTITLEMENT_STATUSES,
    GRIEVANCE_CHANNELS,
    GRIEVANCE_STATUSES,
    GRIEVANCE_SUBJECTS,
    PAYMENT_RAILS,
)
from ledger_svc.repo.ledger import (
    Approval,
    Disbursement,
    DisbursementReversal,
    LedgerAnchor,
)
from sarana_shared.events.outbox import make_outbox_model

# ledger-svc's own outbox table: outbox.ledger_svc_event.
OutboxEvent = make_outbox_model("ledger_svc")

# Tables the application role may never UPDATE or DELETE. The migration revokes those
# grants and installs an append-only trigger on each.
APPEND_ONLY_TABLES: tuple[str, ...] = ("disbursement", "approval", "ledger_anchor")

__all__ = [
    "AID_SCHEMA",
    "ANOMALY_DISPOSITIONS",
    "ANOMALY_SUBJECTS",
    "APPEND_ONLY_TABLES",
    "APPROVAL_DECISIONS",
    "APPROVAL_LEVELS",
    "ASSESSMENT_STATUSES",
    "DAMAGE_CATEGORIES",
    "ENTITLEMENT_STATUSES",
    "GRIEVANCE_CHANNELS",
    "GRIEVANCE_STATUSES",
    "GRIEVANCE_SUBJECTS",
    "PAYMENT_RAILS",
    "AnomalyFlag",
    "Approval",
    "CostSchedule",
    "CostScheduleLine",
    "DamageAssessment",
    "DeviceSyncCursor",
    "Disbursement",
    "DisbursementReversal",
    "Entitlement",
    "Grievance",
    "LedgerAnchor",
    "OutboxEvent",
]
