"""Reads over the administrative hierarchy.

Every function here returns plain dictionaries rather than ORM instances. These rows are
cached and ETagged, and a detached ORM object that lazy-loads on attribute access from
inside a cache entry is a latent database call on the hot path.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from sarana_shared.domain.geo import in_sri_lanka

# The geometry column is WGS84, so a simplify tolerance is in degrees. At Sri Lankan
# latitudes 0.05 degrees is roughly five kilometres, which is already coarser than any
# useful rendering and a sane ceiling on what a client may ask for.
MAX_SIMPLIFY_TOLERANCE: Final = 0.05
DEFAULT_SIMPLIFY_TOLERANCE: Final = 0.0

# Coordinates are rounded before being used as a cache key. Five decimal places is about
# a metre - finer than any GPS fix a phone will produce, and coarse enough that repeated
# reports from one village share an entry.
RESOLVE_PRECISION: Final = 5

_PROVINCES_SQL = "SELECT id::text, code, name FROM admin.province ORDER BY code"

_DISTRICTS_SQL = """
SELECT id::text, code, name, province_id::text
FROM admin.district
WHERE (CAST(:province_id AS uuid) IS NULL OR province_id = CAST(:province_id AS uuid))
ORDER BY code
"""

_DS_DIVISIONS_SQL = """
SELECT id::text, code, name, district_id::text
FROM admin.ds_division
WHERE (CAST(:district_id AS uuid) IS NULL OR district_id = CAST(:district_id AS uuid))
ORDER BY code
"""

# The name is trilingual JSONB, so a text search has to look in all three locales. A
# search that only matched English would be unusable for most of the country.
_GN_DIVISIONS_SQL = """
SELECT g.id::text, g.code, g.name, g.ds_division_id::text,
       g.population, g.household_count,
       ST_X(g.centroid) AS centroid_lon,
       ST_Y(g.centroid) AS centroid_lat
FROM admin.gn_division g
WHERE (CAST(:ds_division_id AS uuid) IS NULL
       OR g.ds_division_id = CAST(:ds_division_id AS uuid))
  AND (CAST(:min_lon AS double precision) IS NULL
       OR g.geom && ST_MakeEnvelope(
              CAST(:min_lon AS double precision), CAST(:min_lat AS double precision),
              CAST(:max_lon AS double precision), CAST(:max_lat AS double precision), 4326))
  AND (CAST(:q AS text) IS NULL
       OR g.code ILIKE :like
       OR g.name->>'si' ILIKE :like
       OR g.name->>'ta' ILIKE :like
       OR g.name->>'en' ILIKE :like)
ORDER BY g.code
LIMIT :limit OFFSET :offset
"""

_GN_EXPOSURE_SQL = """
SELECT g.id::text, g.code, g.name,
       g.population, g.household_count, g.elderly_pct, g.under5_pct,
       g.landslide_zone, g.flood_return_period_m, g.road_access_class,
       g.cell_coverage_pct,
       ST_X(g.centroid) AS centroid_lon,
       ST_Y(g.centroid) AS centroid_lat,
       d.code AS ds_division_code,
       dt.code AS district_code
FROM admin.gn_division g
JOIN admin.ds_division d ON d.id = g.ds_division_id
JOIN admin.district dt ON dt.id = d.district_id
WHERE dt.code = ANY(CAST(:district_codes AS text[]))
ORDER BY g.code
LIMIT :limit
"""

_GN_DIVISION_SQL = """
SELECT g.id::text, g.code, g.name, g.ds_division_id::text,
       g.population, g.household_count, g.elderly_pct, g.under5_pct,
       g.landslide_zone, g.flood_return_period_m, g.road_access_class,
       g.cell_coverage_pct,
       ST_X(g.centroid) AS centroid_lon,
       ST_Y(g.centroid) AS centroid_lat,
       d.code AS ds_division_code,
       dt.code AS district_code,
       p.code AS province_code
FROM admin.gn_division g
JOIN admin.ds_division d ON d.id = g.ds_division_id
JOIN admin.district dt ON dt.id = d.district_id
JOIN admin.province p ON p.id = dt.province_id
WHERE g.id = :division_id
"""

# ST_SimplifyPreserveTopology rather than ST_Simplify: a simplification that punches a
# hole in a boundary or crosses it over itself would place households in the wrong
# division, which is the one thing this endpoint must never do.
_GN_GEOMETRY_SQL = """
SELECT g.id::text, g.code,
       ST_AsGeoJSON(
           CASE WHEN :tolerance > 0
                THEN ST_SimplifyPreserveTopology(g.geom, :tolerance)
                ELSE g.geom END
       ) AS geojson
