"""Geospatial types and constants.

Conventions:
  - SRID 4326 for storage and API. Project to 5235 (Sri Lanka Grid 1999) only for
    distance and area maths.
  - GN division boundaries are MULTIPOLYGON. Incident locations are POINT.
  - Every point carries accuracy_m and source. A point with no accuracy is not trusted
    for dispatch.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Storage and API SRID. Everything crossing a boundary is WGS 84 lon/lat.
SRID_WGS84: Final = 4326

# Sri Lanka Grid 1999 (Kandawala / SLD99). Metre units - use for distance and area only.
SRID_SLD99: Final = 5235

# Bounding box of Sri Lanka including territorial waters, used as a sanity gate on
# inbound coordinates. A report that lands outside this box is a data error, not a
# location - most often swapped lat/lon.
LK_BBOX_MIN_LON: Final = 79.0
LK_BBOX_MAX_LON: Final = 82.2
LK_BBOX_MIN_LAT: Final = 5.7
LK_BBOX_MAX_LAT: Final = 10.0

EARTH_RADIUS_M: Final = 6_371_008.8

# Above this radius a fix locates a village, not a household. Dispatch needs better.
DISPATCH_ACCURACY_CEILING_M: Final = 500.0


class PointSource(StrEnum):
    """How a coordinate was obtained. Drives how much the system trusts it."""

    GPS = "gps"
    CELL = "cell"
    MANUAL = "manual"
    INFERRED = "inferred"


# Typical accuracy floors by source, used when a client reports a source but no radius.
_SOURCE_DEFAULT_ACCURACY_M: Final[dict[PointSource, float]] = {
    PointSource.GPS: 15.0,
    PointSource.CELL: 1_500.0,
    PointSource.MANUAL: 100.0,
    PointSource.INFERRED: 5_000.0,
}


class GeoPoint(BaseModel):
    """A located observation in WGS 84, with provenance.

    There is no constructor path that produces a point without an accuracy and a source.
    Triage and dispatch read `trusted_for_dispatch` rather than re-deriving the rule.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    lon: float = Field(ge=-180.0, le=180.0)
    lat: float = Field(ge=-90.0, le=90.0)
    accuracy_m: float = Field(gt=0.0, description="68% confidence radius in metres")
    source: PointSource

    @model_validator(mode="after")
    def _sanity_check_bbox(self) -> Self:
        if not in_sri_lanka(self.lon, self.lat):
            swapped_is_plausible = in_sri_lanka(self.lat, self.lon)
            hint = " - lon and lat look swapped" if swapped_is_plausible else ""
            raise ValueError(
                f"coordinate ({self.lon}, {self.lat}) is outside the Sri Lanka bounding box{hint}"
            )
        return self

    @classmethod
    def from_source(
        cls,
        lon: float,
        lat: float,
        source: PointSource,
        accuracy_m: float | None = None,
    ) -> GeoPoint:
        """Build a point, defaulting accuracy from the source when a client omits it."""
        return cls(
            lon=lon,
            lat=lat,
            source=source,
            accuracy_m=accuracy_m if accuracy_m is not None else _SOURCE_DEFAULT_ACCURACY_M[source],
        )

    @property
    def trusted_for_dispatch(self) -> bool:
        """Whether this fix is precise enough to route a responder to.

        A point that fails this does not block an incident - it routes to the operator
        for a location confirmation instead of sending a crew to a 5km circle.
        """
        return self.accuracy_m <= DISPATCH_ACCURACY_CEILING_M

    @property
    def wkt(self) -> str:
        """Well-known text for PostGIS, longitude first."""
        return f"POINT({self.lon} {self.lat})"

    def as_geojson(self) -> dict[str, object]:
        """GeoJSON geometry. Coordinates are [lon, lat] per RFC 7946."""
        return {"type": "Point", "coordinates": [self.lon, self.lat]}

    def distance_to(self, other: GeoPoint) -> float:
        """Great-circle distance in metres.

        Adequate for dedup candidate windows and proximity sorting. Anything that needs
        true planar distance projects to SRID 5235 in the database instead.
        """
        return haversine_m(self.lon, self.lat, other.lon, other.lat)


class BoundingBox(BaseModel):
    """An axis-aligned WGS 84 extent, used for map viewport and tile queries."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_lon: float = Field(ge=-180.0, le=180.0)
    min_lat: float = Field(ge=-90.0, le=90.0)
    max_lon: float = Field(ge=-180.0, le=180.0)
    max_lat: float = Field(ge=-90.0, le=90.0)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.min_lon >= self.max_lon or self.min_lat >= self.max_lat:
            raise ValueError("bounding box minimums must be strictly less than maximums")
        return self

    def contains(self, point: GeoPoint) -> bool:
        """Whether a point falls inside this extent."""
        return (
            self.min_lon <= point.lon <= self.max_lon and self.min_lat <= point.lat <= self.max_lat
        )

    @property
    def wkt(self) -> str:
        """Well-known text polygon, closed ring, counter-clockwise."""
        return (
            f"POLYGON(({self.min_lon} {self.min_lat}, {self.max_lon} {self.min_lat}, "
            f"{self.max_lon} {self.max_lat}, {self.min_lon} {self.max_lat}, "
            f"{self.min_lon} {self.min_lat}))"
        )


SRI_LANKA_BBOX: Final = BoundingBox(
    min_lon=LK_BBOX_MIN_LON,
    min_lat=LK_BBOX_MIN_LAT,
    max_lon=LK_BBOX_MAX_LON,
    max_lat=LK_BBOX_MAX_LAT,
)


def in_sri_lanka(lon: float, lat: float) -> bool:
    """Whether a coordinate falls inside the Sri Lanka bounding box."""
    return LK_BBOX_MIN_LON <= lon <= LK_BBOX_MAX_LON and LK_BBOX_MIN_LAT <= lat <= LK_BBOX_MAX_LAT


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance between two WGS 84 coordinates, in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
