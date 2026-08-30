"""The administrative hierarchy: the reference data everything else joins against.

These are the most-read and least-changed endpoints on the platform. They are cached
hard, revalidated with an ETag, and - where it matters - able to serve a stale answer with
`X-Sarana-Stale: true` rather than fail. A console that cannot draw the map during a
cyclone is worse than one drawing yesterday's boundaries.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from core_api.api.deps import SessionDep
from core_api.cache import (
    HIERARCHY_MAX_AGE,
    apply_cache_headers,
    etag_for,
    matches,
    not_modified,
)
from core_api.domain import hierarchy
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.domain.geo import (
    LK_BBOX_MAX_LAT,
    LK_BBOX_MAX_LON,
    LK_BBOX_MIN_LAT,
    LK_BBOX_MIN_LON,
)
from sarana_shared.errors import NotFound, ValidationFailed

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["hierarchy"])

ReadPrincipal = Depends(require(Scope.ADMIN_READ))

# Reading a household's contact hash is the one hierarchy call that reaches a stable
# per-person identifier, so it gets its own scope. In practice one credential holds it:
# the service that sends the messages.
ContactPrincipal = Depends(require(Scope.HOUSEHOLD_CONTACT_READ))

# How many divisions one bulk contact request may name. A national alert covers ~14,000,
# and a single query over all of them would hold a connection long enough to matter during
# the one event when it must not. The caller pages; this is the ceiling on one page.
MAX_DIVISIONS_PER_REQUEST = 200


class AreaSummary(BaseModel):
    """A hierarchy node, without geometry."""

    model_config = ConfigDict(frozen=True)

    id: str
    code: str
    name: dict[str, str]


class DistrictSummary(AreaSummary):
    province_id: str


class DSDivisionSummary(AreaSummary):
    district_id: str


class GNDivisionSummary(AreaSummary):
    ds_division_id: str
    population: int
    household_count: int
    centroid_lon: float | None = None
    centroid_lat: float | None = None


class GNDivisionDetail(GNDivisionSummary):
    """One division, with the exposure denominators the forecasting agent needs."""

    elderly_pct: float | None = None
    under5_pct: float | None = None
    landslide_zone: int | None = None
    flood_return_period_m: int | None = None
    road_access_class: int | None = None
    cell_coverage_pct: float | None = None
    ds_division_code: str
    district_code: str
    province_code: str


class ResolvedArea(BaseModel):
    """The division a coordinate falls in."""

    model_config = ConfigDict(frozen=True)

    id: str
    code: str
    name: dict[str, str]
    ds_division_id: str
    ds_division_code: str
    district_code: str
    province_code: str


class HouseholdSummary(BaseModel):
    """A household with no personal data.

    Names and phone numbers are never selected by the query behind this, so there is
    nothing here to redact - which is a stronger guarantee than redacting.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    reference_code: str
    gn_division_id: str
    member_count: int
    has_over_70: bool
    has_under_5: bool
    has_mobility_impairment: bool
    preferred_language: str


def _cached_list(
    request: Request, response: Response, payload: list[dict[str, Any]]
) -> Response | list[dict[str, Any]]:
    """Attach cache headers, or return 304 if the client is already current."""
    tag = etag_for(payload)
    if matches(request, tag):
        return not_modified(tag, max_age=HIERARCHY_MAX_AGE)
    apply_cache_headers(response, etag=tag, max_age=HIERARCHY_MAX_AGE)
    return payload


@router.get("/provinces", response_model=list[AreaSummary])
async def get_provinces(
    request: Request,
    response: Response,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
) -> Any:
    """All nine provinces."""
    return _cached_list(request, response, await hierarchy.list_provinces(session))


@router.get("/districts", response_model=list[DistrictSummary])
async def get_districts(
    request: Request,
    response: Response,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    province_id: UUID | None = Query(default=None),
) -> Any:
    """Districts, optionally within one province."""
    rows = await hierarchy.list_districts(session, province_id=province_id)
    return _cached_list(request, response, rows)


@router.get("/ds-divisions", response_model=list[DSDivisionSummary])
async def get_ds_divisions(
    request: Request,
    response: Response,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    district_id: UUID | None = Query(default=None),
) -> Any:
    """DS divisions, optionally within one district."""
    rows = await hierarchy.list_ds_divisions(session, district_id=district_id)
    return _cached_list(request, response, rows)


