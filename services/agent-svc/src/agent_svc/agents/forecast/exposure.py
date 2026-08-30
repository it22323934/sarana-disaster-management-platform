"""What the scoring engine knows about one GN division, and where the numbers come from.

Two things live here: the per-division attributes the engine reads, and the rainfall
downscaling that turns station readings into a number for a division that has no station in
it — which is most of them, since there are 40 stations and 14,022 divisions.

## The attribute directions, which are decisions and not facts

Two of these columns arrived in the file 04 schema with a range and no stated direction, and
an engine that guesses silently is an engine nobody can audit. They are fixed here, once:

**`landslide_zone` 1-4, higher is more hazardous.** Not a decision — NBRO's own zonation
and `sarana_shared.adapters.gov.nbro.LandslideZone` both say so. Worth stating because
build file 13's own trigger example reads `landslide_zone <= 2` for a high-hazard rule,
which is backwards. The adapter and the schema win.

**`road_access_class` 1-4, higher is worse access.** A decision. Nothing in the schema or
the seed says which way it runs, so it is fixed here to match `landslide_zone` — higher is
worse throughout — because two adjacent columns that count in opposite directions is a bug
waiting in whichever one somebody reads second.

**`flood_return_period_m` is months between floods, lower is worse.** A division that
floods every 5 months is in more trouble than one that floods every 45. The seed generates
5-49, which only makes sense as months.

## The one thing that is not here

Build file 13 lists elevation and distance to the nearest waterway among the inputs.
`admin.gn_division` carries neither, and inventing them from the centroid would produce a
number that looks like terrain data and is not. They are absent, the engine does not
pretend otherwise, and adding them is a schema change plus a real elevation source.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

# How far away a station can be and still say anything useful about a division, in degrees.
# Roughly 165 km at Sri Lanka's latitude. Beyond it the inverse-distance weight is tiny
# anyway; the cutoff exists so a division on the far side of the island is not nudged by a
# station it shares no weather with, and so the fallback below is reachable and tested.
MAX_STATION_DISTANCE_DEG: Final = 1.5

# The exponent on inverse distance. 2 is the usual choice for rainfall: it weights the
# nearest gauge strongly without letting a single station 3 km away completely silence one
# 12 km away, which a higher power does.
IDW_POWER: Final = 2.0

# Below this the station is treated as being *at* the division and takes the whole weight.
# Guards the division by zero, and is small enough (~55 m) that it only fires when a
# station really is inside the division.
COINCIDENT_DEG: Final = 0.0005


@dataclass(frozen=True, slots=True)
class DivisionExposure:
    """One GN division's static attributes, as the engine reads them.

    Everything here comes from `admin.gn_division` through core-api. None of it is personal
    data: counts and percentages over a division, never a household or a person.
    """

    gn_division_id: str
    gn_division_code: str
    ds_division_code: str
    district_code: str
    centroid_lon: float
    centroid_lat: float

    household_count: int = 0
    population: int = 0

    # Every one of these is nullable in the schema, and a division with no survey data is a
    # real state rather than an error. The engine treats a missing attribute as "unknown"
    # and says so in the drivers, instead of substituting a default that would read as a
    # measurement.
    landslide_zone: int | None = None
    flood_return_period_m: int | None = None
    road_access_class: int | None = None
    cell_coverage_pct: float | None = None
    elderly_pct: float | None = None
    under5_pct: float | None = None

    @property
    def elderly_households(self) -> int:
        """Households likely to contain someone over 70.

        A share applied to a count, which is what the census gives us. Reported as a
        denominator for planning, never as a list of people — the platform does not hold
        who is old, and it should not learn.
        """
        if self.elderly_pct is None:
            return 0
        return round(self.household_count * self.elderly_pct / 100.0)

    @property
    def under5_households(self) -> int:
        if self.under5_pct is None:
            return 0
        return round(self.household_count * self.under5_pct / 100.0)


@dataclass(frozen=True, slots=True)
class StationReading:
    """One Met station's rolling 24-hour rainfall, at a place.

    `reporting` is carried rather than filtered out at the source because a station that
    has lost power reads the same as a station recording no rain, and treating them alike
    understates exactly the districts in the worst trouble. Non-reporting stations are
    dropped by `rainfall_at`; the count of them is what the confidence penalty reads.
    """

    station_id: str
    lon: float
    lat: float
    rainfall_mm_24h: float
    reporting: bool = True


@dataclass(frozen=True, slots=True)
class DivisionRainfall:
    """What the engine believes has fallen and will fall on one division.

    `observed_24h` is measured, interpolated from gauges. `expected_24h`/`48h`/`72h` are
    forecast: what the Department expects to fall over the next window, downscaled to this
    division. The distinction is load-bearing — a forecast agent that scores on what has
    already fallen has no lead time and is a reporting tool.
    """

    observed_24h: float
    expected_24h: float
    expected_48h: float
    expected_72h: float

    # Gauges within range that had nothing to say. Drives the confidence penalty: a
    # division interpolated from two working stations out of six deserves a lower
    # confidence than one surrounded by a healthy network, and hiding that difference is
    # how a forecast acquires authority it has not earned.
    stations_used: int = 0
    stations_silent: int = 0

    def peak(self) -> tuple[float, int]:
        """The worst 24-hour accumulation in view, and how many hours out it is.

        **Every one of these four numbers is a 24-hour accumulation**, and so is every NBRO
        threshold. The observation is the last 24 hours; each forecast is what the
        Department expects a 24-hour gauge to read at the midpoint of that window. So the
        comparison against a threshold is like for like, and the answer to "when?" is the
        window that peaked.

        Adding them together instead — observed plus forecast — would produce a two-day
        total compared against a one-day threshold, which crosses every zone's evacuate
        level a day early and looks, from the outside, exactly like a working early
        warning. That is the most dangerous kind of wrong this engine could be.

        The peak rather than the nearest window because a forecast is a statement about
        what is coming: a division that is dry now and will take 180 mm the day after
        tomorrow needs the warning now, which is the entire point of lead time.
        """
        windows = (
            (self.observed_24h, 0),
            (self.expected_24h, 24),
            (self.expected_48h, 48),
            (self.expected_72h, 72),
        )
        return max(windows, key=lambda pair: pair[0])


def distance_deg(lon_a: float, lat_a: float, lon_b: float, lat_b: float) -> float:
    """Planar distance in degrees.

    Not a geodesic. Over the ~450 km of Sri Lanka the error against a proper great-circle
    distance is well under the spacing between rain gauges, and it is the *ratio* of
    distances that sets the weights here, not their absolute size. A geodesic would be more
    correct and would not move a single forecast.
    """
    return math.hypot(lon_a - lon_b, lat_a - lat_b)


def rainfall_at(
    lon: float,
    lat: float,
    readings: list[StationReading],
    *,
    max_distance_deg: float = MAX_STATION_DISTANCE_DEG,
    power: float = IDW_POWER,
) -> tuple[float, int, int]:
    """Interpolate rainfall at a point. Returns (mm, stations used, stations silent).

    Inverse-distance weighted over the reporting stations within range, which is what build
    file 13 specifies and what the Department's own products use. A station inside the
    division takes the whole weight.

    Returns 0.0 with a zero count when no station is in range, rather than falling back to a
    national average. A national average is the exact failure the Ditwah mock was reshaped
    to prevent: it makes every division look identical and lets targeting logic appear to
    work while doing nothing. A division with no gauge nearby has no rainfall estimate, the
    confidence says so, and that is the honest answer.
    """
    nearby = [
        (reading, distance_deg(lon, lat, reading.lon, reading.lat))
        for reading in readings
        if distance_deg(lon, lat, reading.lon, reading.lat) <= max_distance_deg
    ]
    silent = sum(1 for reading, _ in nearby if not reading.reporting)
    usable = [(reading, d) for reading, d in nearby if reading.reporting]

    if not usable:
        return 0.0, 0, silent

    for reading, d in usable:
        if d <= COINCIDENT_DEG:
            return reading.rainfall_mm_24h, 1, silent

    weights = [1.0 / (d**power) for _, d in usable]
    total = sum(weights)
    weighted = sum(
        reading.rainfall_mm_24h * weight
        for (reading, _), weight in zip(usable, weights, strict=True)
    )
    return round(weighted / total, 1), len(usable), silent


def downscale(
    district_expected_mm: float, division_observed: float, district_observed: float
) -> float:
    """Scale a district-wide forecast to one division inside it.

    The Department forecasts by district; the decision is per division, and a district is
    large enough that its wet edge and its dry edge are different places. The ratio of what
    is currently falling on the division to what is falling across the district is the only
    per-division signal available, so it is what the forecast is scaled by.

    **This is a crude downscaling and it should be labelled as one wherever it is shown.**
    It assumes the spatial pattern of the next 24 hours looks like the pattern of the last
    24, which is roughly true for a system tracking steadily across the island and wrong
    for a storm that turns. A real one needs gridded forecast data, which the Department
    does not publish.

    Clamped either side so a single anomalous gauge cannot triple a division's forecast or
    zero it out.
    """
    if district_observed <= 0.0:
        return district_expected_mm
    ratio = min(
        MAX_DOWNSCALE_RATIO, max(MIN_DOWNSCALE_RATIO, division_observed / district_observed)
    )
    return round(district_expected_mm * ratio, 1)


# How far a division's forecast may depart from its district's. A gauge reading three times
# the district mean is far more likely to be a blocked funnel or a tipping-bucket fault than
# a division about to receive three times the rain, and a forecast that follows it produces
# an evacuation advisory for one division and nothing for its neighbours.
MIN_DOWNSCALE_RATIO: Final = 0.5
MAX_DOWNSCALE_RATIO: Final = 1.8
