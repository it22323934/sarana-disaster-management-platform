"""The Resilience Graph surface.

The rule under test throughout is that agents append and never overwrite. An agent that
could write an entity attribute directly would make "why does the graph believe this"
unanswerable, which is the failure the observation/projection split exists to prevent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from sarana_shared.domain.ids import uuid7

pytestmark = pytest.mark.asyncio(loop_scope="session")

GN_KEY = "LK-11-03-045"


def an_observation(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "entity_type": "gn_division",
        "natural_key": f"LK-11-03-{uuid7().int % 1000:03d}",
        "observation_type": "displaced_count",
        "value": 40,
        "confidence": 0.9,
    }
    body.update(overrides)
    return body


# --------------------------------------------------------------------------------------
# Appending observations
# --------------------------------------------------------------------------------------


async def test_an_observation_is_appended_and_names_its_merge_policy(
    client: AsyncClient, agent_header: dict[str, str]
) -> None:
    """The policy comes back so the agent knows how its value will be reconciled."""
    response = await client.post(
        "/api/v1/rg/observations", headers=agent_header, json=an_observation()
    )

    assert response.status_code == 201
    body = response.json()
    assert body["merge_policy"] == "max", "displaced_count is a MAX attribute"
    assert body["id"]


async def test_a_first_sighting_creates_the_entity(
    client: AsyncClient, agent_header: dict[str, str], operator_header: dict[str, str]
) -> None:
    """The graph learns about entities from observations, so an unknown key is not an error."""
    key = f"LK-11-03-{uuid7().int % 1000:03d}"

    appended = await client.post(
        "/api/v1/rg/observations",
        headers=agent_header,
        json=an_observation(natural_key=key),
    )
    assert appended.status_code == 201

    entity = await client.get(f"/api/v1/rg/entities/gn_division/{key}", headers=operator_header)
    assert entity.status_code == 200
    assert entity.json()["natural_key"] == key


async def test_an_attribute_with_no_merge_policy_is_refused_at_the_edge(
    client: AsyncClient, agent_header: dict[str, str]
) -> None:
    """Accepting it now and failing in a background worker would fail where nobody looks."""
    response = await client.post(
        "/api/v1/rg/observations",
        headers=agent_header,
        json=an_observation(observation_type="nobody_registered_this"),
    )

    assert response.status_code == 422
    assert "no merge policy registered" in response.text


async def test_an_unknown_entity_type_is_refused(
    client: AsyncClient, agent_header: dict[str, str]
) -> None:
    """Adding a node type is a migration, deliberately."""
    response = await client.post(
        "/api/v1/rg/observations",
        headers=agent_header,
        json=an_observation(entity_type="submarine"),
    )

    assert response.status_code == 422


async def test_confidence_outside_zero_to_one_is_refused(
    client: AsyncClient, agent_header: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/rg/observations",
        headers=agent_header,
        json=an_observation(confidence=1.5),
    )

    assert response.status_code == 422


async def test_appending_requires_the_resilience_write_scope(
    client: AsyncClient, citizen_header: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/rg/observations", headers=citizen_header, json=an_observation()
    )

    assert response.status_code == 403


async def test_appending_is_refused_anonymously(client: AsyncClient) -> None:
    response = await client.post("/api/v1/rg/observations", json=an_observation())

    assert response.status_code == 401


async def test_an_unknown_field_on_an_observation_is_refused(
    client: AsyncClient, agent_header: dict[str, str]
) -> None:
    """extra="forbid": a misspelled field must not be silently discarded."""
    response = await client.post(
        "/api/v1/rg/observations",
        headers=agent_header,
        json=an_observation(confidance=0.5),
    )

    assert response.status_code == 422


# --------------------------------------------------------------------------------------
# Entities and relations
# --------------------------------------------------------------------------------------


async def test_an_unknown_entity_is_a_404(
    client: AsyncClient, operator_header: dict[str, str]
) -> None:
    response = await client.get(
        "/api/v1/rg/entities/gn_division/LK-99-99-999", headers=operator_header
    )

    assert response.status_code == 404


async def test_the_relations_route_is_not_shadowed_by_the_entity_route(
    client: AsyncClient, operator_header: dict[str, str]
) -> None:
    """`/entities/{id}/relations` must not be read as `/entities/{type}/{natural_key}`.

    Declaration order is what keeps these apart, so it is worth a test: the wrong match
    would turn a relations query into a 422 about an unknown entity type.
    """
    response = await client.get(f"/api/v1/rg/entities/{uuid7()}/relations", headers=operator_header)

    # A well-formed id for an entity that does not exist: 404, never 422.
    assert response.status_code == 404
    assert "No such entity" in response.text


async def test_an_unknown_relation_type_is_refused(
    client: AsyncClient, operator_header: dict[str, str]
) -> None:
    response = await client.get(
        f"/api/v1/rg/entities/{uuid7()}/relations",
        headers=operator_header,
        params={"type": "orbits"},
    )

    assert response.status_code == 422


async def test_relations_accept_a_point_in_time(
    client: AsyncClient, operator_header: dict[str, str]
) -> None:
    """Bitemporal: `at` asks what held in the world then, not what we knew then."""
    yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()

    response = await client.get(
        f"/api/v1/rg/entities/{uuid7()}/relations",
        headers=operator_header,
        params={"at": yesterday},
    )

    assert response.status_code == 404, "the entity does not exist, but `at` parsed"


# --------------------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------------------


async def test_search_says_which_strategy_it_used(
    client: AsyncClient, operator_header: dict[str, str]
) -> None:
    """A caller expecting semantic similarity must not silently get a substring match."""
    response = await client.get("/api/v1/rg/search", headers=operator_header, params={"q": "LK-11"})

    assert response.status_code == 200
    assert response.json()["strategy"] == "natural_key"


async def test_a_malformed_embedding_is_refused(
    client: AsyncClient, operator_header: dict[str, str]
) -> None:
    response = await client.get(
        "/api/v1/rg/search", headers=operator_header, params={"embedding": "not,a,vector"}
    )

    assert response.status_code == 422


async def test_an_embedding_of_the_wrong_width_is_refused(
    client: AsyncClient, operator_header: dict[str, str]
) -> None:
    """A short vector would be a silent mismatch against a 1024-dimension index."""
    response = await client.get(
        "/api/v1/rg/search",
        headers=operator_header,
        params={"embedding": "0.1,0.2,0.3"},
    )

    assert response.status_code == 422
    assert "dimensions" in response.text


async def test_a_malformed_attribute_filter_is_refused(
    client: AsyncClient, operator_header: dict[str, str]
) -> None:
    response = await client.get(
        "/api/v1/rg/search", headers=operator_header, params={"attributes": "not json"}
    )

    assert response.status_code == 422


async def test_search_requires_the_resilience_read_scope(
    client: AsyncClient, citizen_header: dict[str, str]
) -> None:
    response = await client.get("/api/v1/rg/search", headers=citizen_header)

    assert response.status_code == 403


# --------------------------------------------------------------------------------------
# The projection-only write path
# --------------------------------------------------------------------------------------


async def test_the_upsert_endpoint_is_refused_to_an_agent(
    client: AsyncClient, agent_header: dict[str, str]
) -> None:
    """Agents append observations. Writing an entity directly is the projection's job.

    An agent holds resilience:write, which is enough to observe and deliberately not
    enough to overwrite - that separation is what keeps the graph explainable.
    """
    response = await client.post(
        "/api/v1/rg/entities:upsert",
        headers=agent_header,
        json={"entity_type": "gn_division", "natural_key": GN_KEY, "attributes": {}},
    )

    assert response.status_code == 403


async def test_a_human_operator_cannot_append_an_observation(
    client: AsyncClient, operator_header: dict[str, str]
) -> None:
    """Humans read the graph; agents are what put things in it.

    RESILIENCE_WRITE is held by AGENT and SERVICE and by no human role, so an operator
    reading the common operating picture cannot quietly become a source in it.
    """
    response = await client.post(
        "/api/v1/rg/observations", headers=operator_header, json=an_observation()
    )

    assert response.status_code == 403


async def test_the_projection_can_upsert_an_entity(
    client: AsyncClient, admin_header: dict[str, str]
) -> None:
    key = f"LK-11-03-{uuid7().int % 1000:03d}"

    response = await client.post(
        "/api/v1/rg/entities:upsert",
        headers=admin_header,
        json={
            "entity_type": "gn_division",
            "natural_key": key,
            "attributes": {"displaced_count": 12},
        },
    )

    assert response.status_code == 200
    assert response.json()["attributes"]["displaced_count"] == 12