@router.get("/gn-divisions", response_model=list[GNDivisionSummary])
async def get_gn_divisions(
    request: Request,
    response: Response,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    ds_division_id: UUID | None = Query(default=None),
    bbox: str | None = Query(default=None, description="min_lon,min_lat,max_lon,max_lat in WGS84"),
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """GN divisions, narrowed by parent, bounding box or name.

    Always paginated: there are ~14,022 of these and no client wants all of them at once.
    """
    parsed = _parse_bbox(bbox)
    rows = await hierarchy.list_gn_divisions(
        session,
        ds_division_id=ds_division_id,
        bbox=parsed,
        q=q,
        limit=limit,
        offset=offset,
    )
    return _cached_list(request, response, rows)


def _parse_bbox(raw: str | None) -> tuple[float, float, float, float] | None:
    """Parse and sanity-check a bounding box.

    A malformed box is refused rather than ignored. Silently dropping the filter would
    return the whole country to a client that asked for one district and thought it had
    got one.
    """
    if raw is None:
        return None

    parts = raw.split(",")
    if len(parts) != 4:
        raise ValidationFailed(
            "bbox must be four comma-separated numbers: min_lon,min_lat,max_lon,max_lat",
            context={"bbox": raw},
        )
    try:
        min_lon, min_lat, max_lon, max_lat = (float(part) for part in parts)
    except ValueError as error:
        raise ValidationFailed("bbox values must be numbers", context={"bbox": raw}) from error

    if min_lon >= max_lon or min_lat >= max_lat:
        raise ValidationFailed(
            "bbox minimums must be smaller than its maximums", context={"bbox": raw}
        )
    outside = (
        max_lon < LK_BBOX_MIN_LON
        or min_lon > LK_BBOX_MAX_LON
        or max_lat < LK_BBOX_MIN_LAT
        or min_lat > LK_BBOX_MAX_LAT
    )
    if outside:
        raise ValidationFailed("bbox does not overlap Sri Lanka", context={"bbox": raw})
    return min_lon, min_lat, max_lon, max_lat


@router.get("/gn-divisions/{division_id}", response_model=GNDivisionDetail)
async def get_gn_division(
    division_id: UUID,
    request: Request,
    response: Response,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
) -> Any:
    """One GN division and its vulnerability denominators."""
    row = await hierarchy.get_gn_division(session, division_id)
    if row is None:
        raise NotFound("No such GN division.", context={"gn_division_id": str(division_id)})

    tag = etag_for(row)
    if matches(request, tag):
        return not_modified(tag, max_age=HIERARCHY_MAX_AGE)
    apply_cache_headers(response, etag=tag, max_age=HIERARCHY_MAX_AGE)
    return row


@router.get("/gn-divisions/{division_id}/geometry")
async def get_gn_division_geometry(
    division_id: UUID,
    request: Request,
    response: Response,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    tolerance: float = Query(
        default=hierarchy.DEFAULT_SIMPLIFY_TOLERANCE,
        ge=0.0,
        le=hierarchy.MAX_SIMPLIFY_TOLERANCE,
        description="Simplification tolerance in degrees. 0 returns the exact boundary.",
    ),
) -> Any:
    """A division boundary as GeoJSON, optionally simplified for rendering."""
    row = await hierarchy.get_gn_geometry(session, division_id, tolerance=tolerance)
    if row is None:
        raise NotFound("No such GN division.", context={"gn_division_id": str(division_id)})

    import json

    payload = {
        "id": row["id"],
        "code": row["code"],
        "tolerance": tolerance,
        "geometry": json.loads(row["geojson"]) if row["geojson"] else None,
    }
    tag = etag_for(payload)
    if matches(request, tag):
        return not_modified(tag, max_age=HIERARCHY_MAX_AGE)
    apply_cache_headers(response, etag=tag, max_age=HIERARCHY_MAX_AGE)
    return payload


@router.get("/resolve", response_model=ResolvedArea)
async def resolve_coordinate(
    request: Request,
    response: Response,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    lat: float = Query(ge=-90.0, le=90.0),
    lng: float = Query(ge=-180.0, le=180.0),
) -> Any:
    """The GN division containing a coordinate.

    On the hot path for every citizen report, with a p99 budget of 20ms. Answers are
    cached by coordinate rounded to five decimal places - about a metre - so repeated
    reports from one village share an entry.

    A point outside every boundary is a 404, not the nearest division. Guessing would send
    responders to the wrong place, and a GPS fix three kilometres offshore is an error
    worth surfacing rather than smoothing over.
    """
    cache = request.app.state.resolve_cache
    key = hierarchy.resolve_cache_key(lng, lat)

    hit = cache.get(key)
    if hit is not None:
        if hit == "__miss__":
            raise NotFound(
                "That coordinate is not inside any GN division.",
                context={"lat": lat, "lng": lng},
            )
        response.headers["X-Sarana-Cache"] = "hit"
        return hit

    row = await hierarchy.resolve_point(session, lon=lng, lat=lat)
    if row is None:
        # Negative results are cached too. An offshore coordinate retried in a loop by a
        # confused client must not become a stream of index scans.
        cache.put(key, "__miss__")
        raise NotFound(
            "That coordinate is not inside any GN division.",
            context={"lat": lat, "lng": lng},
        )

    cache.put(key, row)
    response.headers["X-Sarana-Cache"] = "miss"
    return row


@router.get("/households", response_model=list[HouseholdSummary])
async def get_households(
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    gn_division_id: Annotated[UUID, Query()] = ...,  # type: ignore[assignment]
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Households in one division, scoped by row-level security and PII-free.

    Not cached: this is the one hierarchy endpoint whose rows are about people, and a
    shared cache keyed by URL would serve one officer's scoped result to another.
    """
    return await hierarchy.list_households(
        session, gn_division_id=gn_division_id, limit=limit, offset=offset
    )


class HouseholdContact(BaseModel):
    """Where to send a message for one household.

    `recipient_ref_hash` is a keyed HMAC of the contact number, never the number. A
    messaging gateway resolves it to a real address at the edge, so the platform can
    address a household without ever holding a phone number that could be exported.

    It is still a stable per-person identifier, which is why it sits behind its own scope
    rather than behind `admin:read`.
    """

    model_config = ConfigDict(frozen=True)

    household_id: str
    reference_code: str
    recipient_ref_hash: str | None = Field(
        description="Null for a household with no contact number on file. That is a real "
        "and common state - not everybody has a phone - and a caller must treat it as "
        "'cannot be messaged' rather than as an error."
    )
    preferred_language: str
    gn_division_code: str


@router.get("/households/{household_id}/contact", response_model=HouseholdContact)
async def get_household_contact(
    household_id: UUID,
    session: SessionDep,
    principal: Principal = ContactPrincipal,
) -> Any:
    """How to reach one household, for a service that has something to tell them.

    Behind `household:contact_read` rather than `admin:read`, and held by one credential:
    the messaging service. Every other reader of the hierarchy - the console, the
    dashboard, the agents - keeps the weaker scope and cannot reach a per-person
    identifier at all.

    Never cached. This is per-household and scope-sensitive, and a shared cache keyed by
    URL would serve one caller's authorised answer to another.
    """
    found = await hierarchy.household_contact(session, household_id=household_id)
    if found is None:
        # Absent and out-of-scope are the same answer on purpose. Confirming that a
        # household exists but belongs to another district is a disclosure in itself.
        raise NotFound("No such household.")
    return found


class DivisionContacts(BaseModel):
    """Every messaging address in a set of divisions, one page at a time."""

    model_config = ConfigDict(frozen=True)

    contacts: list[HouseholdContact]
    next_offset: int | None = Field(
        default=None,
        description="Pass as `offset` to continue. Null when the last page is reached.",
    )


@router.get("/households/contacts", response_model=DivisionContacts)
async def get_division_contacts(
    session: SessionDep,
    principal: Principal = ContactPrincipal,
    gn_division_code: Annotated[list[str], Query()] = ...,  # type: ignore[assignment]
    limit: int = Query(default=2000, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Messaging addresses for a whole area, for an alert fan-out.

    The bulk form of the single-household lookup, behind the same scope. Warning a district
    one household at a time would be thousands of round trips during the minutes when this
    service is busiest and the warning is most time-critical.

    **Households with no contact number are returned, not filtered.** `recipient_ref_hash`
    is null for them. That is the answer an operator needs — "480 households here, 63 of
    whom cannot be reached by SMS" — and filtering would report the division as fully
    covered when a sixth of it is unreachable.

    Never cached. Scope-sensitive and per-division; a shared cache keyed by URL would serve
    one caller's authorised answer to another.
    """
    if not gn_division_code:
        raise ValidationFailed("Name at least one gn_division_code.")
    if len(gn_division_code) > MAX_DIVISIONS_PER_REQUEST:
        raise ValidationFailed(
            f"At most {MAX_DIVISIONS_PER_REQUEST} divisions per request; page through larger areas."
        )

    rows = await hierarchy.division_contacts(
        session, gn_division_codes=list(gn_division_code), limit=limit, offset=offset
    )
    return {
        "contacts": rows,
        # A full page means there may be more. One extra empty request at the end is
        # cheaper than a fan-out that silently stopped at a page boundary.
        "next_offset": (offset + limit) if len(rows) == limit else None,
    }
