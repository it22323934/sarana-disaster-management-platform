"""Cost schedules, damage assessments and entitlements.

Money is LKR minor units as `bigint` throughout. Never a float, never a numeric that
could be rendered with a decimal point somewhere it should not be. Every monetary row
records the cost schedule version that produced it, so a schedule revision never
silently rewrites an entitlement that was already calculated and approved.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ledger_svc.repo.base import (
    AID_SCHEMA,
    ASSESSMENT_STATUSES,
    DAMAGE_CATEGORIES,
    ENTITLEMENT_STATUSES,
)
from sarana_shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from sarana_shared.db.constraints import in_list, localised
from sarana_shared.domain.geo import SRID_WGS84


class CostSchedule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A published NDRSC compensation cost schedule.

    Versioned and time-bounded so an entitlement can always be recalculated against the
    schedule that was actually in force on the day it was assessed.
    """

    __tablename__ = "cost_schedule"
    __table_args__ = (
        UniqueConstraint("version", name="uq_cost_schedule_version"),
        CheckConstraint(r"version ~ '^\d{4}\.\d{2}(\.\d+)?$'", name="version_shape"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="effective_period_ordered",
        ),
        {"schema": AID_SCHEMA},
    )

    version: Mapped[str] = mapped_column(String(16), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)


class CostScheduleLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One rate in a schedule, with the formula that is published on the dashboard.

    `formula` is not decoration. A household told it is entitled to a given amount can
    read the same formula the system used, which is what makes the figure contestable
    rather than merely announced.
    """

    __tablename__ = "cost_schedule_line"
    __table_args__ = (
        UniqueConstraint(
            "cost_schedule_id", "category", "subcategory", name="uq_cost_schedule_line"
        ),
        localised("description"),
        CheckConstraint(in_list("category", DAMAGE_CATEGORIES), name="category_known"),
        CheckConstraint("rate_lkr_cents >= 0", name="rate_non_negative"),
        CheckConstraint(
            "cap_lkr_cents IS NULL OR cap_lkr_cents >= rate_lkr_cents", name="cap_above_rate"
        ),
        {"schema": AID_SCHEMA},
    )

    cost_schedule_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{AID_SCHEMA}.cost_schedule.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    subcategory: Mapped[str] = mapped_column(String(48), nullable=False, server_default="")
    description: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    unit: Mapped[str] = mapped_column(String(24), nullable=False)
    rate_lkr_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cap_lkr_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    formula: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class DamageAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A GN officer's assessment of what one household lost.

    Written offline in the Field Companion and synced later. `client_operation_id` is the
    idempotency key from the client's append-only operation log (ADR-006): replaying the
    log after a lost connection cannot create a second assessment.

    `gps_at_assessment` records where the officer stood, not where the household is. The
    two are compared as one of several inputs to anomaly detection - an assessment filed
    from thirty kilometres away is worth a look.
    """

    __tablename__ = "damage_assessment"
    __table_args__ = (
        UniqueConstraint("client_operation_id", name="uq_assessment_client_operation"),
        CheckConstraint(in_list("status", ASSESSMENT_STATUSES), name="status_known"),
        CheckConstraint(in_list("category", DAMAGE_CATEGORIES), name="category_known"),
        CheckConstraint("cost_estimate_lkr_cents >= 0", name="cost_estimate_non_negative"),
        CheckConstraint(
            "public_ref ~ '^DMG-[0-9]{6}-[0-9A-HJKMNP-TV-Z]{6}$'", name="public_ref_shape"
        ),
        # An accepted assessment must carry evidence. A photo hash that nobody can
        # reproduce is the difference between an audit and a shrug.
        CheckConstraint(
            "status <> 'ACCEPTED' OR evidence_hash IS NOT NULL",
            name="accepted_assessment_has_evidence",
        ),
        CheckConstraint(
            "gps_accuracy_m IS NULL OR gps_accuracy_m > 0", name="gps_accuracy_positive"
        ),
        Index("ix_damage_assessment_gps", "gps_at_assessment", postgresql_using="gist"),
        Index("ix_damage_assessment_household", "household_id"),
        Index("ix_damage_assessment_division_status", "gn_division_code", "status"),
        {"schema": AID_SCHEMA},
    )

    public_ref: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    household_id: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    gn_division_id: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    gn_division_code: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        doc="Denormalised so row-level security is a prefix test, not a three-level join",
    )
    hazard_event_id: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)

    assessed_by: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    category: Mapped[str] = mapped_column(String(32), nullable=False)
    subcategory: Mapped[str] = mapped_column(String(48), nullable=False, server_default="")
    cost_estimate_lkr_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)

    evidence_photo_uris: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    evidence_hash: Mapped[str | None] = mapped_column(Text, nullable=True)

    gps_at_assessment: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=SRID_WGS84, spatial_index=False), nullable=True
    )
    gps_accuracy_m: Mapped[int | None] = mapped_column(Integer, nullable=True)

    client_operation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="DRAFT", index=True
    )
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class Entitlement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """What one accepted assessment is worth under one cost schedule.

    `calculation_trace` is NOT NULL and must be a non-empty object. An entitlement that
    cannot show its working is not auditable, and the public transparency claim rests on
    exactly that: anyone can follow the schedule line, the inputs and the arithmetic from
    the assessment to the figure.
    """

    __tablename__ = "entitlement"
    __table_args__ = (
        UniqueConstraint("assessment_id", name="uq_entitlement_assessment"),
        CheckConstraint(in_list("status", ENTITLEMENT_STATUSES), name="status_known"),
        CheckConstraint("calculated_lkr_cents >= 0", name="amount_non_negative"),
        CheckConstraint("jsonb_typeof(calculation_trace) = 'object'", name="trace_is_object"),
        CheckConstraint("calculation_trace <> '{}'::jsonb", name="trace_not_empty"),
        CheckConstraint(r"cost_schedule_version ~ '^\d{4}\.\d{2}(\.\d+)?$'", name="version_shape"),
        {"schema": AID_SCHEMA},
    )

    assessment_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{AID_SCHEMA}.damage_assessment.id", ondelete="RESTRICT"),
        nullable=False,
    )
    cost_schedule_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{AID_SCHEMA}.cost_schedule.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    cost_schedule_version: Mapped[str] = mapped_column(String(16), nullable=False)

    calculated_lkr_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    calculation_trace: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="CALCULATED", index=True
    )
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class DeviceSyncCursor(Base):
    """The highest operation seq the server has accepted from one field device.

    The one piece of state the assessments themselves cannot supply. Without it a batch
    arriving as 8, 9, 10 after 7 was lost is indistinguishable from the next three
    operations in order, and the record gets rebuilt out of an update whose create never
    arrived.

    Moves forward only. A device that is reset gets a new `device_id`; rewinding a cursor
    would let a replayed log overwrite work already accepted.
    """

    __tablename__ = "device_sync_cursor"
    __table_args__ = (
        CheckConstraint("last_applied_seq >= 0", name="cursor_non_negative"),
        CheckConstraint(
            "blocked_on_seq IS NULL OR blocked_on_seq > last_applied_seq",
            name="block_is_ahead_of_the_cursor",
        ),
        {"schema": AID_SCHEMA},
    )

    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_applied_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    blocked_on_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
