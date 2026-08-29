"""Every mock response admits to being one.

This is the property the whole service rests on. `sarana_shared.adapters.gov` refuses a
response without both markers, so a route that forgets them does not serve unmarked data —
it breaks. The point of the test is to catch that at build time rather than at the first
client call.

The test walks the OpenAPI schema rather than a hand-written list of routes, so a route
added tomorrow is covered without anybody remembering to add it here.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from sarana_shared.adapters.gov.base import (
    MOCK_HEADER,
    MOCK_HEADER_VALUE,
    MOCK_SOURCE_FIELD,
    MOCK_SOURCE_VALUE,
)

# A representative value for each path parameter, chosen so the route resolves rather than
# 404s. A 404 would still carry the right shape but would not exercise the handler.
PATH_VALUES: dict[str, str] = {
    "warning_id": "MET-20251127-YELLOW-001",
    "location_id": "DMC-51-001",
    "version": "2025.11",
    "claim_reference": "unknown",
    "service_no": "GN51010011",
    "household_ref": "HH-5101001-0001",
    "transfer_ref": "unknown",
    "message_id": "unknown",
}

# Query parameters routes need to get past validation.
QUERY_VALUES: dict[str, dict[str, Any]] = {
    "/met/v1/forecast/rainfall": {"district": "LK-51", "hours": 24},
    "/nbro/v1/zonation": {"gn_division_id": "LK-51-01-001"},
    "/gnreg/v1/officers": {"gn_division_id": "LK-51-01-001"},
    "/hhreg/v1/households": {"gn_division_id": "LK-51-01-001"},
    "/telco/v1/coverage": {"gn_division_id": "LK-51-01-001"},
}


def _get_paths(client: AsyncClient) -> list[str]:
    app = client._transport.app  # type: ignore[attr-defined, union-attr]
    spec: dict[str, Any] = app.openapi()
    return sorted(path for path, ops in spec["paths"].items() if "get" in ops)


async def test_every_get_route_carries_the_mock_header(client: AsyncClient) -> None:
    """No route may answer without `X-Sarana-Mock: true`.

    If one does, a client pointed by accident at a real agency endpoint would work, and
    nobody would find out until real warnings appeared in a demo — or a demo's synthetic
    rainfall reached something that mattered.
    """
    paths = _get_paths(client)
    assert paths, "no GET routes found; the schema walk is not doing anything"

    for path in paths:
        url = path
        for name, value in PATH_VALUES.items():
            url = url.replace(f"{{{name}}}", value)

        response = await client.get(url, params=QUERY_VALUES.get(path, {}))
        assert response.headers.get(MOCK_HEADER) == MOCK_HEADER_VALUE, (
            f"{path} answered {response.status_code} without {MOCK_HEADER}"
        )


async def test_every_json_route_carries_the_source_field(client: AsyncClient) -> None:
    """Every JSON body carries a top-level `"source": "MOCK"`."""
    for path in _get_paths(client):
        url = path
        for name, value in PATH_VALUES.items():
            url = url.replace(f"{{{name}}}", value)

        response = await client.get(url, params=QUERY_VALUES.get(path, {}))
        if not response.headers["content-type"].startswith("application/json"):
            continue

        body = response.json()
        assert body.get(MOCK_SOURCE_FIELD) == MOCK_SOURCE_VALUE, (
            f"{path} returned JSON without {MOCK_SOURCE_FIELD}={MOCK_SOURCE_VALUE!r}"
        )


async def test_the_xml_feed_marks_its_root_element(client: AsyncClient) -> None:
    """XML has no envelope, so the marker goes on the root element instead."""
    response = await client.get("/met/v1/warnings")

    assert response.status_code == 200
    assert response.headers[MOCK_HEADER] == MOCK_HEADER_VALUE
    assert f'{MOCK_SOURCE_FIELD}="{MOCK_SOURCE_VALUE}"' in response.text


@pytest.mark.parametrize(
    "path",
    ["/met/v1/warnings/no-such-warning", "/ndrsc/v1/cost-schedules/1999.01"],
)
async def test_a_not_found_is_still_a_problem_document(client: AsyncClient, path: str) -> None:
    """A routing miss returns Problem Details, never a bare string.

    The mock header is deliberately not required here: the client checks the status before
    the header, so a 404 becomes `GovRecordNotFound` either way, and requiring the marker
    on an error path would mean the shared error handlers had to know about this service.
    """
    response = await client.get(path)

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 404
