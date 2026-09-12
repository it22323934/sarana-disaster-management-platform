"""Citizen reports and their transcription.

A raw report is what actually arrived: an SMS, a voice note, a photo, a form. It is kept
verbatim and never edited. Everything the platform derives from it - transcription,
translation, geolocation, dedup - hangs off it and carries its own confidence.

ADR-007: Sinhala and Tamil are low-resource languages and ASR accuracy on them is
materially worse than English. That makes the confidence gate to human review the
headline design decision here, not a footnote.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from incident_svc.repo.base import (
    EMBEDDING_DIMENSIONS,
    INCIDENT_SCHEMA,
    INTAKE_CHANNELS,
    LOCATION_SOURCES,
    PROCESSING_STATUSES,
)
from sarana_shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from sarana_shared.db.constraints import confidence_range, in_list
from sarana_shared.domain.geo import SRID_WGS84

# Below this, a transcription or translation must be seen by a human before anything
# downstream may act on it. Non-negotiable #7.
HUMAN_REVIEW_CONFIDENCE_THRESHOLD = 0.75


class RawReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A report exactly as it arrived. Never edited, never deleted.

    The sender is stored as an HMAC, not a number: inbound SMS resolves to a household
    without the platform ever holding a plaintext phone number for routing.
    """

    __tablename__ = "raw_report"
    __table_args__ = (
        CheckConstraint(in_list("channel", INTAKE_CHANNELS), name="channel_known"),
        CheckConstraint(
            in_list("processing_status", PROCESSING_STATUSES), name="processing_status_known"
        ),
        CheckConstraint(
            "reported_language IS NULL OR reported_language IN ('si','ta','en')",
            name="reported_language_supported",
        ),
        CheckConstraint(
            "location_source IS NULL OR " + in_list("location_source", LOCATION_SOURCES),
            name="location_source_known",
        ),
        # A point with no accuracy is not trusted for dispatch, so it may not exist.
        CheckConstraint(
            "reported_location IS NULL OR location_accuracy_m IS NOT NULL",
            name="location_has_accuracy",
        ),
        CheckConstraint(
            "location_accuracy_m IS NULL OR location_accuracy_m > 0",
            name="location_accuracy_positive",
        ),
        Index("ix_raw_report_location", "reported_location", postgresql_using="gist"),
        Index("ix_raw_report_received_at", "received_at"),
        Index("ix_raw_report_sender", "sender_msisdn_hash"),
        {"schema": INCIDENT_SCHEMA},
    )

    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    sender_msisdn_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender_household_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )

    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_audio_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_image_uris: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

    reported_language: Mapped[str | None] = mapped_column(String(2), nullable=True)
    reported_location: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=SRID_WGS84, spatial_index=False), nullable=True
    )
    location_accuracy_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_source: Mapped[str | None] = mapped_column(String(16), nullable=True)

    processing_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="RECEIVED", index=True
    )


class ReportTranscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """What the ASR and translation produced, with the confidence that decides its fate.

    `needs_human_review` is derived from `confidence` by a generated column rather than
    set by the caller. A gate that the calling code can forget to apply is not a gate,
    and the whole safety argument for low-resource-language ASR rests on this one.
    """

    __tablename__ = "report_transcription"
    __table_args__ = (
        confidence_range("confidence"),
        CheckConstraint(
            "detected_language IS NULL OR detected_language IN ('si','ta','en')",
            name="detected_language_supported",
        ),
        # A reviewed transcription must name its reviewer.
        CheckConstraint(
            "(reviewed_text IS NULL) = (reviewed_by IS NULL)", name="review_is_attributed"
        ),
        Index("ix_report_transcription_review", "needs_human_review"),
        {"schema": INCIDENT_SCHEMA},
    )

    raw_report_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{INCIDENT_SCHEMA}.raw_report.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    detected_language: Mapped[str | None] = mapped_column(String(2), nullable=True)

    text_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)

    needs_human_review: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=None,
        doc="Generated from confidence by the migration; never written by the application",
    )

    reviewed_by: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    reviewed_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReportEmbedding(Base):
    """The vector used to find candidate duplicates of a report.

    Keyed on the report rather than given its own id: exactly one embedding per report,
    and the FK is the natural primary key.
    """

    __tablename__ = "report_embedding"
    __table_args__ = (
        Index(
            "ix_report_embedding_vector",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        {"schema": INCIDENT_SCHEMA},
    )

    raw_report_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{INCIDENT_SCHEMA}.raw_report.id", ondelete="CASCADE"),
        primary_key=True,
    )
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
