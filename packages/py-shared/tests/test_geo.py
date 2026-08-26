import pytest
from pydantic import ValidationError
from sarana_shared.domain.geo import LocatedPoint, Point, geodesic_distance_m


def test_gps_point_requires_accuracy() -> None:
    with pytest.raises(ValidationError, match="accuracy_m"):
        LocatedPoint(point=Point(lat=6.9, lng=79.8), source="gps", accuracy_m=None)


def test_manual_point_never_needs_accuracy_but_is_dispatchable() -> None:
    located = LocatedPoint(point=Point(lat=6.9, lng=79.8), source="manual", accuracy_m=None)
    assert located.is_dispatchable()


def test_gps_point_dispatchable_only_within_threshold() -> None:
    precise = LocatedPoint(point=Point(lat=6.9, lng=79.8), source="gps", accuracy_m=30)
    imprecise = LocatedPoint(point=Point(lat=6.9, lng=79.8), source="gps", accuracy_m=500)
    assert precise.is_dispatchable()
    assert not imprecise.is_dispatchable()


def test_inferred_point_with_no_accuracy_is_not_dispatchable() -> None:
    located = LocatedPoint(point=Point(lat=6.9, lng=79.8), source="inferred", accuracy_m=None)
    assert not located.is_dispatchable()


def test_geodesic_distance_known_points() -> None:
    # Colombo Fort to Kandy city centre — roughly 90-100km as the crow flies.
    colombo = Point(lat=6.9344, lng=79.8428)
    kandy = Point(lat=7.2906, lng=80.6337)
    distance = geodesic_distance_m(colombo, kandy)
    assert 85_000 < distance < 100_000


def test_geodesic_distance_zero_for_same_point() -> None:
    p = Point(lat=6.9, lng=79.8)
    assert geodesic_distance_m(p, p) == pytest.approx(0.0, abs=1e-6)
