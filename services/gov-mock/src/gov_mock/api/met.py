"""Department of Meteorology routes.

The warnings feed is XML because the Department's is. Observations and the forecast are
JSON. That inconsistency is not an oversight to tidy up — it is what integrating with a
real agency looks like, and a platform that has only ever parsed its own JSON discovers it
at the worst time.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final
from xml.etree.ElementTree import Element, SubElement

from fastapi import APIRouter, HTTPException, Query

from gov_mock.api.deps import (
    SimulatedHoursDep,
    SimulatedNowDep,
    StateDep,
    mock_json,
    mock_xml,
)
from gov_mock.data import met as met_data
from gov_mock.data.districts import BY_CODE, EAST_COAST_DISTRICTS

router = APIRouter(prefix="/met/v1", tags=["met"])

# When each warning level comes into force, in hours past landfall, and when the whole
# sequence stands down. A warning that never expires is one nobody trusts the second time.
_LEVEL_SCHEDULE: Final[tuple[tuple[float, str], ...]] = (
    (-72.0, "Yellow"),
    (-36.0, "Amber"),
    (-12.0, "Red"),
)
_STAND_DOWN_HOUR: Final = 48.0

# How long a bulletin is valid for once issued.
_VALIDITY_HOURS: Final = 24

_HEADLINES: Final[dict[str, str]] = {
    "Yellow": "Heavy rain advisory for the Eastern and Uva provinces",
    "Amber": "Heavy rain and strong wind warning; localised flooding expected",
    "Red": "Severe weather warning: destructive wind, storm surge and major flooding",
}

# Forecast windows the Department publishes. A request for any other window is refused
# rather than interpolated: a 17-hour forecast nobody issued is a number with no source.
FORECAST_WINDOWS: Final[frozenset[int]] = frozenset({6, 12, 24, 48, 72})

# Half-width of the confidence band, as a share of the point forecast. Wider further out,
# because it is. A forecast published without a band invites a decision it cannot support.
_BAND_AT_6H: Final = 0.15
_BAND_AT_72H: Final = 0.55


def _current_level(hours: float) -> str | None:
    """The warning level in force at this hour, or None if none is."""
    if hours >= _STAND_DOWN_HOUR:
        return None
    level: str | None = None
    for from_hour, name in _LEVEL_SCHEDULE:
        if hours >= from_hour:
            level = name
    return level


def _warnings(now: datetime, hours: float) -> list[dict[str, Any]]:
    """Every warning in force, as plain dicts ready to render as XML."""
    level = _current_level(hours)
    if level is None:
        return []

    # Issued at the moment the level came into force, not now. A bulletin timestamped
    # "just now" every time it is fetched would make it impossible to tell a reissued
    # warning from a standing one.
    issued_hour = max(
        from_hour for from_hour, name in _LEVEL_SCHEDULE if name == level and hours >= from_hour
    )
    issued_at = now - timedelta(hours=hours - issued_hour)

    districts = sorted(EAST_COAST_DISTRICTS) if level == "Yellow" else sorted(BY_CODE)
    return [
        {
            "id": f"MET-{issued_at:%Y%m%d}-{level.upper()}-001",
            "level": level,
            "hazard": "CYCLONE",
            "headline": _HEADLINES[level],
            "issuedAt": issued_at.isoformat(),
            "validUntil": (issued_at + timedelta(hours=_VALIDITY_HOURS)).isoformat(),
            "districts": districts,
        }
    ]


def _warning_element(parent: Element | None, warning: dict[str, Any]) -> Element:
    """Render one warning as XML."""
    element = Element("warning") if parent is None else SubElement(parent, "warning")
    for tag in ("id", "level", "hazard", "headline", "issuedAt", "validUntil"):
        SubElement(element, tag).text = str(warning[tag])
    districts = SubElement(element, "districts")
    for code in warning["districts"]:
        SubElement(districts, "district").text = code
    return element


@router.get("/warnings", summary="Current warnings (XML)")
def warnings(now: SimulatedNowDep, hours: SimulatedHoursDep) -> Any:
    """Every warning currently in force. XML, as the Department publishes it."""
    root = Element("warnings")
    for warning in _warnings(now, hours):
        _warning_element(root, warning)
    return mock_xml(root)


@router.get("/warnings/{warning_id}", summary="One warning by id (XML)")
def warning(warning_id: str, now: SimulatedNowDep, hours: SimulatedHoursDep) -> Any:
    """One warning. 404 if it is not in force — an expired warning is not retrievable.

    That is the Department's behaviour and it is worth preserving: a consumer that caches
    a warning id and refetches it after stand-down must handle the miss rather than
    receiving a warning that is no longer true.
    """
    found = next((w for w in _warnings(now, hours) if w["id"] == warning_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail="No warning with that id is in force")
    return mock_xml(_warning_element(None, found))


@router.get("/observations", summary="Station rainfall observations")
def observations(
    state: StateDep,
    now: SimulatedNowDep,
    hours: SimulatedHoursDep,
    station: str | None = Query(default=None, description="Station id, e.g. MET-020"),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None, alias="to"),
) -> Any:
    """Current readings from the observing network.

    `from` and `to` are accepted and deliberately ignored: this mock holds no history, and
    a window it silently reinterpreted as "now" would be worse than one it visibly does not
    implement. The response says so in `window_supported` rather than letting a caller
    believe it got a time series.
    """
    stations = met_data.STATIONS
    if station is not None:
        stations = tuple(s for s in stations if s.station_id == station)
        if not stations:
            raise HTTPException(status_code=404, detail="No such station")

    rows = []
    for entry in stations:
        reporting = met_data.is_reporting(entry, hours_since_landfall=hours, seed=state.seed)
        rows.append(
            {
                "station_id": entry.station_id,
                "station_name": entry.name,
                "district_code": entry.district_code,
                "lon": entry.lon,
                "lat": entry.lat,
                "observed_at": now.isoformat(),
                # A station that is down reports 0.0 alongside `reporting: false`. The
                # flag is what a consumer must branch on: a silent gauge and a dry one
                # produce the same number, and treating them alike understates exactly the
                # districts in the worst trouble.
                "rainfall_mm_24h": (
                    met_data.rainfall_mm_24h(entry, hours_since_landfall=hours, seed=state.seed)
                    if reporting
                    else 0.0
                ),
                "reporting": reporting,
            }
        )

    return mock_json(
        {
            "observations": rows,
            "window_supported": False,
            "note": "This mock serves current readings only; from/to are ignored.",
        }
    )


@router.get("/forecast/rainfall", summary="Rainfall forecast for a district")
def rainfall_forecast(
    state: StateDep,
    now: SimulatedNowDep,
    hours: SimulatedHoursDep,
    district: str = Query(description="District code, e.g. LK-51"),
    forecast_hours: int = Query(default=24, alias="hours"),
) -> Any:
    """Expected rainfall over a forward window, with a confidence band."""
    if district not in BY_CODE:
        raise HTTPException(status_code=404, detail="No such district")
    if forecast_hours not in FORECAST_WINDOWS:
        raise HTTPException(
            status_code=422,
            detail=(
                "The Department publishes forecasts for "
                f"{sorted(FORECAST_WINDOWS)} hour windows only."
            ),
        )

    # The forecast is the modelled rainfall at the midpoint of the window, which is what a
    # 24-hour accumulation over that window works out at.
    midpoint = hours + forecast_hours / 2
    expected = met_data.district_rainfall_mm(
        district, hours_since_landfall=midpoint, seed=state.seed
    )

    span = _BAND_AT_6H + (_BAND_AT_72H - _BAND_AT_6H) * (forecast_hours - 6) / (72 - 6)
    return mock_json(
        {
            "forecast": {
                "district_code": district,
                "hours": forecast_hours,
                "expected_mm": expected,
                "confidence_low_mm": round(max(0.0, expected * (1 - span)), 1),
                "confidence_high_mm": round(expected * (1 + span), 1),
                "issued_at": now.isoformat(),
            }
        }
    )
