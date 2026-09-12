"""Incidents: the deduplicated, verified, prioritised view of what is happening.

Many raw reports become one incident. The link between them carries a similarity score
and says who or what made the link, so a merge is reviewable rather than a fact that
appeared from nowhere.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from incident_svc.repo.base import INCIDENT_SCHEMA, INCIDENT_STATUSES
from sarana_shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from sarana_shared.db.constraints import confidence_range, in_list, localised
from sarana_shared.domain.geo import SRID_WGS84

INCIDENT_TYPES: tuple[str, ...] = (
    "FLOOD",
    "LANDSLIDE",
    "STRUCTURAL_COLLAPSE",
    "MEDICAL",
    "MISSING_PERSON",
    "TRAPPED",
    "EVACUATION_NEEDED",
    "SUPPLIES_NEEDED",
    "INFRASTRUCTURE",
    "OTHER",
)


class Incident(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One real-world situation needing a response.

    `public_ref` is what a citizen is told and what an operator says on the radio -
    `INC-251128-K3M9PQ`. The UUID never leaves the system.
    """

    __tablename__ = "incident"
    __table_args__ = (
        localised("summary", nullable=True),
        CheckConstraint(in_list("status", INCIDENT_STATUSES), name="status_known"),
        CheckConstraint(in_list("type", INCIDENT_TYPES), name="type_known"),
        CheckConstraint("severity BETWEEN 1 AND 5", name="severity_range"),
        CheckConstraint("people_at_risk >= 0", name="people_at_risk_non_negative"),
        confidence_range("location_confidence", nullable=True),
        CheckConstraint(
            "public_ref ~ '^INC-[0-9]{6}-[0-9A-HJKMNP-TV-Z]{6}$'", name="public_ref_shape"
        ),
        # Resolution cannot precede the first report of the problem.
        CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= first_reported_at",
            name="resolved_after_reported",
        ),
        Index("ix_incident_location", "location", postgresql_using="gist"),
        # Operators work the open queue; resolved incidents are read by the Learn loop
        # on a different access path, so they are kept out of the hot index.
        Index(
            "ix_incident_open",
            "gn_division_id",
            "severity",
            postgresql_where=text("status <> 'RESOLVED'"),
        ),
        Index("ix_incident_cluster", "cluster_id"),
        {"schema": INCIDENT_SCHEMA},
    )

    public_ref: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    gn_division_id: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    gn_division_code: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        index=True,
        doc="Denormalised so row-level security is a prefix test, not a three-level join",
    )

    type: Mapped[str] = mapped_column(String(32), nullable=False)
    subtype: Mapped[str | None] = mapped_column(String(48), nullable=True)
    summary: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)

    location: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=SRID_WGS84, spatial_index=False), nullable=True
    )
    location_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)

    people_at_risk: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    severity: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="3")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="REPORTED", index=True
    )

    first_reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    cluster_id: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    is_cluster_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class ReportIncidentLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Which reports were folded into which incident, and on what evidence.

    A dedup decision is auditable: the similarity that justified it and the agent or
    person who made it are both on the row. Merging two genuinely separate emergencies
    is a life-safety failure, so the merge has to be reviewable after the fact.
    """

    __tablename__ = "report_incident_link"
    __table_args__ = (
        UniqueConstraint("raw_report_id", "incident_id", name="uq_report_incident"),
        CheckConstraint("similarity BETWEEN 0 AND 1", name="similarity_range"),
        {"schema": INCIDENT_SCHEMA},
    )

    raw_report_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{INCIDENT_SCHEMA}.raw_report.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    incident_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{INCIDENT_SCHEMA}.incident.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    similarity: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    linked_by: Mapped[str] = mapped_column(
        String(64), nullable=False, doc="Agent name, or the user id of the operator who linked"
    )


class TriageScore(UUIDPrimaryKeyMixin, Base):
    """A priority score with the factors that produced it.

    `factors` is required. A ranking with no explanation cannot be argued with by the
    operator who has to act on it, and cannot be improved by the Learn loop.

    Append-only by convention: rescoring writes a new row, so the queue order at any
    past moment is reconstructable.
    """

    __tablename__ = "triage_score"
    __table_args__ = (
        CheckConstraint("score BETWEEN 0 AND 1", name="score_range"),
        CheckConstraint("jsonb_typeof(factors) = 'object'", name="factors_is_object"),
        CheckConstraint("factors <> '{}'::jsonb", name="factors_not_empty"),
        CheckConstraint("rank_in_queue IS NULL OR rank_in_queue > 0", name="rank_positive"),
        Index("ix_triage_score_incident_time", "incident_id", "scored_at"),
        {"schema": INCIDENT_SCHEMA},
    )

    incident_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{INCIDENT_SCHEMA}.incident.id", ondelete="CASCADE"),
        nullable=False,
    )
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    factors: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rank_in_queue: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