FROM admin.gn_division g
WHERE g.id = :division_id
"""

_RESOLVE_SQL = """
SELECT g.id::text, g.code, g.name, g.ds_division_id::text,
       d.code AS ds_division_code,
       dt.code AS district_code,
       p.code AS province_code
FROM admin.gn_division g
JOIN admin.ds_division d ON d.id = g.ds_division_id
JOIN admin.district dt ON dt.id = d.district_id
JOIN admin.province p ON p.id = dt.province_id
WHERE ST_Contains(g.geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
LIMIT 1
"""

# The encrypted columns are not selected at all rather than selected and dropped later: a
# query that never reads a name cannot leak one through a logging change or a stray
# model_dump(). Row-level security still applies on top of this.
_HOUSEHOLDS_SQL = """
SELECT h.id::text, h.reference_code, h.gn_division_id::text,
       h.member_count, h.has_over_70, h.has_under_5,
       h.has_mobility_impairment, h.preferred_language
FROM admin.household h
WHERE h.gn_division_id = :gn_division_id
ORDER BY h.reference_code
LIMIT :limit OFFSET :offset
"""


def resolve_cache_key(lon: float, lat: float) -> str:
    """The cache key for a coordinate lookup, rounded to metre precision."""
    return f"{round(lon, RESOLVE_PRECISION)}:{round(lat, RESOLVE_PRECISION)}"


async def list_provinces(session: AsyncSession) -> list[dict[str, Any]]:
    """All nine provinces, ordered by code."""
    result = await session.execute(text(_PROVINCES_SQL))
    return [dict(row) for row in result.mappings()]


async def list_districts(
    session: AsyncSession, *, province_id: UUID | None = None
) -> list[dict[str, Any]]:
    """Districts, optionally within one province."""
    result = await session.execute(text(_DISTRICTS_SQL), {"province_id": province_id})
    return [dict(row) for row in result.mappings()]


async def list_ds_divisions(
    session: AsyncSession, *, district_id: UUID | None = None
) -> list[dict[str, Any]]:
    """DS divisions, optionally within one district."""
    result = await session.execute(text(_DS_DIVISIONS_SQL), {"district_id": district_id})
    return [dict(row) for row in result.mappings()]


async def list_gn_divisions(
    session: AsyncSession,
    *,
    ds_division_id: UUID | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    q: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """GN divisions, narrowed by parent, bounding box or name.

    There are ~14,022 of these, so this always paginates and never returns geometry. A
    client that wants a boundary asks for one division's geometry by id.
    """
    min_lon, min_lat, max_lon, max_lat = bbox if bbox else (None, None, None, None)
    result = await session.execute(
        text(_GN_DIVISIONS_SQL),
        {
            "ds_division_id": ds_division_id,
            "min_lon": min_lon,
            "min_lat": min_lat,
            "max_lon": max_lon,
            "max_lat": max_lat,
            "q": q,
            "like": f"%{q}%" if q else None,
            "limit": limit,
            "offset": offset,
        },
    )
    return [dict(row) for row in result.mappings()]


async def get_gn_division(session: AsyncSession, division_id: UUID) -> dict[str, Any] | None:
    """One GN division with its vulnerability denominators, or None."""
    result = await session.execute(text(_GN_DIVISION_SQL), {"division_id": division_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def get_gn_geometry(
    session: AsyncSession,
    division_id: UUID,
    *,
    tolerance: float = DEFAULT_SIMPLIFY_TOLERANCE,
) -> dict[str, Any] | None:
    """One division's boundary as GeoJSON, optionally simplified."""
    clamped = max(0.0, min(tolerance, MAX_SIMPLIFY_TOLERANCE))
    result = await session.execute(
        text(_GN_GEOMETRY_SQL), {"division_id": division_id, "tolerance": clamped}
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def resolve_point(session: AsyncSession, *, lon: float, lat: float) -> dict[str, Any] | None:
    """The GN division containing a coordinate, or None.

    On the hot path for every citizen report. ST_Contains against the GiST index on
    `geom` is an index scan followed by an exact test on a handful of candidates.

    Returns None rather than the nearest division for a point outside every boundary. A
    report from three kilometres offshore is a GPS error or a mistake, and guessing a
    division for it would send a rescue team to the wrong beach.
    """
    if not in_sri_lanka(lon, lat):
        return None

    result = await session.execute(text(_RESOLVE_SQL), {"lon": lon, "lat": lat})
    row = result.mappings().first()
    return dict(row) if row else None


async def list_households(
    session: AsyncSession, *, gn_division_id: UUID, limit: int = 200, offset: int = 0
) -> list[dict[str, Any]]:
    """Households in one division, with no personal data."""
    result = await session.execute(
        text(_HOUSEHOLDS_SQL),
        {"gn_division_id": gn_division_id, "limit": limit, "offset": offset},
    )
    return [dict(row) for row in result.mappings()]


# One household's messaging address, and nothing else.
#
# Deliberately a different query from `_HOUSEHOLDS_SQL`, which selects no column that
# identifies a person. That guarantee is worth keeping intact, so contact lookup is its
# own query behind its own scope rather than a widening of the listing.
#
# What comes back is a keyed HMAC, never a phone number. A messaging gateway resolves the
# hash to a real address at the edge; nothing in this platform decrypts a number in order
# to send to it. `preferred_language` rides along because a message in the wrong language
# is a message that did not arrive.
_HOUSEHOLD_CONTACT_SQL = """
SELECT h.id::text                AS household_id,
       h.reference_code,
       h.contact_msisdn_hash     AS recipient_ref_hash,
       h.preferred_language,
       g.code                    AS gn_division_code
FROM admin.household h
JOIN admin.gn_division g ON g.id = h.gn_division_id
WHERE h.id = :household_id
"""


async def household_contact(session: AsyncSession, *, household_id: UUID) -> dict[str, Any] | None:
    """How to reach one household, as a keyed hash.

    Row-level security applies, so a caller scoped to one district cannot read a
    household in another - a machine credential is subject to it on exactly the same
    terms as a person.

    Returns None both when the household does not exist and when it is out of scope. The
    caller cannot tell those apart, which is correct: saying "this household exists but
    is not yours" is itself a disclosure.
    """
    result = await session.execute(text(_HOUSEHOLD_CONTACT_SQL), {"household_id": household_id})
    row = result.mappings().first()
    return dict(row) if row else None


# Every messaging address in one division, for an alert fan-out.
#
# The bulk form of `_HOUSEHOLD_CONTACT_SQL`, and behind the same scope. Targeting a
# district one household at a time would be thousands of round trips during exactly the
# minutes when core-api is busiest and a warning is most time-critical.
#
# Ordered by reference so paging is stable: a fan-out that re-read a page mid-dispatch and
# got a different slice would send twice to some households and never to others.
#
# `contact_msisdn_hash` may be NULL. Those rows are returned rather than filtered, because
# "this division has 480 households and 63 of them cannot be reached by SMS" is the answer
# an operator needs; filtering would report the division as fully covered.
_DIVISION_CONTACTS_SQL = """
SELECT h.id::text                AS household_id,
       h.reference_code,
       h.contact_msisdn_hash     AS recipient_ref_hash,
       h.preferred_language,
       g.code                    AS gn_division_code
FROM admin.household h
JOIN admin.gn_division g ON g.id = h.gn_division_id
WHERE g.code = ANY(CAST(:gn_division_codes AS text[]))
ORDER BY g.code, h.reference_code
LIMIT :limit OFFSET :offset
"""


async def division_contacts(
    session: AsyncSession,
    *,
    gn_division_codes: list[str],
    limit: int = 5000,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Messaging addresses for every household in these divisions.

    Row-level security applies, so a caller scoped to one district gets that district's
    rows and nothing else - which is what makes an alerting service's reach a property of
    its credential rather than of its own restraint.
    """
    result = await session.execute(
        text(_DIVISION_CONTACTS_SQL),
        {"gn_division_codes": gn_division_codes, "limit": limit, "offset": offset},
    )
    return [dict(row) for row in result.mappings()]


async def list_gn_exposure(
    session: AsyncSession,
    *,
    district_codes: list[str],
    limit: int = 5000,
) -> list[dict[str, Any]]:
    """Every division in these districts, with the exposure attributes, in one query.

    The forecast agent needs all of them at once: it scores per division and the
    per-division endpoint would be one HTTP round trip per division, several hundred per
    generation, several generations an hour. That is not a performance nicety - it is the
    difference between a forecast that arrives before the rain and one that does not.

    Districts rather than a bounding box because that is what a Met warning names, and
    resolving a warning to a box and back to divisions would lose the districts the
    Department was actually talking about.

    No geometry, ever. A responder wanting a boundary asks for one division's by id; a
    payload carrying 14,022 polygons is one nobody can use and everybody pays for.
    """
    result = await session.execute(
        text(_GN_EXPOSURE_SQL),
        {"district_codes": district_codes, "limit": limit},
    )
    return [dict(row) for row in result.mappings()]
