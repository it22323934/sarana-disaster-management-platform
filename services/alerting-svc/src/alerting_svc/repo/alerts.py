"""Alert templates, alerts, dispatches and delivery receipts.

Every citizen-facing string here carries a database CHECK requiring si, ta and en. That
is the whole point of this schema: on 28 November 2025 the DMC and Defence Ministry
press conference on Cyclone Ditwah went out in Sinhala and English only, and
Tamil-speaking communities on the east coast - where the cyclone made landfall - were
left without the warning. A record like that cannot be written here.

Templates are pre-translated and native-speaker reviewed. Machine translation at dispatch
time is never acceptable for a life-safety message. An alert built from a reviewed
template dispatches automatically; an alert containing free text that is not from a
template requires human sign-off.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
from sarana_shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from sarana_shared.db.constraints import in_list, localised
from sarana_shared.domain.geo import SRID_WGS84


class AlertTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A pre-translated, reviewed alert body.

    A template may only reach PUBLISHED once a named native speaker has signed off the
    Sinhala and the Tamil. English is the drafting language, so it needs no separate
    reviewer - but si and ta both do, and the constraint says so.
    """

    __tablename__ = "alert_template"
    __table_args__ = (
        localised("body"),
        UniqueConstraint("code", "version", name="uq_alert_template_code_version"),
        CheckConstraint(in_list("status", TEMPLATE_STATUSES), name="status_known"),
        CheckConstraint(in_list("hazard_type", HAZARD_TYPES), name="hazard_type_known"),
        CheckConstraint(in_list("severity", CAP_SEVERITIES), name="severity_known"),
        CheckConstraint(in_list("urgency", CAP_URGENCIES), name="urgency_known"),
        CheckConstraint(in_list("certainty", CAP_CERTAINTIES), name="certainty_known"),
        CheckConstraint("version > 0", name="version_positive"),
        # Not publishable until a native speaker has reviewed both non-English locales.
        CheckConstraint(
            "status NOT IN ('NATIVE_REVIEWED','PUBLISHED')"
            " OR (reviewed_by_si IS NOT NULL AND reviewed_by_ta IS NOT NULL"
            "     AND reviewed_at IS NOT NULL)",
            name="review_requires_native_speakers",
        ),
        {"schema": ALERTING_SCHEMA},
    )

    code: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    hazard_type: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(12), nullable=False)
    urgency: Mapped[str] = mapped_column(String(12), nullable=False)
    certainty: Mapped[str] = mapped_column(String(12), nullable=False)

    body: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)

    reviewed_by_si: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    reviewed_by_ta: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="DRAFT")


class Alert(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One CAP alert. Headline, description and instruction are all required in si/ta/en.

    `requires_human_signoff` is the third, softer gate in the autonomy model: an alert
    assembled from a reviewed template goes out automatically, and anything carrying free
    text that did not come from a template waits for a person.
    """

    __tablename__ = "alert"
    __table_args__ = (
        localised("headline"),
        localised("description"),
        localised("instruction"),
        CheckConstraint(in_list("status", ALERT_STATUSES), name="status_known"),
        CheckConstraint(in_list("severity", CAP_SEVERITIES), name="severity_known"),
        CheckConstraint(in_list("urgency", CAP_URGENCIES), name="urgency_known"),
        CheckConstraint(in_list("certainty", CAP_CERTAINTIES), name="certainty_known"),
        CheckConstraint("expires_at > effective_at", name="expiry_after_effective"),
        CheckConstraint("cardinality(area_gn_division_ids) > 0", name="alert_covers_an_area"),
        # The softer third gate, at rest: free text cannot have been dispatched without
        # a named human having signed it off.
        CheckConstraint(
            "status NOT IN ('DISPATCHING','DISPATCHED')"
            " OR requires_human_signoff = false"
            " OR (signed_off_by IS NOT NULL AND signed_off_at IS NOT NULL)",
            name="free_text_requires_signoff",
        ),
        # An alert built from no template is by definition free text.
        CheckConstraint(
            "template_id IS NOT NULL OR requires_human_signoff = true",
            name="untemplated_alert_is_gated",
        ),
        Index("ix_alert_geom", "geom", postgresql_using="gist"),
        Index("ix_alert_effective", "effective_at"),
        {"schema": ALERTING_SCHEMA},
    )

    hazard_event_id: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    template_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ALERTING_SCHEMA}.alert_template.id", ondelete="RESTRICT"),
        nullable=True,
    )

    cap_identifier: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    cap_xml: Mapped[str | None] = mapped_column(Text, nullable=True)

    headline: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    description: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    instruction: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)

    severity: Mapped[str] = mapped_column(String(12), nullable=False)
    urgency: Mapped[str] = mapped_column(String(12), nullable=False)
    certainty: Mapped[str] = mapped_column(String(12), nullable=False)

    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    area_gn_division_ids: Mapped[list[Any]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False
    )
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=SRID_WGS84, spatial_index=False),
        nullable=True,
    )

    requires_human_signoff: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    signed_off_by: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    signed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="DRAFT", index=True
    )
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class AlertDispatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One alert going out over one channel.

    Fan-out is per channel so that a failing telco gateway degrades that channel alone.
    An SMS outage must not stop the app push or the radio bulletin.
    """

    __tablename__ = "alert_dispatch"
    __table_args__ = (
        UniqueConstraint("alert_id", "channel", name="uq_alert_dispatch_channel"),
        CheckConstraint(in_list("channel", DISPATCH_CHANNELS), name="channel_known"),
        CheckConstraint(in_list("status", DISPATCH_STATUSES), name="status_known"),
        CheckConstraint("target_count >= 0", name="target_count_non_negative"),
        CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="completed_after_started",
        ),
        {"schema": ALERTING_SCHEMA},
    )

    alert_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ALERTING_SCHEMA}.alert.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(12), nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="QUEUED")


class DeliveryReceipt(UUIDPrimaryKeyMixin, Base):
    """Proof that a specific message reached, or failed to reach, a specific recipient.

    Delivery proof is the point: "we issued a warning" is not the same claim as "it
    arrived". The recipient is stored as a hash, never a number - a delivery log is one
    of the easiest places for a phone book to accumulate.

    `language` records which of the three the recipient was actually served, so the
    per-language delivery rate is measurable rather than assumed.
    """

    __tablename__ = "delivery_receipt"
    __table_args__ = (
        CheckConstraint(in_list("channel", DISPATCH_CHANNELS), name="channel_known"),
        CheckConstraint(in_list("status", DELIVERY_STATUSES), name="status_known"),
        CheckConstraint("language IN ('si','ta','en')", name="language_supported"),
        CheckConstraint(
            "status <> 'FAILED' OR failure_reason IS NOT NULL", name="failure_has_a_reason"
        ),
        Index("ix_delivery_receipt_dispatch_status", "dispatch_id", "status"),
        Index("ix_delivery_receipt_target", "target_ref_hash"),
        {"schema": ALERTING_SCHEMA},
    )

    dispatch_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ALERTING_SCHEMA}.alert_dispatch.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(12), nullable=False)
    target_ref_hash: Mapped[str] = mapped_column(
        Text, nullable=False, doc="HMAC of the recipient reference. Never a plaintext number."
    )
    language: Mapped[str] = mapped_column(String(2), nullable=False)

    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="QUEUED")
    status_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    provider_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
