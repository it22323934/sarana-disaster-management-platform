"""Geospatial types: SRID constants, Point/Polygon wrappers, and location accuracy/source.

Per docs/build-prompts/02-conventions.md: SRID 4326 for storage and API, project to
5235 (Sri Lanka Grid 1999) only for distance/area maths. Every point carries accuracy_m
and source — a point with no accuracy is not trusted for dispatch.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

SRID_WGS84 = 4326
"""Storage and API SRID — plain lat/lng, what every service persists and returns."""

SRID_SL_GRID_1999 = 5235
"""Sri Lanka Grid 1999 — project into this only when doing distance/area maths, never
for storage. See geodesic_distance_m for the case that matters in practice (dedup
radius, geofencing) without needing a full projection library at scaffold stage."""

LocationSource = Literal["gps", "cell", "manual", "inferred"]


class Point(BaseModel):
    """A WGS84 point. `lat`/`lng`, not `x`/`y` — this is a place, not a plot coordinate."""

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)

    def as_geojson(self) -> dict[str, Any]:
        return {"type": "Point", "coordinates": [self.lng, self.lat]}


class LocatedPoint(BaseModel):
    """A point that also carries the accuracy/source pair the conventions require.
    Nothing in the incident or dispatch pipeline should accept a bare Point — this is
    the type that actually flows through those APIs."""

    point: Point
    accuracy_m: float | None = Field(default=None, ge=0)
    source: LocationSource

    @model_validator(mode="after")
    def _gps_should_have_accuracy(self) -> LocatedPoint:
        if self.source == "gps" and self.accuracy_m is None:
            raise ValueError("A GPS-sourced point must carry accuracy_m")
        return self

    def is_dispatchable(self, *, max_accuracy_m: float = 100.0) -> bool:
        """Whether this point is trustworthy enough to route a responder to directly,
        vs. falling back to GN-division-level dispatch (docs/build-prompts/15)."""
        if self.source == "manual":
            return True  # a human placed the pin deliberately
        if self.accuracy_m is None:
            return False
        return self.accuracy_m <= max_accuracy_m


class MultiPolygon(BaseModel):
    """GN/DS/District boundary geometry. Rings are [ [ [lng, lat], ... ], ... ] per
    polygon, matching GeoJSON MultiPolygon coordinate nesting exactly."""

    rings: list[list[list[tuple[float, float]]]]

    def as_geojson(self) -> dict[str, Any]:
        return {"type": "MultiPolygon", "coordinates": self.rings}


_EARTH_RADIUS_M = 6_371_000.0


def geodesic_distance_m(a: Point, b: Point) -> float:
    """Haversine great-circle distance in metres. Good enough for the ~300m dedup radius
    and similar short-range checks; anything needing true planar accuracy should project
    through SRID_SL_GRID_1999 in PostGIS instead of this function."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlng = math.radians(b.lng - a.lng)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(h))
