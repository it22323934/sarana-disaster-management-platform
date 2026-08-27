"""Payload contracts for every event in the catalogue.

This is the contract between every service and every agent. A field here is a promise to
everyone downstream, which is why the evolution rules in `registry.py` are strict.

Payloads carry identifiers and decisions, never personal data. An event log is read by
more people, for longer, than the record it describes was ever meant for - and a replay
three weeks later hands all of it to whoever is debugging. Names, phone numbers and exact
household coordinates stay in the database behind an access check.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sarana_shared.events import catalogue as ev
from sarana_shared.events.registry import register


class EventPayload(BaseModel):
    """Base for every payload. Forbids extra fields so a typo fails at the publisher."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --- Anticipate ---------------------------------------------------------------------


@register(ev.HAZARD_EVENT_DECLARED)
class HazardEventDeclared(EventPayload):
    """A hazard has been declared and the disaster clock has an anchor."""

    hazard_event_id: UUID
    hazard_type: str
    source: str = Field(description="Which mocked government feed declared it")
    declared_at: datetime
    landfall_at: datetime | None = None


@register(ev.HAZARD_READING_INGESTED)
class HazardReadingIngested(EventPayload):
    """One raw observation arrived from one feed."""

    hazard_event_id: UUID
    reading_id: UUID
    source: str
    observed_at: datetime


@register(ev.FORECAST_IMPACT_GENERATED)
class ImpactForecastGenerated(EventPayload):
    """A per-GN-division impact forecast, with the drivers that produced it.

    `drivers` travels on the event, not just in the database. A consumer deciding whether
    to pre-position supplies needs to know what moved the score, and making it fetch that
    separately means it usually will not.
    """

    forecast_id: UUID
    hazard_event_id: UUID
    gn_division_code: str
    impact_class: int = Field(ge=0, le=4)
    confidence: float = Field(ge=0, le=1)
    lead_time_hours: int = Field(ge=0)
    method: str
    drivers: dict[str, float]
    expected_households_affected: int = Field(ge=0)


@register(ev.FORECAST_TRIGGER_FIRED)
class AnticipatoryTriggerFired(EventPayload):
    """A pre-agreed condition was met and something was done about it."""

    trigger_id: UUID
    hazard_event_id: UUID
    gn_division_code: str | None = None
    action_taken: str
    forecast_id: UUID | None = None


# --- Warn ----------------------------------------------------------------------------


@register(ev.ALERT_DRAFTED)
class AlertDrafted(EventPayload):
    """An alert exists in draft. Whether it needs a human depends on its template."""

    alert_id: UUID
    hazard_event_id: UUID
    template_id: UUID | None = None
    severity: str
    urgency: str
    certainty: str
    area_gn_division_codes: list[str]
    # An alert built from a reviewed template dispatches automatically. Free text waits.
    requires_human_signoff: bool


@register(ev.ALERT_SIGNOFF_REQUESTED)
class AlertSignoffRequested(EventPayload):
    """A free-text alert is waiting for a person."""

    alert_id: UUID
    requested_at: datetime


@register(ev.ALERT_SIGNOFF_GRANTED)
class AlertSignoffGranted(EventPayload):
    """A named human approved the alert text."""

    alert_id: UUID
    signed_off_by: UUID
    signed_off_at: datetime


@register(ev.ALERT_DISPATCHED)
class AlertDispatched(EventPayload):
    """The alert has gone out over one channel. Side-effecting: this sent real messages."""

    alert_id: UUID
    dispatch_id: UUID
    channel: str
    target_count: int = Field(ge=0)


@register(ev.ALERT_DELIVERY_CONFIRMED)
class AlertDeliveryConfirmed(EventPayload):
    """Proof one message arrived.

    `language` is on the event because per-language delivery rate is the metric that
    would have caught the Ditwah failure, and a metric nobody can compute is not a metric.
    """

    dispatch_id: UUID
    receipt_id: UUID
    channel: str
    language: str


@register(ev.ALERT_DELIVERY_FAILED)
class AlertDeliveryFailed(EventPayload):
    """A message did not arrive. The recipient is never named on the event."""

    dispatch_id: UUID
    receipt_id: UUID
    channel: str
    language: str
    failure_reason: str


# --- Respond -------------------------------------------------------------------------


