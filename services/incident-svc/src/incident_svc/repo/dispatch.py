"""Dispatch planning and responders.

`dispatch_plan` carries the first of the two mandatory human gates: committing a
life-safety dispatch action. An agent proposes the plan, computes the route and ranks
the queue; a human commits it. There is no bypass flag, no demo mode that skips it, and
the rule is enforced by a database trigger as well as by the application - see the
migration. Application code is the first line; the trigger is the one that still holds
when the application is wrong.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from incident_svc.repo.base import DISPATCH_STATUSES, INCIDENT_SCHEMA
from sarana_shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from sarana_shared.db.constraints import in_list
from sarana_shared.domain.geo import SRID_WGS84

RESPONDER_TYPES: tuple[str, ...] = (
    "AMBULANCE",
    "FIRE",
    "POLICE",
    "MILITARY",
    "NAVY",
    "COAST_GUARD",
    "VOLUNTEER",
    "NGO",
    "MEDICAL_TEAM",
    "ENGINEERING",
)

RESPONDER_STATUSES: tuple[str, ...] = ("AVAILABLE", "ASSIGNED", "EN_ROUTE", "ON_SCENE", "OFFLINE")


class Responder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A team or vehicle that can be sent somewhere."""

    __tablename__ = "responder"
    __table_args__ = (
        CheckConstraint(in_list("type", RESPONDER_TYPES), name="type_known"),
        CheckConstraint(in_list("status", RESPONDER_STATUSES), name="status_known"),
        CheckConstraint("capacity >= 0", name="capacity_non_negative"),
        Index("ix_responder_current_location", "current_location", postgresql_using="gist"),
        {"schema": INCIDENT_SCHEMA},
    )

    org: Mapped[str] = mapped_column(String(96), nullable=False)
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    home_gn_division_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    current_location: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=SRID_WGS84, spatial_index=False), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="AVAILABLE", index=True
    )


class DispatchPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A proposed allocation of responders to incidents. HUMAN GATE.

    The plan is produced autonomously - scoring, routing, sequencing. What a human does
    is commit it. `signed_off_by` and `signed_off_at` are the record of that decision,
    and a trigger refuses any transition to RELEASED without them.

    `langgraph_thread_id` is how the paused agent run is resumed once the decision is
    made: the thread sits at an `interrupt()` holding no process and no cost, and
    `Command(resume=...)` picks it up on the same thread (ADR-004).
    """

    __tablename__ = "dispatch_plan"
    __table_args__ = (
        CheckConstraint(in_list("status", DISPATCH_STATUSES), name="status_known"),
        # The gate, stated declaratively as well as in the trigger. A CHECK cannot see
        # the previous row version, so the trigger does the transition rule; this covers
        # the resting state.
        CheckConstraint(
            "status NOT IN ('RELEASED','COMPLETED')"
            " OR (signed_off_by IS NOT NULL AND signed_off_at IS NOT NULL)",
            name="released_requires_signoff",
        ),
        CheckConstraint(
            "status <> 'REJECTED' OR rejection_reason IS NOT NULL",
            name="rejection_has_a_reason",
        ),
        CheckConstraint("cardinality(incident_ids) > 0", name="plan_covers_an_incident"),
        CheckConstraint(
            "estimated_duration_min IS NULL OR estimated_duration_min > 0",
            name="duration_positive",
        ),
        Index("ix_dispatch_plan_status", "status"),
        Index("ix_dispatch_plan_thread", "langgraph_thread_id"),
        {"schema": INCIDENT_SCHEMA},
    )

    incident_ids: Mapped[list[Any]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), nullable=False)
    responder_ids: Mapped[list[Any]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, server_default="{}"
    )
    route: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    estimated_duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)

    proposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    proposed_by_agent: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PROPOSED")
    signed_off_by: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    signed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    langgraph_thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
