"""Anomaly flags and grievances: the two accountability paths.

They point in opposite directions on purpose. An anomaly flag is the system questioning a
pattern in the data; a grievance is a citizen questioning the system. A transparency
platform that has only the first is surveillance.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ledger_svc.repo.base import (
    AID_SCHEMA,
    ANOMALY_DISPOSITIONS,
    ANOMALY_SUBJECTS,
    GRIEVANCE_CHANNELS,
    GRIEVANCE_STATUSES,
    GRIEVANCE_SUBJECTS,
)
from sarana_shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from sarana_shared.db.constraints import in_list, localised, no_individual_named


class AnomalyFlag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A pattern that warrants review. Never public, never names a person (ADR-009).

    `rationale` carries a CHECK that rejects any document containing an officer id, an
    assessor id or a user id at any depth. Divisions with genuinely worse damage will
    legitimately look like outliers - that is the damage behaving as expected, not
    evidence about whoever assessed it. A system that gets this wrong does more harm than
    the fraud it catches.

    Every flag needs a human disposition before it can close, and FALSE_POSITIVE is a
    first-class outcome because the false-positive rate is a tracked metric reported
    alongside the detection rate.
    """

    __tablename__ = "anomaly_flag"
    __table_args__ = (
        no_individual_named("rationale"),
        CheckConstraint(in_list("subject_type", ANOMALY_SUBJECTS), name="subject_type_known"),
        CheckConstraint(in_list("disposition", ANOMALY_DISPOSITIONS), name="disposition_known"),
        CheckConstraint("score BETWEEN 0 AND 1", name="score_range"),
        CheckConstraint("jsonb_typeof(rationale) = 'object'", name="rationale_is_object"),
        CheckConstraint("rationale <> '{}'::jsonb", name="rationale_not_empty"),
        # A closed flag must record who closed it and why. An open flag must not.
        CheckConstraint(
            "(disposition = 'OPEN' AND disposed_by IS NULL AND disposed_at IS NULL)"
            " OR (disposition <> 'OPEN' AND disposed_by IS NOT NULL"
            "     AND disposed_at IS NOT NULL AND disposition_note IS NOT NULL)",
            name="disposition_is_attributed",
        ),
        Index("ix_anomaly_flag_subject", "subject_type", "subject_id"),
        Index("ix_anomaly_flag_open", "disposition"),
        {"schema": AID_SCHEMA},
    )

    subject_type: Mapped[str] = mapped_column(String(24), nullable=False)
    subject_id: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    detector: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detector_version: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    rationale: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raised_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    disposition: Mapped[str] = mapped_column(String(24), nullable=False, server_default="OPEN")
    disposed_by: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    disposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disposition_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class Grievance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A citizen disputing an assessment, entitlement, disbursement or exclusion.

    ADR-008: this is Phase 1, not future work. Sphere and the Core Humanitarian Standard
    both require a complaints mechanism, and a transparency system that is auditable by
    outsiders but not contestable by the affected household is not transparent to the
    person who matters most.

    Grievances route to DS, carry an SLA clock, and their counts and resolution times
    appear on the public dashboard - which is what stops the mechanism from existing on
    paper only.
    """

    __tablename__ = "grievance"
    __table_args__ = (
        localised("description"),
        localised("resolution", nullable=True),
        CheckConstraint(in_list("channel", GRIEVANCE_CHANNELS), name="channel_known"),
        CheckConstraint(in_list("status", GRIEVANCE_STATUSES), name="status_known"),
        CheckConstraint(in_list("subject_type", GRIEVANCE_SUBJECTS), name="subject_type_known"),
        CheckConstraint(
            "public_ref ~ '^GRV-[0-9]{6}-[0-9A-HJKMNP-TV-Z]{6}$'", name="public_ref_shape"
        ),
        CheckConstraint("sla_due_at > raised_at", name="sla_is_in_the_future"),
        # A resolved grievance owes the household an explanation, in their language.
        CheckConstraint(
            "status NOT IN ('RESOLVED','REJECTED')"
            " OR (resolved_at IS NOT NULL AND resolution IS NOT NULL)",
            name="resolution_is_explained",
        ),
        Index("ix_grievance_subject", "subject_type", "subject_id"),
        Index("ix_grievance_ds_status", "assigned_ds_division_code", "status"),
        Index("ix_grievance_sla", "sla_due_at"),
        {"schema": AID_SCHEMA},
    )

    public_ref: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    household_id: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(24), nullable=False)
    subject_id: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    raised_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    description: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="RECEIVED", index=True
    )

    assigned_ds_division_id: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    assigned_ds_division_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)

    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