@register(ev.INCIDENT_REPORT_RECEIVED)
class IncidentReportReceived(EventPayload):
    """A citizen report arrived. The report text is not on the event.

    Whoever needs the content reads it from the database behind an access check. Putting
    it here would copy every citizen's words into the event log, the archive, and every
    replay of that window.
    """

    report_id: UUID
    channel: str
    received_at: datetime
    reported_language: str | None = None
    gn_division_code: str | None = None
    has_audio: bool = False
    has_images: bool = False


@register(ev.INCIDENT_REPORT_TRANSCRIBED)
class IncidentReportTranscribed(EventPayload):
    """Speech became text, with the confidence that decides what happens next."""

    report_id: UUID
    transcription_id: UUID
    detected_language: str | None = None
    confidence: float = Field(ge=0, le=1)
    needs_human_review: bool


@register(ev.INCIDENT_REPORT_FLAGGED_FOR_REVIEW)
class IncidentReportFlaggedForReview(EventPayload):
    """Low confidence sent this to a person. It never auto-publishes.

    ADR-007: Sinhala and Tamil are low-resource languages and accuracy on them is
    materially worse than English. This event is the visible half of that design decision.
    """

    report_id: UUID
    reason: str
    confidence: float = Field(ge=0, le=1)


@register(ev.INCIDENT_VERIFIED)
class IncidentVerified(EventPayload):
    """A report became a verified incident."""

    incident_id: UUID
    public_ref: str
    gn_division_code: str
    incident_type: str
    severity: int = Field(ge=1, le=5)
    people_at_risk: int = Field(ge=0)


@register(ev.INCIDENT_DUPLICATE_LINKED)
class IncidentDuplicateLinked(EventPayload):
    """Two reports were judged to be about the same thing.

    `similarity` and `linked_by` travel with it because merging two genuinely separate
    emergencies is a life-safety failure and the decision has to be reviewable.
    """

    incident_id: UUID
    report_id: UUID
    similarity: float = Field(ge=0, le=1)
    linked_by: str


@register(ev.INCIDENT_TRIAGED)
class IncidentTriaged(EventPayload):
    """A priority score, with the factors that produced it."""

    incident_id: UUID
    score: float = Field(ge=0, le=1)
    model_version: str
    factors: dict[str, float]
    rank_in_queue: int | None = None


@register(ev.DISPATCH_PLAN_PROPOSED)
class DispatchPlanProposed(EventPayload):
    """An agent has proposed sending people somewhere. Nothing has been sent yet."""

    plan_id: UUID
    incident_ids: list[UUID]
    responder_ids: list[UUID]
    estimated_duration_min: int | None = None
    proposed_by_agent: str


@register(ev.DISPATCH_SIGNOFF_REQUESTED)
class DispatchSignoffRequested(EventPayload):
    """The plan is waiting at the first mandatory human gate."""

    plan_id: UUID
    requested_at: datetime
    langgraph_thread_id: str | None = None


@register(ev.DISPATCH_SIGNOFF_GRANTED)
class DispatchSignoffGranted(EventPayload):
    """A named human committed the plan, having re-proved their second factor."""

    plan_id: UUID
    signed_off_by: UUID
    signed_off_at: datetime


@register(ev.DISPATCH_SIGNOFF_REJECTED)
class DispatchSignoffRejected(EventPayload):
    """A human refused the plan, and said why."""

    plan_id: UUID
    rejected_by: UUID
    rejected_at: datetime
    reason: str


@register(ev.DISPATCH_RELEASED)
class DispatchReleased(EventPayload):
    """Responders are being sent. Side-effecting: crews are moving on this."""

    plan_id: UUID
    incident_ids: list[UUID]
    responder_ids: list[UUID]
    released_at: datetime


@register(ev.INCIDENT_RESOLVED)
class IncidentResolved(EventPayload):
    """The situation is over. Feeds the Learn loop."""

    incident_id: UUID
    resolved_at: datetime
    outcome: str


# --- Sustain -------------------------------------------------------------------------


@register(ev.AID_ASSESSMENT_SUBMITTED)
class AidAssessmentSubmitted(EventPayload):
    """A GN officer submitted a damage assessment, possibly after days offline."""

    assessment_id: UUID
    public_ref: str
    gn_division_code: str
    hazard_event_id: UUID
    category: str
    cost_estimate_lkr_cents: int = Field(ge=0)
    # The client operation id from the offline log. Consumers use it to recognise a
    # resubmission of work they have already seen (ADR-006).
    client_operation_id: str


