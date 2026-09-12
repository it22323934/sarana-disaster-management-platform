"""Reads and appends over the Resilience Graph.

Agents get exactly one write path here: appending an observation. Entities are only
changed by the projection worker, which folds observations in under the documented merge
policy. Keeping those separate is what makes "why does the graph believe this" a question
with an answer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from sarana_shared.domain.ids import uuid7

_ENTITY_BY_KEY_SQL = """
SELECT id::text, entity_type, natural_key, attributes, created_at, updated_at
FROM resilience.rg_entity
WHERE entity_type = :entity_type AND natural_key = :natural_key
"""

_ENTITY_BY_ID_SQL = """
SELECT id::text, entity_type, natural_key, attributes, created_at, updated_at
FROM resilience.rg_entity
WHERE id = :entity_id
"""

# Bitemporal: `at` selects the edges that held in the world at that instant, which is not
# the same as the edges we knew about then. A household sheltering between T+2d and T+9d
# is a closed edge at T+30d, not a deleted one.
_RELATIONS_SQL = """
SELECT r.id::text, r.from_entity_id::text, r.to_entity_id::text, r.relation_type,
       r.attributes, r.valid_from, r.valid_to, r.confidence,
       e.entity_type AS other_entity_type, e.natural_key AS other_natural_key
FROM resilience.rg_relation r
JOIN resilience.rg_entity e
  ON e.id = CASE WHEN r.from_entity_id = :entity_id THEN r.to_entity_id
                 ELSE r.from_entity_id END
WHERE (r.from_entity_id = :entity_id OR r.to_entity_id = :entity_id)
  AND (CAST(:relation_type AS text) IS NULL
       OR r.relation_type = CAST(:relation_type AS text))
  AND r.valid_from <= CAST(:at AS timestamptz)
  AND (r.valid_to IS NULL OR r.valid_to > CAST(:at AS timestamptz))
ORDER BY r.valid_from DESC
LIMIT :limit
"""

_INSERT_OBSERVATION_SQL = """
INSERT INTO resilience.rg_observation (
    id, entity_id, observed_at, source_agent, source_event_id,
    correlation_id, observation_type, value, confidence
) VALUES (
    :id, :entity_id, CAST(:observed_at AS timestamptz), :source_agent, :source_event_id,
    :correlation_id, :observation_type, CAST(:value AS jsonb), :confidence
)
RETURNING id::text, entity_id::text, observed_at, observation_type, confidence
"""

_UPSERT_ENTITY_SQL = """
INSERT INTO resilience.rg_entity (id, entity_type, natural_key, attributes)
VALUES (:id, :entity_type, :natural_key, CAST(:attributes AS jsonb))
ON CONFLICT (entity_type, natural_key) DO UPDATE
    SET attributes = resilience.rg_entity.attributes || EXCLUDED.attributes,
        updated_at = now()
RETURNING id::text, entity_type, natural_key, attributes
"""

# Vector similarity when the caller supplies an embedding. `<=>` is pgvector's cosine
# distance, so smaller is closer and the ivfflat index is used.
_SEARCH_VECTOR_SQL = """
SELECT id::text, entity_type, natural_key, attributes,
       (embedding <=> CAST(:embedding AS vector)) AS distance
FROM resilience.rg_entity
WHERE embedding IS NOT NULL
  AND (CAST(:entity_type AS text) IS NULL OR entity_type = CAST(:entity_type AS text))
  AND (CAST(:attribute_filter AS jsonb) IS NULL
       OR attributes @> CAST(:attribute_filter AS jsonb))
ORDER BY embedding <=> CAST(:embedding AS vector)
LIMIT :k
"""

# Without an embedding there is still a useful answer: match the natural key. Text search
# is not a stand-in for semantic similarity, and the response says which one it used so a
# caller is never misled about what it got.
_SEARCH_TEXT_SQL = """
SELECT id::text, entity_type, natural_key, attributes, NULL::float AS distance
FROM resilience.rg_entity
WHERE (CAST(:entity_type AS text) IS NULL OR entity_type = CAST(:entity_type AS text))
  AND (CAST(:q AS text) IS NULL OR natural_key ILIKE :like)
  AND (CAST(:attribute_filter AS jsonb) IS NULL
       OR attributes @> CAST(:attribute_filter AS jsonb))
