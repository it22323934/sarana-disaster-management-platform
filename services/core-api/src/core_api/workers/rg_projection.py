"""Folds observations into `rg_entity.attributes`.

This is the only thing that writes an entity's attributes. Agents append observations and
this decides what the graph believes, using the merge policy table - which means the
answer to "why does the graph say this village is cut off" is always a list of
observations and one named policy, not a guess about which write landed last.

The projection is a pure fold over observations ordered by observation time, so re-running
it over the same range produces the same attributes. That idempotence is what makes it
safe to replay after a bad deploy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core_api.domain.resilience_graph import queries as rg
from core_api.domain.resilience_graph.merge import Observed, UnknownAttribute, merge

_log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """What one projection pass did to one entity."""

    entity_id: UUID
    attributes: dict[str, Any]
    observations_folded: int
    skipped: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.skipped


def fold(observations: list[dict[str, Any]]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Reduce observations to an attribute bag, and name what was skipped.

    Unregistered attributes are skipped rather than dropped silently or allowed to abort
    the whole fold. One agent emitting an unknown attribute must not stop the projection
    of everything else known about a division during an incident - but it must be visible,
    so the names come back with the result and are logged.
    """
    attributes: dict[str, Observed] = {}
    skipped: list[str] = []

    for observation in observations:
        name = observation["observation_type"]
        candidate = Observed(
            value=observation["value"],
            confidence=float(observation["confidence"]),
            observed_at=observation["observed_at"].timestamp(),
        )
        try:
            attributes[name] = merge(name, attributes.get(name), candidate)
        except UnknownAttribute:
            if name not in skipped:
                skipped.append(name)
        except ValueError as error:
            # A type mismatch - a max policy handed a string, say. Same reasoning: skip
            # the attribute, keep the rest, and make the reason visible.
            if name not in skipped:
                skipped.append(name)
            _log.warning("observation_unmergeable", attribute=name, error=str(error))

    return {name: observed.value for name, observed in attributes.items()}, tuple(skipped)


async def project_entity(session: AsyncSession, entity_id: UUID) -> ProjectionResult:
    """Recompute one entity's attributes from its observations."""
    observations = await rg.observations_for(session, entity_id)
    attributes, skipped = fold(observations)

    entity = await rg.get_entity(session, entity_id)
    if entity is None:
        raise LookupError(f"no entity {entity_id}")

    await rg.upsert_entity(
        session,
        entity_type=entity["entity_type"],
        natural_key=entity["natural_key"],
        attributes=json.dumps(attributes),
    )

    if skipped:
        _log.warning(
            "projection_skipped_attributes",
            entity_id=str(entity_id),
            entity_type=entity["entity_type"],
            skipped=list(skipped),
        )

    _log.info(
        "entity_projected",
        entity_id=str(entity_id),
        entity_type=entity["entity_type"],
        observations=len(observations),
        attributes=len(attributes),
    )

    return ProjectionResult(
        entity_id=entity_id,
        attributes=attributes,
        observations_folded=len(observations),
        skipped=skipped,
    )


async def project_all(
    session_factory: async_sessionmaker[AsyncSession], entity_ids: list[UUID]
) -> list[ProjectionResult]:
    """Project several entities, one transaction each.

    One transaction per entity rather than one for the batch: a single unprojectable
    entity must not roll back the fifty that projected cleanly before it.
    """
    results: list[ProjectionResult] = []
    for entity_id in entity_ids:
        async with session_factory() as session:
            try:
                results.append(await project_entity(session, entity_id))
                await session.commit()
            except Exception:
                await session.rollback()
                _log.exception("projection_failed", entity_id=str(entity_id))
                raise
    return results