@register(ev.AID_ENTITLEMENT_CALCULATED)
class AidEntitlementCalculated(EventPayload):
    """What an assessment is worth, and under which schedule.

    `cost_schedule_version` travels with the amount so a consumer never has to guess
    which schedule produced a figure it is comparing against.
    """

    entitlement_id: UUID
    assessment_id: UUID
    calculated_lkr_cents: int = Field(ge=0)
    cost_schedule_version: str
    requires_district_approval: bool


@register(ev.AID_APPROVAL_RECORDED)
class AidApprovalRecorded(EventPayload):
    """One approval decision at one level."""

    approval_id: UUID
    entitlement_id: UUID
    level: str
    approver_id: UUID
    decision: str
    entry_hash: str = Field(description="Position in the hash chain, for verification")


@register(ev.AID_DISBURSEMENT_RELEASED)
class AidDisbursementReleased(EventPayload):
    """Money was released. Side-effecting: this moved funds on a payment rail.

    A replay must never reach the consumer that talks to the bank. That is the single
    clearest reason the refusal mechanism exists.
    """

    disbursement_id: UUID
    entitlement_id: UUID
    amount_lkr_cents: int = Field(gt=0)
    released_by: UUID
    released_at: datetime
    payment_rail: str
    seq: int = Field(description="Position in the ledger, for the daily Merkle root")
    entry_hash: str


@register(ev.AID_DISBURSEMENT_CITIZEN_CONFIRMED)
class AidDisbursementCitizenConfirmed(EventPayload):
    """The household said the money arrived.

    A ledger recording only what the state believes it paid is not evidence that anyone
    was paid. This closes the loop from the other end.
    """

    disbursement_id: UUID
    confirmed_at: datetime
    channel: str


@register(ev.AID_ANOMALY_FLAGGED)
class AidAnomalyFlagged(EventPayload):
    """A pattern warranting review. Never public, and it names no one (ADR-009).

    The rationale is deliberately absent from the event. Flags are private, and an event
    log is the least private place in the platform.
    """

    flag_id: UUID
    subject_type: str
    subject_id: UUID
    detector: str
    detector_version: str
    score: float = Field(ge=0, le=1)


@register(ev.AID_ANOMALY_DISPOSED)
class AidAnomalyDisposed(EventPayload):
    """A human closed a flag.

    `disposition` includes FALSE_POSITIVE because the false-positive rate is a tracked
    metric reported alongside the detection rate, and it can only be computed if the
    outcome is recorded.
    """

    flag_id: UUID
    disposition: str
    disposed_at: datetime


@register(ev.AID_GRIEVANCE_RAISED)
class AidGrievanceRaised(EventPayload):
    """A citizen is disputing something that affects their household (ADR-008)."""

    grievance_id: UUID
    public_ref: str
    subject_type: str
    channel: str
    assigned_ds_division_code: str | None = None
    sla_due_at: datetime


@register(ev.AID_GRIEVANCE_RESOLVED)
class AidGrievanceResolved(EventPayload):
    """A grievance was closed, within its SLA or not.

    `within_sla` is on the event because resolution time appears on the public dashboard,
    and a mechanism whose performance is not published is a mechanism on paper only.
    """

    grievance_id: UUID
    status: str
    resolved_at: datetime
    within_sla: bool


# --- Cross-cutting -------------------------------------------------------------------


@register(ev.RESILIENCE_OBSERVATION_APPENDED)
class ResilienceObservationAppended(EventPayload):
    """An agent appended a fact to the Resilience Graph (ADR-012)."""

    observation_id: UUID
    entity_id: UUID
    entity_type: str
    observation_type: str
    source_agent: str
    confidence: float = Field(ge=0, le=1)


@register(ev.AUDIT_ENTRY_WRITTEN)
class AuditEntryWritten(EventPayload):
    """Something was recorded in the append-only action log.

    Carries the position in the chain, not the content. The content is in the audit log,
    which has its own access control for a reason.
    """

    entry_id: UUID
    seq: int
    actor_type: str
    action: str
    subject_type: str
    entry_hash: str