ORDER BY natural_key
LIMIT :k
"""


async def get_entity_by_key(
    session: AsyncSession, *, entity_type: str, natural_key: str
) -> dict[str, Any] | None:
    """One entity by its identifier in the owning system."""
    result = await session.execute(
        text(_ENTITY_BY_KEY_SQL),
        {"entity_type": entity_type, "natural_key": natural_key},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def get_entity(session: AsyncSession, entity_id: UUID) -> dict[str, Any] | None:
    """One entity by id."""
    result = await session.execute(text(_ENTITY_BY_ID_SQL), {"entity_id": entity_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def get_relations(
    session: AsyncSession,
    entity_id: UUID,
    *,
    relation_type: str | None = None,
    at: datetime,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Edges touching an entity that held at a given instant."""
    result = await session.execute(
        text(_RELATIONS_SQL),
        {
            "entity_id": entity_id,
            "relation_type": relation_type,
            "at": at,
            "limit": limit,
        },
    )
    return [dict(row) for row in result.mappings()]


async def append_observation(
    session: AsyncSession,
    *,
    entity_id: UUID,
    observed_at: datetime,
    source_agent: str,
    correlation_id: str,
    observation_type: str,
    value: str,
    confidence: float,
    source_event_id: UUID | None = None,
) -> dict[str, Any]:
    """Append one observation. Never updates, never overwrites."""
    result = await session.execute(
        text(_INSERT_OBSERVATION_SQL),
        {
            "id": uuid7(),
            "entity_id": entity_id,
            "observed_at": observed_at,
            "source_agent": source_agent,
            "source_event_id": source_event_id,
            "correlation_id": correlation_id,
            "observation_type": observation_type,
            "value": value,
            "confidence": confidence,
        },
    )
    return dict(result.mappings().one())


async def upsert_entity(
    session: AsyncSession, *, entity_type: str, natural_key: str, attributes: str
) -> dict[str, Any]:
    """Create or shallow-merge an entity. Projection worker only."""
    result = await session.execute(
        text(_UPSERT_ENTITY_SQL),
        {
            "id": uuid7(),
            "entity_type": entity_type,
            "natural_key": natural_key,
            "attributes": attributes,
        },
    )
    return dict(result.mappings().one())


async def search_entities(
    session: AsyncSession,
    *,
    q: str | None = None,
    entity_type: str | None = None,
    embedding: str | None = None,
    attribute_filter: str | None = None,
    k: int = 20,
) -> tuple[list[dict[str, Any]], str]:
    """Search the graph, returning the rows and which strategy produced them.

    The strategy is returned rather than hidden because the two are not interchangeable:
    a caller that asked for semantic similarity and silently got a substring match would
    draw the wrong conclusion from an empty or odd result set.
    """
    if embedding is not None:
        result = await session.execute(
            text(_SEARCH_VECTOR_SQL),
            {
                "embedding": embedding,
                "entity_type": entity_type,
                "attribute_filter": attribute_filter,
                "k": k,
            },
        )
        return [dict(row) for row in result.mappings()], "vector"

    result = await session.execute(
        text(_SEARCH_TEXT_SQL),
        {
            "q": q,
            "like": f"%{q}%" if q else None,
            "entity_type": entity_type,
            "attribute_filter": attribute_filter,
            "k": k,
        },
    )
    return [dict(row) for row in result.mappings()], "natural_key"


async def observations_for(
    session: AsyncSession, entity_id: UUID, *, attribute: str | None = None, limit: int = 500
) -> list[dict[str, Any]]:
    """Raw observations for an entity, oldest first.

    Oldest first because that is the order the projection folds them in, and a merge
    policy that depends on order must be replayed in the same order it originally ran.
    """
    result = await session.execute(
        text(
            "SELECT id::text, entity_id::text, observed_at, source_agent, "
            "       observation_type, value, confidence, correlation_id "
            "FROM resilience.rg_observation "
            "WHERE entity_id = :entity_id "
            "  AND (CAST(:attribute AS text) IS NULL "
            "       OR observation_type = CAST(:attribute AS text)) "
            "ORDER BY observed_at, id "
            "LIMIT :limit"
        ),
        {"entity_id": entity_id, "attribute": attribute, "limit": limit},
    )
    return [dict(row) for row in result.mappings()]
