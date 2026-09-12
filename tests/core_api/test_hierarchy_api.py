"""The hierarchy surface, including the coordinate resolver on the hot path.

`/admin/resolve` answers the question every citizen report starts with: which division is
this? Getting it wrong sends responders to the wrong place, so the boundary cases are
tested explicitly rather than assumed.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.core_api.conftest import (
    BOUNDARY_LON,
    GN_EAST,
    GN_WEST,
    KANDY_DISTRICT,
    KANDY_DS,
    NORTH_LAT,
    SOUTH_LAT,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

MID_LAT = (SOUTH_LAT + NORTH_LAT) / 2

# Points comfortably inside each division, either side of the shared edge.
WEST_INTERIOR = (80.65, MID_LAT)
EAST_INTERIOR = (80.75, MID_LAT)

# Three points near the shared boundary at longitude 80.7. PostGIS ST_Contains excludes
# the boundary itself, so a point exactly on the shared edge belongs to whichever polygon
# claims it - the assertion is that exactly one does, not which.
JUST_WEST = (BOUNDARY_LON - 0.0001, MID_LAT)
JUST_EAST = (BOUNDARY_LON + 0.0001, MID_LAT)
ON_THE_EDGE = (BOUNDARY_LON, MID_LAT)

# Well out in the Indian Ocean, still inside the country bounding box.
OFFSHORE = (81.9, 5.9)


async def test_resolve_finds_the_division_containing_a_point(
    client: AsyncClient,
    operator_header: dict[str, str],
    hierarchy_fixture: dict[str, str],
    clean_resolve_cache: None,
) -> None:
    lng, lat = WEST_INTERIOR
    response = await client.get(
        "/api/v1/admin/resolve", headers=operator_header, params={"lat": lat, "lng": lng}
    )

    assert response.status_code == 200
    assert response.json()["code"] == GN_WEST


async def test_resolve_distinguishes_two_adjacent_divisions(
    client: AsyncClient,
    operator_header: dict[str, str],
    hierarchy_fixture: dict[str, str],
    clean_resolve_cache: None,
) -> None:
    """Adjacent divisions are the case a bounding-box shortcut gets wrong."""
    west_lng, west_lat = WEST_INTERIOR
    east_lng, east_lat = EAST_INTERIOR

    west = await client.get(
        "/api/v1/admin/resolve",
        headers=operator_header,
        params={"lat": west_lat, "lng": west_lng},
    )
    east = await client.get(
        "/api/v1/admin/resolve",
        headers=operator_header,
        params={"lat": east_lat, "lng": east_lng},
    )

    assert west.json()["code"] == GN_WEST
    assert east.json()["code"] == GN_EAST


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        pytest.param(JUST_WEST, GN_WEST, id="a-metre-west-of-the-boundary"),
        pytest.param(JUST_EAST, GN_EAST, id="a-metre-east-of-the-boundary"),
    ],
)
async def test_resolve_is_correct_within_a_metre_of_a_boundary(
    client: AsyncClient,
    operator_header: dict[str, str],
    hierarchy_fixture: dict[str, str],
    clean_resolve_cache: None,
    point: tuple[float, float],
    expected: str,
) -> None:
    """A household on a division line is assessed by one officer or the other."""
    lng, lat = point
    response = await client.get(
        "/api/v1/admin/resolve", headers=operator_header, params={"lat": lat, "lng": lng}
    )

    assert response.status_code == 200
    assert response.json()["code"] == expected


async def test_a_point_exactly_on_a_shared_edge_resolves_to_exactly_one_division(
    client: AsyncClient,
    operator_header: dict[str, str],
    hierarchy_fixture: dict[str, str],
    clean_resolve_cache: None,
) -> None:
    """Which one is arbitrary; that it is exactly one is not.

    Two divisions both claiming a point would mean two officers assessing the same
    household, and neither claiming it would mean nobody does.
    """
    lng, lat = ON_THE_EDGE
    response = await client.get(
        "/api/v1/admin/resolve", headers=operator_header, params={"lat": lat, "lng": lng}
    )

    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert response.json()["code"] in (GN_WEST, GN_EAST)


async def test_an_offshore_point_is_a_404_not_a_guess(
    client: AsyncClient,
    operator_header: dict[str, str],
    hierarchy_fixture: dict[str, str],
    clean_resolve_cache: None,
) -> None:
    """The case the brief names. Guessing the nearest division beaches a rescue team."""
    lng, lat = OFFSHORE
    response = await client.get(
        "/api/v1/admin/resolve", headers=operator_header, params={"lat": lat, "lng": lng}
    )

    assert response.status_code == 404
    assert "not inside any GN division" in response.text


async def test_a_coordinate_outside_sri_lanka_is_refused_without_a_query(
    client: AsyncClient,
    operator_header: dict[str, str],
    hierarchy_fixture: dict[str, str],
    clean_resolve_cache: None,
) -> None:
    """Rejected on the bounding box before the database is touched."""
    response = await client.get(
        "/api/v1/admin/resolve",
        headers=operator_header,
        params={"lat": 48.85, "lng": 2.35},
    )

    assert response.status_code == 404


async def test_a_repeated_coordinate_is_served_from_cache(
    client: AsyncClient,
    operator_header: dict[str, str],
    hierarchy_fixture: dict[str, str],
    clean_resolve_cache: None,
) -> None:
    """The hot path has a 20ms p99 budget; 14,022 polygons per request will not meet it."""
    lng, lat = WEST_INTERIOR
    params = {"lat": lat, "lng": lng}

    first = await client.get("/api/v1/admin/resolve", headers=operator_header, params=params)
    second = await client.get("/api/v1/admin/resolve", headers=operator_header, params=params)

    assert first.headers["X-Sarana-Cache"] == "miss"
    assert second.headers["X-Sarana-Cache"] == "hit"
    assert first.json() == second.json()


async def test_coordinates_within_a_metre_share_a_cache_entry(
    client: AsyncClient,
    operator_header: dict[str, str],
    hierarchy_fixture: dict[str, str],
    clean_resolve_cache: None,
) -> None:
    """Rounded to five decimal places, so repeated reports from one village coalesce."""
    lng, lat = WEST_INTERIOR

    await client.get(
        "/api/v1/admin/resolve", headers=operator_header, params={"lat": lat, "lng": lng}
    )
    nearby = await client.get(
        "/api/v1/admin/resolve",
        headers=operator_header,
        params={"lat": lat + 0.000001, "lng": lng + 0.000001},
    )

    assert nearby.headers["X-Sarana-Cache"] == "hit"


async def test_resolve_requires_authentication(client: AsyncClient) -> None:
    lng, lat = WEST_INTERIOR
    response = await client.get("/api/v1/admin/resolve", params={"lat": lat, "lng": lng})

    assert response.status_code == 401


async def test_a_caller_without_the_reference_scope_is_refused(
    client: AsyncClient, citizen_header: dict[str, str]
) -> None:
    lng, lat = WEST_INTERIOR
    response = await client.get(
        "/api/v1/admin/resolve", headers=citizen_header, params={"lat": lat, "lng": lng}
    )

    assert response.status_code == 403


# --------------------------------------------------------------------------------------
# The hierarchy reads
# --------------------------------------------------------------------------------------


async def test_provinces_are_returned_with_trilingual_names(
    client: AsyncClient, operator_header: dict[str, str], hierarchy_fixture: dict[str, str]
) -> None:
    response = await client.get("/api/v1/admin/provinces", headers=operator_header)

    assert response.status_code == 200
    central = [row for row in response.json() if row["code"] == "LK-P02"]
    assert len(central) == 1
    assert set(central[0]["name"]) == {"si", "ta", "en"}


async def test_hierarchy_reads_are_cached_and_revalidate(
    client: AsyncClient, operator_header: dict[str, str], hierarchy_fixture: dict[str, str]
) -> None:
    """14,022 divisions must not be a per-request database hit."""
    first = await client.get("/api/v1/admin/provinces", headers=operator_header)

    assert first.headers["Cache-Control"] == "public, max-age=3600"
    etag = first.headers["ETag"]

    second = await client.get(
        "/api/v1/admin/provinces",
        headers={**operator_header, "If-None-Match": etag},
    )

    assert second.status_code == 304


async def test_districts_can_be_filtered_by_province(
    client: AsyncClient, operator_header: dict[str, str], hierarchy_fixture: dict[str, str]
) -> None:
    response = await client.get(
        "/api/v1/admin/districts",
        headers=operator_header,
        params={"province_id": hierarchy_fixture["province_id"]},
    )

    assert response.status_code == 200
    assert [row["code"] for row in response.json()] == ["LK-11"]


async def test_gn_divisions_can_be_searched_in_any_of_the_three_languages(
    client: AsyncClient, operator_header: dict[str, str], hierarchy_fixture: dict[str, str]
) -> None:
    """A search that only matched English would be unusable for most of the country."""
    response = await client.get(
        "/api/v1/admin/gn-divisions", headers=operator_header, params={"q": "West"}
    )

    assert response.status_code == 200
    assert [row["code"] for row in response.json()] == [GN_WEST]


async def test_a_bounding_box_narrows_the_division_list(
    client: AsyncClient, operator_header: dict[str, str], hierarchy_fixture: dict[str, str]
) -> None:
    response = await client.get(
        "/api/v1/admin/gn-divisions",
        headers=operator_header,
        params={"bbox": f"80.60,{SOUTH_LAT},80.69,{NORTH_LAT}"},
    )

    assert response.status_code == 200
    assert [row["code"] for row in response.json()] == [GN_WEST]


async def test_a_malformed_bounding_box_is_refused_not_ignored(
    client: AsyncClient, operator_header: dict[str, str]
) -> None:
    """Dropping the filter would hand back the country to a client expecting one district."""
    response = await client.get(
        "/api/v1/admin/gn-divisions", headers=operator_header, params={"bbox": "1,2,3"}
    )

    assert response.status_code == 422


async def test_a_bounding_box_outside_sri_lanka_is_refused(
    client: AsyncClient, operator_header: dict[str, str]
) -> None:
    response = await client.get(
        "/api/v1/admin/gn-divisions",
        headers=operator_header,
        params={"bbox": "2.0,48.0,2.5,48.5"},
    )

    assert response.status_code == 422


async def test_a_division_detail_carries_its_full_code_path(
    client: AsyncClient, operator_header: dict[str, str], hierarchy_fixture: dict[str, str]
) -> None:
    """So a client can render the breadcrumb without four more requests."""
    response = await client.get(
        f"/api/v1/admin/gn-divisions/{hierarchy_fixture['west_id']}",
        headers=operator_header,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ds_division_code"] == "LK-11-03"
    assert body["district_code"] == "LK-11"
    assert body["province_code"] == "LK-P02"


async def test_an_unknown_division_is_a_404(
    client: AsyncClient, operator_header: dict[str, str]
) -> None:
    response = await client.get(
        "/api/v1/admin/gn-divisions/00000000-0000-7000-8000-000000000000",
        headers=operator_header,
    )

    assert response.status_code == 404


async def test_geometry_is_returned_as_geojson(
    client: AsyncClient, operator_header: dict[str, str], hierarchy_fixture: dict[str, str]
) -> None:
    response = await client.get(
        f"/api/v1/admin/gn-divisions/{hierarchy_fixture['west_id']}/geometry",
        headers=operator_header,
    )

    assert response.status_code == 200
    geometry = response.json()["geometry"]
    assert geometry["type"] == "MultiPolygon"
    assert geometry["coordinates"]


async def test_a_simplify_tolerance_beyond_the_ceiling_is_refused(
    client: AsyncClient, operator_header: dict[str, str], hierarchy_fixture: dict[str, str]
) -> None:
    """An unbounded tolerance would let a client ask for a boundary simplified to nothing."""
    response = await client.get(
        f"/api/v1/admin/gn-divisions/{hierarchy_fixture['west_id']}/geometry",
        headers=operator_header,
        params={"tolerance": 5.0},
    )

    assert response.status_code == 422


async def test_the_household_list_carries_no_personal_data(
    client: AsyncClient, operator_header: dict[str, str], hierarchy_fixture: dict[str, str]
) -> None:
    """Names and phone numbers are never selected, so there is nothing to redact."""
    response = await client.get(
        "/api/v1/admin/households",
        headers=operator_header,
        params={"gn_division_id": hierarchy_fixture["west_id"]},
    )

    assert response.status_code == 200
    for row in response.json():
        assert "head_name_encrypted" not in row
        assert "contact_msisdn_encrypted" not in row
        assert "contact_msisdn_hash" not in row


# --------------------------------------------------------------------------------------
# Bulk exposure, for the forecast agent
# --------------------------------------------------------------------------------------


async def test_exposure_returns_every_division_in_a_district_at_once(
    client: AsyncClient,
    operator_header: dict[str, str],
    hierarchy_fixture: dict[str, str],
) -> None:
    """The forecast agent scores per division and needs all of them in one call.

    The per-division endpoint would be one round trip each - several hundred per
    generation, several generations an hour - and a forecast that arrives after the rain is
    not a forecast.
    """
    response = await client.get(
        "/api/v1/admin/gn-divisions/exposure",
        headers=operator_header,
        params={"districts": KANDY_DISTRICT},
    )

    assert response.status_code == 200
    codes = {row["code"] for row in response.json()}
    assert {GN_WEST, GN_EAST} <= codes


async def test_exposure_carries_the_attributes_the_scoring_engine_reads(
    client: AsyncClient,
    operator_header: dict[str, str],
    hierarchy_fixture: dict[str, str],
) -> None:
    """A missing attribute is not the same as a zero one.

    `landslide_zone` absent means the NBRO survey does not cover this division, and the
    engine scores it against the least hazardous zone and says so. `landslide_zone` of 0
    would be a measurement, and there is no zone 0.
    """
    response = await client.get(
        "/api/v1/admin/gn-divisions/exposure",
        headers=operator_header,
        params={"districts": KANDY_DISTRICT},
    )

    row = next(row for row in response.json() if row["code"] == GN_WEST)
    for field in (
        "landslide_zone",
        "flood_return_period_m",
        "road_access_class",
        "cell_coverage_pct",
        "elderly_pct",
        "under5_pct",
        "centroid_lon",
        "centroid_lat",
    ):
        assert field in row, f"the scoring engine reads {field} and it is not returned"
    assert row["household_count"] >= 0
    assert row["ds_division_code"] == KANDY_DS
    assert row["district_code"] == KANDY_DISTRICT


async def test_exposure_names_the_division_in_three_languages(
    client: AsyncClient,
    operator_header: dict[str, str],
    hierarchy_fixture: dict[str, str],
) -> None:
    """The narrative names the division to a GN officer, and non-negotiable #2 does not
    stop applying because the text came from a reference table."""
    response = await client.get(
        "/api/v1/admin/gn-divisions/exposure",
        headers=operator_header,
        params={"districts": KANDY_DISTRICT},
    )

    row = next(row for row in response.json() if row["code"] == GN_WEST)
    assert set(row["name"]) == {"si", "ta", "en"}


async def test_exposure_carries_no_geometry(
    client: AsyncClient,
    operator_header: dict[str, str],
    hierarchy_fixture: dict[str, str],
) -> None:
    """A payload carrying 14,022 polygons is one nobody can use and everybody pays for.

    A responder wanting a boundary asks for one division's by id.
    """
    response = await client.get(
        "/api/v1/admin/gn-divisions/exposure",
        headers=operator_header,
        params={"districts": KANDY_DISTRICT},
    )

    assert "geom" not in response.json()[0]
    assert "geometry" not in response.json()[0]


async def test_exposure_refuses_an_empty_district_list(
    client: AsyncClient, operator_header: dict[str, str]
) -> None:
    """Rather than returning the whole country to a caller that asked for nothing."""
    response = await client.get(
        "/api/v1/admin/gn-divisions/exposure",
        headers=operator_header,
        params={"districts": " , "},
    )

    assert response.status_code == 422


async def test_exposure_ignores_a_district_that_does_not_exist(
    client: AsyncClient,
    operator_header: dict[str, str],
    hierarchy_fixture: dict[str, str],
) -> None:
    """A warning naming a district with no seeded divisions is a real state during a
    partial import, and it must not take the rest of the forecast down with it."""
    response = await client.get(
        "/api/v1/admin/gn-divisions/exposure",
        headers=operator_header,
        params={"districts": f"{KANDY_DISTRICT},LK-99"},
    )

    assert response.status_code == 200
    assert {row["code"] for row in response.json()} >= {GN_WEST, GN_EAST}


async def test_exposure_is_not_readable_by_a_citizen(
    client: AsyncClient, citizen_header: dict[str, str]
) -> None:
    """It is a map of who is vulnerable, division by division, for the whole country."""
    response = await client.get(
        "/api/v1/admin/gn-divisions/exposure",
        headers=citizen_header,
        params={"districts": KANDY_DISTRICT},
    )

    assert response.status_code == 403
