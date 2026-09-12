"""The Resilience Graph surface.

Agents get one write path: appending an observation. Entities change only through the
projection worker, which folds observations in under the documented merge policy. That
separation is what turns "the graph feeds the next Anticipate cycle" into something an
auditor can trace back to the agent and event that caused it.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from core_api.api.deps import SessionDep
from core_api.domain import resilience_graph as rg
from core_api.domain.resilience_graph.merge import UnknownAttribute
from core_api.repo.base import EMBEDDING_DIMENSIONS
from core_api.repo.resilience import ENTITY_TYPES, RELATION_TYPES
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.domain.time import utc_now
from sarana_shared.errors import NotFound, ValidationFailed

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/rg", tags=["resilience-graph"])

ReadPrincipal = Depends(require(Scope.RESILIENCE_READ))
WritePrincipal = Depends(require(Scope.RESILIENCE_WRITE))
InternalPrincipal = Depends(require(Scope.SYSTEM_ADMIN))


class ObservationRequest(BaseModel):
    """One appended fact about one entity.

    The entity is named by type and natural key rather than by id, so an agent never has
    to carry a UUID between services to say something about a division it already knows
    the code of.
    """

    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(description="One of the registered graph entity types")
    natural_key: str = Field(min_length=1, max_length=128)
    observation_type: str = Field(
        min_length=1,
        max_length=64,
        description="The attribute being observed. Must have a registered merge policy.",
    )
    value: Any = Field(description="The observed value, shaped to suit the merge policy")
    confidence: float = Field(ge=0.0, le=1.0)
    observed_at: datetime | None = Field(
        default=None, description="When it held in the world. Defaults to now."
    )
    source_event_id: UUID | None = None


class ObservationResponse(BaseModel):
    """What was appended."""

    model_config = ConfigDict(frozen=True)

    id: str
    entity_id: str
    observation_type: str
    confidence: float
    observed_at: datetime
    merge_policy: str = Field(description="How this attribute will be folded in")


class EntityResponse(BaseModel):
    """A graph entity and its current projected attributes."""

    model_config = ConfigDict(frozen=True)

    id: str
    entity_type: str
    natural_key: str
    attributes: dict[str, Any]


class RelationResponse(BaseModel):
    """One edge, as it held at the requested instant."""

    model_config = ConfigDict(frozen=True)

    id: str
    from_entity_id: str
    to_entity_id: str
    relation_type: str
    attributes: dict[str, Any]
    valid_from: datetime
    valid_to: datetime | None
    confidence: float | None
    other_entity_type: str
    other_natural_key: str


class UpsertRequest(BaseModel):
    """Projection-only entity write."""

    model_config = ConfigDict(extra="forbid")

    entity_type: str
    natural_key: str = Field(min_length=1, max_length=128)
    attributes: dict[str, Any] = Field(default_factory=dict)


class SearchHit(BaseModel):
    """One search result. `distance` is present only for a vector search."""

    model_config = ConfigDict(frozen=True)

    id: str
    entity_type: str
    natural_key: str
    attributes: dict[str, Any]
    distance: float | None = None


class SearchResponse(BaseModel):
    """Results, and which strategy produced them.

    The strategy is explicit because a caller that asked for semantic similarity and
    silently received a substring match would draw the wrong conclusion from the results.
    """

    model_config = ConfigDict(frozen=True)

    strategy: str
    hits: list[SearchHit]


def _validate_entity_type(entity_type: str) -> None:
    if entity_type not in ENTITY_TYPES:
        raise ValidationFailed(
            f"unknown entity type {entity_type!r}",
            context={"known": sorted(ENTITY_TYPES)},
        )


@router.post(
    "/observations",
    response_model=ObservationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def append_observation(
    body: ObservationRequest,
    request: Request,
    session: SessionDep,
    principal: Principal = WritePrincipal,
) -> Any:
    """Append one observation. The only write path an agent gets.

    The merge policy is checked here, at the edge, rather than later in the projection.
    An observation accepted now and found unmergeable by a background worker would fail
    where nobody is looking; failing the request tells the agent immediately.
    """
    _validate_entity_type(body.entity_type)

    try:
        policy = rg.policy_for(body.observation_type)
    except UnknownAttribute as error:
        raise ValidationFailed(str(error), context={"attribute": body.observation_type}) from error

    entity = await rg.get_entity_by_key(
        session, entity_type=body.entity_type, natural_key=body.natural_key
    )
    if entity is None:
        # The graph learns about entities from observations, so a first sighting creates
        # the node with no attributes; the projection fills it in.
        entity = await rg.upsert_entity(
            session,
            entity_type=body.entity_type,
            natural_key=body.natural_key,
            attributes="{}",
        )

    correlation_id = getattr(request.state, "correlation_id", None) or str(
        request.headers.get("x-correlation-id", "")
    )
    row = await rg.append_observation(
        session,
        entity_id=UUID(entity["id"]),
        observed_at=body.observed_at or utc_now(),
        source_agent=principal.subject_id,
        correlation_id=correlation_id or "unknown",
        observation_type=body.observation_type,
        value=json.dumps(body.value),
        confidence=body.confidence,
        source_event_id=body.source_event_id,
    )

    _log.info(
        "observation_appended",
        entity_type=body.entity_type,
        natural_key=body.natural_key,
        attribute=body.observation_type,
        merge_policy=policy.value,
        source_agent=principal.subject_id,
    )

    return {
        "id": row["id"],
        "entity_id": row["entity_id"],
        "observation_type": row["observation_type"],
        "confidence": float(row["confidence"]),
        "observed_at": row["observed_at"],
        "merge_policy": policy.value,
    }


# Declared before `/entities/{entity_type}/{natural_key}`: that route would otherwise
# match this path, reading the id as a type and "relations" as a natural key.
@router.get("/entities/{entity_id}/relations", response_model=list[RelationResponse])
async def get_relations(
    entity_id: UUID,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    type: str | None = Query(default=None, description="Filter to one relation type"),
    at: datetime | None = Query(
        default=None, description="The instant to ask about. Defaults to now."
    ),
    limit: int = Query(default=200, ge=1, le=1000),
) -> Any:
    """Edges touching an entity that held at a given instant.

    Bitemporal: `at` selects when the relationship held in the world, not when the
    platform learned about it. A household that sheltered somewhere for a week is a closed
    edge afterwards, not a deleted one, because the Learn loop needs that history.
    """
    if type is not None and type not in RELATION_TYPES:
        raise ValidationFailed(
            f"unknown relation type {type!r}", context={"known": sorted(RELATION_TYPES)}
        )

    entity = await rg.get_entity(session, entity_id)
    if entity is None:
        raise NotFound("No such entity.", context={"entity_id": str(entity_id)})

    return await rg.get_relations(
        session, entity_id, relation_type=type, at=at or utc_now(), limit=limit
    )


@router.get("/search", response_model=SearchResponse)
async def search(
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    q: str | None = Query(default=None, max_length=200),
    type: str | None = Query(default=None),
    k: int = Query(default=20, ge=1, le=100),
    embedding: str | None = Query(
        default=None,
        description=(
            "A query vector as comma-separated floats. When absent the search falls back "
            "to matching the natural key."
        ),
    ),
    attributes: str | None = Query(
        default=None, description="JSON object the attributes must contain"
    ),
) -> Any:
    """Similarity search over the graph.

    Accepts a caller-supplied embedding rather than computing one: the embedding model
    lives with the agent runtime, and core-api holding a second copy would guarantee the
    two eventually disagree about what a vector means.
    """
    if type is not None:
        _validate_entity_type(type)

    vector = _parse_embedding(embedding)
    attribute_filter = _parse_attribute_filter(attributes)

    hits, strategy = await rg.search_entities(
        session,
        q=q,
        entity_type=type,
        embedding=vector,
        attribute_filter=attribute_filter,
        k=k,
    )
    return {"strategy": strategy, "hits": hits}


def _parse_embedding(raw: str | None) -> str | None:
    """Validate a comma-separated vector and render it for pgvector."""
    if raw is None:
        return None
    try:
        values = [float(part) for part in raw.split(",")]
    except ValueError as error:
        raise ValidationFailed(
            "embedding must be comma-separated numbers", context={"received": raw[:80]}
        ) from error

    if len(values) != EMBEDDING_DIMENSIONS:
        raise ValidationFailed(
            f"embedding must have {EMBEDDING_DIMENSIONS} dimensions, got {len(values)}",
            context={"expected": EMBEDDING_DIMENSIONS, "received": len(values)},
        )
    return "[" + ",".join(str(value) for value in values) + "]"


def _parse_attribute_filter(raw: str | None) -> str | None:
    """Validate a JSON containment filter."""
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValidationFailed(
            "attributes must be a JSON object", context={"received": raw[:80]}
        ) from error
    if not isinstance(parsed, dict):
        raise ValidationFailed("attributes must be a JSON object")
    return json.dumps(parsed)


@router.post("/entities:upsert", response_model=EntityResponse)
async def upsert_entity(
    body: UpsertRequest,
    session: SessionDep,
    principal: Principal = InternalPrincipal,
) -> Any:
    """Create or merge an entity. The projection job's endpoint, not an agent's."""
    _validate_entity_type(body.entity_type)
    return await rg.upsert_entity(
        session,
        entity_type=body.entity_type,
        natural_key=body.natural_key,
        attributes=json.dumps(body.attributes),
    )


@router.get("/entities/{entity_type}/{natural_key}", response_model=EntityResponse)
async def get_entity(
    entity_type: str,
    natural_key: str,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
) -> Any:
    """One entity by its identifier in the owning system."""
    _validate_entity_type(entity_type)
    row = await rg.get_entity_by_key(session, entity_type=entity_type, natural_key=natural_key)
    if row is None:
        raise NotFound(
            "No such entity.",
            context={"entity_type": entity_type, "natural_key": natural_key},
        )
    return row
