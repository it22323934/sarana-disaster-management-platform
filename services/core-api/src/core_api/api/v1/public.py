"""Administrative area reference, readable without a credential.

The public transparency dashboard reads `LK-21` from ledger-svc and has to turn it into
"Kandy" / "මහනුවර" / "கண்டி" before a reader can use any figure on the page. `/admin/districts`
answers that question and requires `admin:read`, which a journalist does not have and should
not need - so this is the same reference data on the terms the dashboard is served on.

**These are not data about anyone.** A district name is on every road sign in the country
and a district boundary is published by the Survey Department. The one table in this schema
that is about people, `admin.household`, is under row-level security and is not read here
or anywhere near here.

Cached with the same ETag and max-age as the authenticated hierarchy endpoints. Boundaries
change on a timescale of years and the dashboard is the most-read surface on the platform,
so a revalidating client should almost always get a 304.

**The boundaries are generated, and the code says so rather than the release notes.** The
seed produces geometry at GN level only, as rectangles around real district centroids, and
`admin.district.geom` is null. A district outline here is the union of its GN rectangles:
an accurate statement of where this platform believes its divisions are, and not a survey
boundary. `is_generated` is on every geometry response so a consumer cannot use it without
seeing that, and the dashboard's `/methodology` page repeats it in words.
"""

from __future__ import annotations

import json
from typing import Any, Final

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from core_api.api.deps import PublicSessionDep
from core_api.cache import HIERARCHY_MAX_AGE, apply_cache_headers, etag_for, matches, not_modified
from core_api.domain import hierarchy

router = APIRouter(prefix="/public/areas", tags=["public"])

GEOMETRY_NOTE: Final = (
    "Generated boundaries, not survey boundaries. This seed carries geometry at GN "
    "division level only, as rectangles around real district centroids; a district outline "
    "here is the union of those rectangles. Real coordinates for the district centroids, "
    "invented shapes around them. Do not use for navigation, land administration or any "
    "purpose where a boundary is the answer."
)


class PublicArea(BaseModel):
    """One administrative area: its code, its name in three languages, and its size.

    The code is the identity and the name is a label - the convention throughout SARANA.
    A page that keyed on the name would break the first time a district was transliterated
    differently, and codes are what every figure on the dashboard is joined by.
    """

    model_config = ConfigDict(frozen=True)

    code: str
    name: dict[str, str]
    gn_division_count: int
    population: int
    household_count: int


class PublicDistrict(PublicArea):
    province_code: str
    province_name: dict[str, str]
    centroid_lon: float | None = Field(
        default=None, description="Mean of the district's GN centroids. Null if it has none."
    )
    centroid_lat: float | None = None


class PublicDSDivision(PublicArea):
    district_code: str


class PublicDistrictsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    districts: list[PublicDistrict]


class PublicDSDivisionsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ds_divisions: list[PublicDSDivision]


@router.get("/districts", response_model=PublicDistrictsResponse)
async def public_districts(request: Request, response: Response, session: PublicSessionDep) -> Any:
    """Every district, with its trilingual name and its province. No authentication."""
    payload = {"districts": await hierarchy.public_districts(session)}

    tag = etag_for(payload)
    if matches(request, tag):
        return not_modified(tag, max_age=HIERARCHY_MAX_AGE)

    apply_cache_headers(response, etag=tag, max_age=HIERARCHY_MAX_AGE)
    return payload


@router.get("/ds-divisions", response_model=PublicDSDivisionsResponse)
async def public_ds_divisions(
    request: Request,
    response: Response,
    session: PublicSessionDep,
    district_code: str | None = Query(default=None, max_length=8, examples=["LK-21"]),
) -> Any:
    """DS divisions, optionally within one district. No authentication.

    The drill-down level on the dashboard's district page. GN divisions are deliberately
    not published here: ledger-svc suppresses money below DS, and offering the finer
    reference list would invite a consumer to join at a level the figures do not exist at.
    """
    rows = await hierarchy.public_ds_divisions(session, district_code=district_code)
    payload = {"ds_divisions": rows}

    tag = etag_for(payload)
    if matches(request, tag):
        return not_modified(tag, max_age=HIERARCHY_MAX_AGE)

    apply_cache_headers(response, etag=tag, max_age=HIERARCHY_MAX_AGE)
    return payload


@router.get("/districts.geojson")
async def public_district_geometry(
    request: Request,
    response: Response,
    session: PublicSessionDep,
    tolerance: float = Query(
        default=0.01,
        ge=0.0,
        le=hierarchy.MAX_SIMPLIFY_TOLERANCE,
        description="Simplification in WGS84 degrees. The default is roughly one "
        "kilometre, which is finer than a national choropleth can show and keeps the "
        "payload small enough to serve a cheap phone on 3G.",
    ),
) -> Any:
    """District outlines as a GeoJSON FeatureCollection. No authentication.

    A FeatureCollection rather than one geometry per request: the choropleth needs all
    twenty-five at once, and twenty-five requests over a slow connection would draw the map
    in visible stages. It is one hard-cached response instead.

    Each feature carries only its district code. The metrics are joined on the client from
    `/api/v1/public/districts` on ledger-svc, which keeps the boundary payload cacheable
    for an hour while the figures revalidate every five minutes.
    """
    rows = await hierarchy.public_district_geometry(session, tolerance=tolerance)

    payload = {
        "type": "FeatureCollection",
        "is_generated": True,
        "note": GEOMETRY_NOTE,
        "features": [
            {
                "type": "Feature",
                "id": row["code"],
                "properties": {"district_code": row["code"]},
                "geometry": json.loads(row["geojson"]) if row["geojson"] else None,
            }
            for row in rows
        ],
    }

    tag = etag_for(payload)
    if matches(request, tag):
        return not_modified(tag, max_age=HIERARCHY_MAX_AGE)

    apply_cache_headers(response, etag=tag, max_age=HIERARCHY_MAX_AGE)
    return payload
