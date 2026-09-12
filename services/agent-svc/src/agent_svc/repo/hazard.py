"""Hazard events, feed readings, impact forecasts and anticipatory triggers."""

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
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from agent_svc.repo.base import (
    FORECAST_METHODS,
    HAZARD_SCHEMA,
    HAZARD_SOURCES,
    HAZARD_STATUSES,
    HAZARD_TYPES,
    TRIGGER_ACTIONS,
)
from sarana_shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from sarana_shared.db.constraints import confidence_range, in_list, localised
from sarana_shared.domain.geo import SRID_WGS84


class HazardEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One named hazard, from first monitoring through to closure.

    `landfall_at` anchors the whole disaster timeline. Every runbook, situation report
    and demo speaks in offsets from it - T-72h, T+14d - and `DisasterClock` in
    `sarana_shared` converts between those and absolute UTC.
    """

    __tablename__ = "hazard_event"
    __table_args__ = (
        localised("name"),
        UniqueConstraint("source", "source_ref", name="uq_hazard_event_source_ref"),
        CheckConstraint(in_list("type", HAZARD_TYPES), name="type_known"),
        CheckConstraint(in_list("status", HAZARD_STATUSES), name="status_known"),
        CheckConstraint(in_list("source", HAZARD_SOURCES), name="source_known"),
        Index("ix_hazard_event_geom", "geom", postgresql_using="gist"),
        Index("ix_hazard_event_status", "status"),
        {"schema": HAZARD_SCHEMA},
    )

    type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(128), nullable=False)

    declared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    landfall_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="MONITORING")

    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=SRID_WGS84, spatial_index=False),
        nullable=True,
    )
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class HazardFeedReading(UUIDPrimaryKeyMixin, Base):
    """One raw observation from one feed, kept verbatim.

    Append-only by convention. A forecast that cannot be re-derived from the readings
    that produced it cannot be reviewed after the event, and the Learn loop depends on
    exactly that re-derivation.
    """

    __tablename__ = "hazard_feed_reading"
    __table_args__ = (
        CheckConstraint(in_list("source", HAZARD_SOURCES), name="source_known"),
        Index("ix_hazard_feed_reading_event_time", "hazard_event_id", "observed_at"),
        Index("ix_hazard_feed_reading_payload", "payload", postgresql_using="gin"),
        {"schema": HAZARD_SCHEMA},
    )

    hazard_event_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{HAZARD_SCHEMA}.hazard_event.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ImpactForecast(UUIDPrimaryKeyMixin, Base):
    """A per-GN-division impact forecast, with the drivers that produced it.

    `drivers` is required and must be non-empty. A forecast with no explanation of what
    moved the score is not allowed to be written - the entire point of this loop is
    getting past "150mm of rain" to "these 40 divisions, this many households, this
    likely loss of road access".

    Forecasts are never updated. A new run writes a new row, and the UNIQUE key includes
    `generated_at` so the whole forecast history for a division is reconstructable - that
    is what makes the Learn loop's accuracy scoring honest.
    """

    __tablename__ = "impact_forecast"
    __table_args__ = (
        UniqueConstraint(
            "hazard_event_id",
            "gn_division_id",
            "generated_at",
            name="uq_impact_forecast_run",
        ),
        CheckConstraint("impact_class BETWEEN 0 AND 4", name="impact_class_range"),
        confidence_range("confidence"),
        CheckConstraint(in_list("method", FORECAST_METHODS), name="method_known"),
        CheckConstraint("jsonb_typeof(drivers) = 'object'", name="drivers_is_object"),
        CheckConstraint("drivers <> '{}'::jsonb", name="drivers_not_empty"),
        CheckConstraint("valid_to > valid_from", name="validity_ordered"),
        CheckConstraint("lead_time_hours >= 0", name="lead_time_non_negative"),
        CheckConstraint("expected_households_affected >= 0", name="households_non_negative"),
        Index("ix_impact_forecast_division", "gn_division_code", "generated_at"),
        Index("ix_impact_forecast_severe", "hazard_event_id", "impact_class"),
        {"schema": HAZARD_SCHEMA},
    )

    hazard_event_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{HAZARD_SCHEMA}.hazard_event.id", ondelete="CASCADE"),
        nullable=False,
    )
    gn_division_id: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    gn_division_code: Mapped[str] = mapped_column(String(16), nullable=False)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    impact_class: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, doc="0 none, 1 minor, 2 moderate, 3 major, 4 severe"
    )
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    lead_time_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    drivers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    expected_households_affected: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    expected_road_access_loss: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class AnticipatoryTrigger(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A pre-agreed condition and what happened when it fired.

    Anticipatory action only works if the condition is agreed before the disaster, not
    argued about during it. The condition is stored as data so it can be published and
    reviewed in the quiet years, which is when that argument should happen.
    """

    __tablename__ = "anticipatory_trigger"
    __table_args__ = (
        CheckConstraint(
            "action_taken IS NULL OR " + in_list("action_taken", TRIGGER_ACTIONS),
            name="action_taken_known",
        ),
        CheckConstraint("jsonb_typeof(condition) = 'object'", name="condition_is_object"),
        CheckConstraint("condition <> '{}'::jsonb", name="condition_not_empty"),
        # A fired trigger has to say what it did, even if the answer is NO_ACTION.
        CheckConstraint(
            "(fired_at IS NULL AND action_taken IS NULL)"
            " OR (fired_at IS NOT NULL AND action_taken IS NOT NULL)",
            name="fired_trigger_records_its_action",
        ),
        Index("ix_anticipatory_trigger_event", "hazard_event_id", "fired_at"),
        {"schema": HAZARD_SCHEMA},
    )

    hazard_event_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{HAZARD_SCHEMA}.hazard_event.id", ondelete="CASCADE"),
        nullable=False,
    )
    gn_division_id: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    gn_division_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    condition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    action_taken: Mapped[str | None] = mapped_column(String(32), nullable=True)
    forecast_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{HAZARD_SCHEMA}.impact_forecast.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
