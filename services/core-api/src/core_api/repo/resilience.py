"""The `resilience` schema: the Resilience Graph (ADR-012).

Named in every diagram of the proposal and never defined. Here it is a concrete
entity-and-relationship store in PostgreSQL, not a graph database:

    rg_entity      typed nodes with a JSONB attribute bag and a pgvector embedding
    rg_relation    typed directed edges, bitemporal via valid_from / valid_to
    rg_observation append-only facts, each carrying its source agent and confidence

Agents never update an entity directly. They append an observation, and a projection job
folds it into `rg_entity.attributes`. That is what makes "feeds the next Anticipate
cycle" a testable claim rather than a slide.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core_api.repo.base import EMBEDDING_DIMENSIONS, RESILIENCE_SCHEMA
from sarana_shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from sarana_shared.db.constraints import in_list

# The node types the graph carries. Adding one is a migration, deliberately: an
# unconstrained type column turns the graph back into an undocumented JSON blob.
ENTITY_TYPES = (
    "gn_division",
    "household",
    "hazard_event",
    "incident",
    "asset",
    "responder",
    "shelter",
)

RELATION_TYPES = (
    "located_in",
    "affected_by",
    "reported_by",
    "assigned_to",
    "shelters_at",
    "depends_on",
    "adjacent_to",
    "supersedes",
)


class RGEntity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A typed node.

    `natural_key` is the identifier in the owning system - a GN code, an incident public
    reference - so an agent can resolve an entity without carrying UUIDs between
    services.
    """

    __tablename__ = "rg_entity"
    __table_args__ = (
        UniqueConstraint("entity_type", "natural_key", name="uq_rg_entity_type_key"),
        CheckConstraint(in_list("entity_type", ENTITY_TYPES), name="entity_type_known"),
        Index(
            "ix_rg_entity_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_rg_entity_attributes", "attributes", postgresql_using="gin"),
        {"schema": RESILIENCE_SCHEMA},
    )

    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    natural_key: Mapped[str] = mapped_column(String(128), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)


class RGRelation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A typed directed edge, bitemporal.

    `valid_from` / `valid_to` record when the relationship held in the world, not when we
    learned it. A household sheltering somewhere between T+2d and T+9d is a closed edge,
    not a deleted one - the Learn loop needs the history.
    """

    __tablename__ = "rg_relation"
    __table_args__ = (
        CheckConstraint(in_list("relation_type", RELATION_TYPES), name="relation_type_known"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="valid_period_ordered"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_range"
        ),
        CheckConstraint("from_entity_id <> to_entity_id", name="no_self_relation"),
        Index("ix_rg_relation_from_type", "from_entity_id", "relation_type"),
        Index("ix_rg_relation_to_type", "to_entity_id", "relation_type"),
        # Traversal is almost always "edges that hold right now".
        Index(
            "ix_rg_relation_open",
            "relation_type",
            "from_entity_id",
            postgresql_where=text("valid_to IS NULL"),
        ),
        {"schema": RESILIENCE_SCHEMA},
    )

    from_entity_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{RESILIENCE_SCHEMA}.rg_entity.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_entity_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{RESILIENCE_SCHEMA}.rg_entity.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)


class RGObservation(UUIDPrimaryKeyMixin, Base):
    """An append-only fact about an entity.

    Every observation names the agent that produced it, its confidence, and the event it
    came from. That triple is what lets an auditor ask "why does the graph believe this"
    and get an answer that leads back into the event log.

    No `updated_at`: an observation is never revised. A later observation supersedes an
    earlier one, and the projection job decides which wins.
    """

    __tablename__ = "rg_observation"
    __table_args__ = (
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        Index("ix_rg_observation_entity_time", "entity_id", "observed_at"),
        Index("ix_rg_observation_correlation", "correlation_id"),
        {"schema": RESILIENCE_SCHEMA},
    )

    entity_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{RESILIENCE_SCHEMA}.rg_entity.id", ondelete="CASCADE"),
        nullable=False,
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_event_id: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
