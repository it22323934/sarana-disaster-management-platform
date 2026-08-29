"""Synthetic weather: 40 stations, and a Ditwah-shaped rainfall curve through them.

**Station names are real; every reading is invented.** The Department of Meteorology
operates observing stations at these places, and the list uses their real names and
approximate coordinates because a demo that resolves rainfall to a town nobody has heard
of is harder to sanity-check. The millimetres are generated.

The curve is the interesting part. Rainfall is a function of two things:

  **How far past landfall the simulation is.** It builds from about T-72h, peaks in the
  twelve hours around landfall, and decays over the following three days. That shape is
  what makes the whole platform exercisable: the Forecast agent has a rising signal to act
  on before there is any damage to respond to, which is the entire point of anticipatory
  action.

  **Where the station is.** Ditwah came ashore on the east coast. The east is hit hardest,
  the central highlands catch orographic rain on the way through, and the west coast gets
  comparatively little. A uniform national figure would let the targeting logic look
  correct while doing nothing.

Everything here is a pure function of `(seed, station, hour)`. No wall clock, no live
randomness — the same simulated hour produces the same reading on every machine and every
replay.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Final

from gov_mock.data.districts import DISTRICTS, District


@dataclass(frozen=True, slots=True)
class Station:
    """One observing station."""

    station_id: str
    name: str
    district_code: str
    lon: float
    lat: float
    # Metres above sea level. Highland stations catch orographic rainfall, which is why
    # Nuwara Eliya can record more than the coast the storm actually crossed.
    elevation_m: int


# Forty stations. Real names, approximate coordinates.
STATIONS: Final[tuple[Station, ...]] = (
    Station("MET-001", "Colombo", "LK-11", 79.8612, 6.9271, 7),
    Station("MET-002", "Ratmalana", "LK-11", 79.8861, 6.8214, 6),
    Station("MET-003", "Katunayake", "LK-12", 79.8841, 7.1697, 9),
    Station("MET-004", "Gampaha", "LK-12", 79.9990, 7.0897, 15),
    Station("MET-005", "Kalutara", "LK-13", 79.9607, 6.5854, 5),
    Station("MET-006", "Kandy", "LK-21", 80.6337, 7.2906, 500),
    Station("MET-007", "Katugastota", "LK-21", 80.6167, 7.3333, 470),
    Station("MET-008", "Matale", "LK-22", 80.6234, 7.4675, 364),
    Station("MET-009", "Nuwara Eliya", "LK-23", 80.7891, 6.9497, 1868),
    Station("MET-010", "Rahangala", "LK-23", 80.8500, 6.8167, 1300),
    Station("MET-011", "Galle", "LK-31", 80.2210, 6.0535, 13),
    Station("MET-012", "Deniyaya", "LK-31", 80.5556, 6.3389, 396),
    Station("MET-013", "Matara", "LK-32", 80.5353, 5.9549, 4),
    Station("MET-014", "Hambantota", "LK-33", 81.1185, 6.1241, 15),
    Station("MET-015", "Jaffna", "LK-41", 80.0255, 9.6615, 5),
    Station("MET-016", "Kilinochchi", "LK-42", 80.4037, 9.3803, 20),
    Station("MET-017", "Mannar", "LK-43", 79.9045, 8.9810, 3),
    Station("MET-018", "Vavuniya", "LK-44", 80.4982, 8.7514, 91),
    Station("MET-019", "Mullaitivu", "LK-45", 80.8142, 9.2671, 4),
    Station("MET-020", "Batticaloa", "LK-51", 81.6924, 7.7170, 5),
    Station("MET-021", "Valaichchenai", "LK-51", 81.5333, 7.9167, 6),
    Station("MET-022", "Ampara", "LK-52", 81.6747, 7.2911, 34),
    Station("MET-023", "Pottuvil", "LK-52", 81.8333, 6.8750, 5),
    Station("MET-024", "Trincomalee", "LK-53", 81.2335, 8.5874, 6),
    Station("MET-025", "Kantale", "LK-53", 81.0000, 8.3667, 30),
    Station("MET-026", "Kurunegala", "LK-61", 80.3609, 7.4818, 116),
    Station("MET-027", "Puttalam", "LK-62", 79.8283, 8.0362, 4),
    Station("MET-028", "Anuradhapura", "LK-71", 80.4037, 8.3114, 89),
    Station("MET-029", "Maha Illuppallama", "LK-71", 80.4667, 8.1167, 155),
    Station("MET-030", "Polonnaruwa", "LK-72", 81.0188, 7.9403, 55),
    Station("MET-031", "Badulla", "LK-81", 81.0557, 6.9895, 680),
    Station("MET-032", "Bandarawela", "LK-81", 80.9833, 6.8333, 1230),
    Station("MET-033", "Diyatalawa", "LK-81", 80.9667, 6.8167, 1250),
    Station("MET-034", "Moneragala", "LK-82", 81.3487, 6.8728, 155),
    Station("MET-035", "Wellawaya", "LK-82", 81.1000, 6.7333, 100),
    Station("MET-036", "Ratnapura", "LK-91", 80.4037, 6.6828, 34),
    Station("MET-037", "Balangoda", "LK-91", 80.6833, 6.6500, 613),
    Station("MET-038", "Kegalle", "LK-92", 80.3464, 7.2513, 156),
    Station("MET-039", "Nawalapitiya", "LK-92", 80.5333, 7.0500, 655),
    Station("MET-040", "Mahailluppallama Tank", "LK-72", 80.9000, 8.0500, 60),
)

BY_ID: Final[dict[str, Station]] = {station.station_id: station for station in STATIONS}

# District centres, for the case where a district has no station reporting.
BY_DISTRICT: Final[dict[str, District]] = {d.code: d for d in DISTRICTS}

# The peak of the curve, in hours past landfall. Not zero: the heaviest rain from a system
# like Ditwah arrives with and just behind the centre, not ahead of it.
PEAK_HOUR: Final = 6.0

# How wide the peak is, in hours. A larger number is a slower, longer soaking - which is
# what actually causes landslides, as opposed to the intensity that causes flash floods.
SPREAD_HOURS: Final = 30.0

# Millimetres per 24 hours at the peak, on the track itself.
BASE_PEAK_MM: Final = 260.0

# Where Ditwah came ashore, and how fast the rain falls off away from it.
#
# This is the single most consequential shape in the mock. Without it every district in the
# country records the same rainfall, every hazard zone crosses its threshold at the same
# moment, and NBRO issues twenty-five identical bulletins - which looks like a working
# escalation and is actually a national deluge that no targeting logic can be tested
# against.
#
# The longitude spread is tighter than the latitude spread because the system tracked
# roughly north-west along the coast: rain reaches a long way up and down the eastern
# seaboard and a much shorter way inland.
TRACK_LON: Final = 81.70
TRACK_LAT: Final = 7.70
TRACK_SPREAD_LON: Final = 1.30
TRACK_SPREAD_LAT: Final = 1.80

# What a location gets with no help from the storm at all. Not zero: the north-east
# monsoon runs across the whole island, and a west-coast district modelled at zero during a
# cyclone would read as a data gap rather than as a district that is merely wet.
FAR_FIELD_SHARE: Final = 0.15

# The highlands catch orographic rain on the way through, which is why Nuwara Eliya can
# record more than the coast the storm actually crossed.
HIGHLAND_FACTOR: Final = 1.35
HIGHLAND_ELEVATION_M: Final = 900

# Background rainfall outside the event, in mm/24h. Never zero: the north-east monsoon is
# running, and a curve that starts at zero makes any non-zero reading look like the storm.
BASELINE_MM: Final = 4.0

# One station in twenty-five is offline at any moment, and more as the event peaks. A gap
# is reported as a gap, never as a zero - a station that has lost power reads the same as
# a station recording no rain, and treating them alike understates exactly the districts
# in the worst trouble.
BASE_OUTAGE_RATE: Final = 0.04
PEAK_OUTAGE_RATE: Final = 0.22


def exposure_at(lon: float, lat: float) -> float:
    """How exposed a point is to the storm, from `FAR_FIELD_SHARE` up to 1.0.

    A two-dimensional Gaussian around the landfall point. Deliberately a plain shape
    rather than a track integral: the property that has to hold is that the east coast is
    hit hard, the central highlands catch a good deal on the way through, and the west
    coast does not - and a more elaborate model would obscure that rather than improve it.
    """
    dlon = (lon - TRACK_LON) / TRACK_SPREAD_LON
    dlat = (lat - TRACK_LAT) / TRACK_SPREAD_LAT
    return FAR_FIELD_SHARE + (1.0 - FAR_FIELD_SHARE) * math.exp(-(dlon**2 + dlat**2))


def _station_factor(station: Station) -> float:
    """How hard this station is hit, relative to a station on the track itself."""
    factor = exposure_at(station.lon, station.lat)
    if station.elevation_m >= HIGHLAND_ELEVATION_M:
        factor *= HIGHLAND_FACTOR
    return factor


def _intensity(hours_since_landfall: float) -> float:
    """The storm's national intensity at an hour, from 0.0 to 1.0.

    A Gaussian around `PEAK_HOUR`. Chosen over a sharper shape because the decision this
    drives is a cumulative-rainfall threshold, and a curve with a narrow spike crosses a
    24-hour threshold in a way that depends entirely on where the sampling lands.
    """
    return math.exp(-(((hours_since_landfall - PEAK_HOUR) / SPREAD_HOURS) ** 2))


def _rng_for(seed: int, station_id: str, hour_bucket: int) -> random.Random:
    """A generator keyed to one station and one hour.

    Keying on the hour bucket rather than drawing from a running stream is what makes a
    reading reproducible: asking for T+6h twice, or after a restart, gives the same
    millimetres. A shared stream would make every reading depend on how many other
    requests happened first.
    """
    return random.Random((seed, station_id, hour_bucket).__hash__())  # noqa: S311 - synthetic


def rainfall_mm_24h(station: Station, *, hours_since_landfall: float, seed: int) -> float:
    """Rolling 24-hour rainfall at one station, in millimetres.

    Deterministic in `(seed, station, hour)`. Rounded to one decimal place, which is the
    precision the Department publishes at — reporting more would imply an instrument
    accuracy that does not exist.
    """
    hour_bucket = int(hours_since_landfall)
    rng = _rng_for(seed, station.station_id, hour_bucket)

    peak = BASE_PEAK_MM * _station_factor(station)
    modelled = BASELINE_MM + peak * _intensity(hours_since_landfall)

    # Per-station scatter. Real gauges a few kilometres apart disagree by a good deal, and
    # a perfectly smooth field would let an agent key off a precision it will never have.
    scatter = rng.uniform(0.82, 1.18)
    return round(max(0.0, modelled * scatter), 1)


def is_reporting(station: Station, *, hours_since_landfall: float, seed: int) -> bool:
    """Whether this station is sending data at this hour.

    Outages rise with the storm, because that is when the power goes. The station most
    likely to fall silent is the one in the district you most need a reading from.
    """
    hour_bucket = int(hours_since_landfall)
    rng = _rng_for(seed, f"{station.station_id}:up", hour_bucket)
    intensity = _intensity(hours_since_landfall)
    outage_rate = BASE_OUTAGE_RATE + (PEAK_OUTAGE_RATE - BASE_OUTAGE_RATE) * intensity
    return rng.random() > outage_rate


def district_rainfall_mm(district_code: str, *, hours_since_landfall: float, seed: int) -> float:
    """Mean 24-hour rainfall across a district's reporting stations.

    Falls back to the modelled national figure for a district with no station of its own,
    rather than returning zero. Zero rainfall in a district during a cyclone is a claim
    nobody should make from an absence of instruments.
    """
    stations = [s for s in STATIONS if s.district_code == district_code]
    reporting = [
        s for s in stations if is_reporting(s, hours_since_landfall=hours_since_landfall, seed=seed)
    ]
    if not reporting:
        # No instrument is reporting here. Fall back to the modelled figure for the
        # district's own position rather than a national average: zero rainfall in a
        # district during a cyclone is a claim nobody should make from an absence of
        # instruments, and a national mean is a claim about somewhere else.
        district = BY_DISTRICT.get(district_code)
        exposure = (
            exposure_at(district.lon, district.lat) if district is not None else FAR_FIELD_SHARE
        )
        return round(BASELINE_MM + BASE_PEAK_MM * exposure * _intensity(hours_since_landfall), 1)

    total = sum(
        rainfall_mm_24h(s, hours_since_landfall=hours_since_landfall, seed=seed) for s in reporting
    )
    return round(total / len(reporting), 1)
