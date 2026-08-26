"""Coordinates, provenance and the dispatch trust rule."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sarana_shared.domain.geo import (
    SRID_WGS84,
    GeoPoint,
    PointSource,
    in_sri_lanka,
)

# Batticaloa town, on the east coast where Ditwah made landfall.
BATTICALOA_LON, BATTICALOA_LAT = 81.7000, 7.7167


def test_srid_is_wgs84_for_storage_and_api() -> None:
    assert SRID_WGS84 == 4326


def test_a_point_carries_accuracy_and_source() -> None:
    point = GeoPoint(
        lon=BATTICALOA_LON, lat=BATTICALOA_LAT, accuracy_m=12.0, source=PointSource.GPS
    )

    assert point.trusted_for_dispatch
    assert point.wkt == f"POINT({BATTICALOA_LON} {BATTICALOA_LAT})"


def test_a_cell_tower_fix_is_not_trusted_for_dispatch() -> None:
    """A 1.5km circle locates a village, not a household. Route it to an operator."""
    point = GeoPoint.from_source(BATTICALOA_LON, BATTICALOA_LAT, PointSource.CELL)

    assert not point.trusted_for_dispatch


def test_a_point_cannot_exist_without_an_accuracy() -> None:
    with pytest.raises(ValidationError):
        GeoPoint(lon=BATTICALOA_LON, lat=BATTICALOA_LAT, source=PointSource.GPS)  # type: ignore[call-arg]  # the point of the test


def test_swapped_coordinates_are_caught_and_named() -> None:
    """The most common inbound data error, and the easiest to detect."""
    with pytest.raises(ValidationError, match="swapped"):
        GeoPoint(
            lon=BATTICALOA_LAT, lat=BATTICALOA_LON, accuracy_m=10.0, source=PointSource.GPS
        )


def test_a_point_outside_sri_lanka_is_a_data_error() -> None:
    with pytest.raises(ValidationError, match="outside the Sri Lanka"):
        GeoPoint(lon=0.0, lat=0.0, accuracy_m=10.0, source=PointSource.MANUAL)


def test_bounding_box_covers_the_island() -> None:
    assert in_sri_lanka(79.8612, 6.9271)  # Colombo
    assert in_sri_lanka(81.2152, 8.5874)  # Trincomalee
    assert not in_sri_lanka(77.5946, 12.9716)  # Bengaluru


def test_distance_between_colombo_and_batticaloa_is_plausible() -> None:
    colombo = GeoPoint(lon=79.8612, lat=6.9271, accuracy_m=10.0, source=PointSource.GPS)
    batticaloa = GeoPoint(
        lon=BATTICALOA_LON, lat=BATTICALOA_LAT, accuracy_m=10.0, source=PointSource.GPS
    )

    # Great-circle, roughly 210km across the island.
    assert 200_000 < colombo.distance_to(batticaloa) < 225_000
