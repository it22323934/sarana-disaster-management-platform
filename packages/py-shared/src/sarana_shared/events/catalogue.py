"""The event type catalogue.

Named `catalogue` rather than `types`: a module called `types.py` shadows the standard
library module of that name for anything running with this directory on `sys.path`,
and the failure it produces is a circular-import error that names neither file.

Every event SARANA publishes is named here. Nothing publishes a type that is not in this
list: an event nobody declared is an event nobody can consume, replay or reason about.

Grouped by loop - Anticipate, Warn, Respond, Sustain - because that is how the platform is
described and how an operator thinks about it.
"""

from __future__ import annotations

from typing import Final

# --- Anticipate: T-7d to T-72h ------------------------------------------------------
HAZARD_EVENT_DECLARED: Final = "sarana.hazard.event.declared"
HAZARD_READING_INGESTED: Final = "sarana.hazard.reading.ingested"
FORECAST_IMPACT_GENERATED: Final = "sarana.forecast.impact.generated"
FORECAST_TRIGGER_FIRED: Final = "sarana.forecast.trigger.fired"

# --- Warn: T-72h to T-0 -------------------------------------------------------------
ALERT_DRAFTED: Final = "sarana.alert.drafted"
ALERT_SIGNOFF_REQUESTED: Final = "sarana.alert.signoff.requested"
ALERT_SIGNOFF_GRANTED: Final = "sarana.alert.signoff.granted"
ALERT_DISPATCHED: Final = "sarana.alert.dispatched"
ALERT_DELIVERY_CONFIRMED: Final = "sarana.alert.delivery.confirmed"
ALERT_DELIVERY_FAILED: Final = "sarana.alert.delivery.failed"

# --- Respond: T-0 onward ------------------------------------------------------------
INCIDENT_REPORT_RECEIVED: Final = "sarana.incident.report.received"
INCIDENT_REPORT_TRANSCRIBED: Final = "sarana.incident.report.transcribed"
INCIDENT_REPORT_FLAGGED_FOR_REVIEW: Final = "sarana.incident.report.flagged_for_review"
INCIDENT_VERIFIED: Final = "sarana.incident.verified"
INCIDENT_DUPLICATE_LINKED: Final = "sarana.incident.duplicate.linked"
INCIDENT_TRIAGED: Final = "sarana.incident.triaged"
DISPATCH_PLAN_PROPOSED: Final = "sarana.dispatch.plan.proposed"
DISPATCH_SIGNOFF_REQUESTED: Final = "sarana.dispatch.signoff.requested"
DISPATCH_SIGNOFF_GRANTED: Final = "sarana.dispatch.signoff.granted"
DISPATCH_SIGNOFF_REJECTED: Final = "sarana.dispatch.signoff.rejected"
DISPATCH_RELEASED: Final = "sarana.dispatch.released"
INCIDENT_RESOLVED: Final = "sarana.incident.resolved"

# --- Sustain: T+1d to T+90d ---------------------------------------------------------
AID_ASSESSMENT_SUBMITTED: Final = "sarana.aid.assessment.submitted"
AID_ENTITLEMENT_CALCULATED: Final = "sarana.aid.entitlement.calculated"
AID_APPROVAL_RECORDED: Final = "sarana.aid.approval.recorded"
AID_DISBURSEMENT_RELEASED: Final = "sarana.aid.disbursement.released"
AID_DISBURSEMENT_CITIZEN_CONFIRMED: Final = "sarana.aid.disbursement.citizen_confirmed"
AID_ANOMALY_FLAGGED: Final = "sarana.aid.anomaly.flagged"
AID_ANOMALY_DISPOSED: Final = "sarana.aid.anomaly.disposed"
AID_GRIEVANCE_RAISED: Final = "sarana.aid.grievance.raised"
AID_GRIEVANCE_RESOLVED: Final = "sarana.aid.grievance.resolved"

# --- Cross-cutting ------------------------------------------------------------------
RESILIENCE_OBSERVATION_APPENDED: Final = "sarana.resilience.observation.appended"
AUDIT_ENTRY_WRITTEN: Final = "sarana.audit.entry.written"


# The complete catalogue. CI asserts that every registered model appears here and that
# every name here has a registered model, so the two cannot drift apart silently.
ALL_EVENT_TYPES: Final[tuple[str, ...]] = (
    HAZARD_EVENT_DECLARED,
    HAZARD_READING_INGESTED,
    FORECAST_IMPACT_GENERATED,
    FORECAST_TRIGGER_FIRED,
    ALERT_DRAFTED,
    ALERT_SIGNOFF_REQUESTED,
    ALERT_SIGNOFF_GRANTED,
    ALERT_DISPATCHED,
    ALERT_DELIVERY_CONFIRMED,
    ALERT_DELIVERY_FAILED,
    INCIDENT_REPORT_RECEIVED,
    INCIDENT_REPORT_TRANSCRIBED,
    INCIDENT_REPORT_FLAGGED_FOR_REVIEW,
    INCIDENT_VERIFIED,
    INCIDENT_DUPLICATE_LINKED,
    INCIDENT_TRIAGED,
    DISPATCH_PLAN_PROPOSED,
    DISPATCH_SIGNOFF_REQUESTED,
    DISPATCH_SIGNOFF_GRANTED,
    DISPATCH_SIGNOFF_REJECTED,
    DISPATCH_RELEASED,
    INCIDENT_RESOLVED,
    AID_ASSESSMENT_SUBMITTED,
    AID_ENTITLEMENT_CALCULATED,
    AID_APPROVAL_RECORDED,
    AID_DISBURSEMENT_RELEASED,
    AID_DISBURSEMENT_CITIZEN_CONFIRMED,
    AID_ANOMALY_FLAGGED,
    AID_ANOMALY_DISPOSED,
    AID_GRIEVANCE_RAISED,
    AID_GRIEVANCE_RESOLVED,
    RESILIENCE_OBSERVATION_APPENDED,
    AUDIT_ENTRY_WRITTEN,
)

# Events whose consumers have real-world side effects: an SMS leaves the building, money
# moves, a crew is sent somewhere. These are what `side_effect_free=False` consumers
# subscribe to, and they are the reason replay has to be refusable.
SIDE_EFFECTING_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        ALERT_DISPATCHED,
        DISPATCH_RELEASED,
        AID_DISBURSEMENT_RELEASED,
    }
)
