"""Synthetic DMC data: safety locations, occupancy over time, situation reports.

280 safety locations, matching the peak figure reported during Cyclone Ditwah. They are
schools, temples, kovils, mosques and community halls, because that is what a safety
location in Sri Lanka actually is — a building with a roof that is not being used for
anything else this week. Names are generated; none is a real institution.

**Occupancy fills, and it overflows.** Locations in the affected districts fill from around
landfall and keep filling for two days. Some go past their rated capacity, because they do:
a family that has walked to the nearest school is not turned away because a spreadsheet
says it is full. Anything consuming this has to handle occupancy above capacity, which is
why `SafetyLocation.spare_capacity` floors at zero and `is_over_capacity` exists as its own
question.

Occupancy written through `POST /dmc/v1/shelters/{id}/occupancy` overrides the modelled
curve for that location from then on. A real headcount beats a model, which is the entire
reason the write exists.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from gov_mock.data.districts import DISTRICTS, District, ds_codes
from gov_mock.data.met import exposure_at

TOTAL_LOCATIONS: Final = 280

# How exposed a district has to be before the DMC opens safety locations in it.
#
# Derived from the same storm model the rainfall comes from, rather than listed by hand.
# A hand-written list drifts: move the track a tenth of a degree and the shelters fill in
# districts the rain never reached, or stay empty in ones it drowned. One story, one
# source - a district's shelters fill because the model says it was hit.
EVACUATION_EXPOSURE_THRESHOLD: Final = 0.45

AFFECTED_DISTRICTS: Final[frozenset[str]] = frozenset(
    district.code
    for district in DISTRICTS
    if exposure_at(district.lon, district.lat) >= EVACUATION_EXPOSURE_THRESHOLD
)

# Buildings pressed into service, with the capacity each typically offers.
_VENUE_KINDS: Final[tuple[tuple[str, int, int], ...]] = (
    ("Maha Vidyalaya", 180, 600),
    ("Primary School", 90, 260),
    ("Vidyalayam", 120, 400),
    ("Community Hall", 60, 200),
    ("Buddhist Temple", 80, 300),
    ("Kovil", 70, 260),
    ("Jumma Mosque", 90, 320),
    ("Divisional Secretariat Hall", 150, 450),
)

_FACILITIES: Final[tuple[str, ...]] = (
    "water",
    "electricity",
    "toilets",
    "kitchen",
    "medical_point",
    "generator",
    "wheelchair_access",
    "separate_family_space",
)

# When the first families arrive, in hours past landfall, and how long filling takes.
# People move before landfall when a warning worked, and after it when it did not.
FILL_START_HOUR: Final = -12.0
FILL_SATURATION_HOUR: Final = 36.0

# Share of rated capacity a location reaches at saturation. Above 1.0 means over-capacity,
# which happens to about a fifth of them.
_TYPICAL_FILL: Final = 0.85
_OVERFLOW_FILL: Final = 1.25
_OVERFLOW_SHARE: Final = 0.2


@dataclass(frozen=True, slots=True)
class SafetyLocation:
    """One safety location, before occupancy is applied."""

    location_id: str
    name: str
    district_code: str
    ds_division_code: str
    lon: float
    lat: float
    capacity_persons: int
    facilities: tuple[str, ...]
    # The saturation multiple this location reaches. Held on the record rather than drawn
    # at read time so a location that overflows keeps overflowing across requests.
    fill_target: float


def _locations_per_district() -> dict[str, int]:
    """How many locations each district has.

    Weighted toward the affected districts, because that is where the DMC opens them.
    Every district gets at least two: a national register that lists nothing in Hambantota
    would make an unaffected district indistinguishable from an unlisted one.
    """
    weights = {
        district.code: (4.0 if district.code in AFFECTED_DISTRICTS else 1.0)
        for district in DISTRICTS
    }
    total_weight = sum(weights.values())
    counts = {
        code: max(2, round(TOTAL_LOCATIONS * weight / total_weight))
        for code, weight in weights.items()
    }

    # Rounding drifts off the target. Correct on the largest district so the total is
    # exactly 280 - the figure this list is meant to match.
    drift = TOTAL_LOCATIONS - sum(counts.values())
    if drift:
        largest = max(counts, key=lambda code: counts[code])
        counts[largest] += drift
    return counts


def build_locations(*, seed: int) -> list[SafetyLocation]:
    """The whole national register. Deterministic in `seed`."""
    rng = random.Random(seed)  # noqa: S311 - synthetic reference data, not a secret
    counts = _locations_per_district()
    locations: list[SafetyLocation] = []

    for district in DISTRICTS:
        divisions = ds_codes(district)
        for index in range(1, counts[district.code] + 1):
            kind, capacity_low, capacity_high = rng.choice(_VENUE_KINDS)
            locations.append(
                SafetyLocation(
                    location_id=f"DMC-{district.code[3:]}-{index:03d}",
                    name=f"{district.en} {kind} {index}",
                    district_code=district.code,
                    ds_division_code=divisions[index % len(divisions)],
                    # Scattered around the district centre. Not survey positions, and
                    # never to be drawn on a map as though they were.
                    lon=round(district.lon + rng.uniform(-0.18, 0.18), 5),
                    lat=round(district.lat + rng.uniform(-0.18, 0.18), 5),
                    capacity_persons=rng.randrange(capacity_low, capacity_high),
                    facilities=tuple(
                        sorted(rng.sample(_FACILITIES, k=rng.randrange(2, len(_FACILITIES))))
                    ),
                    fill_target=(
                        _OVERFLOW_FILL if rng.random() < _OVERFLOW_SHARE else _TYPICAL_FILL
                    ),
                )
            )
    return locations


def _fill_fraction(hours_since_landfall: float) -> float:
    """How far through the filling curve the simulation is, 0.0 to 1.0.

    A logistic curve: nobody, then a rush around landfall, then a slow tail as people who
    tried to stay give up. Linear filling would make every location cross every threshold
    at the same moment, which is not a useful thing to demonstrate.
    """
    if hours_since_landfall <= FILL_START_HOUR:
        return 0.0
    midpoint = (FILL_START_HOUR + FILL_SATURATION_HOUR) / 2
    steepness = 6.0 / (FILL_SATURATION_HOUR - FILL_START_HOUR)
    return 1.0 / (1.0 + math.exp(-steepness * (hours_since_landfall - midpoint)))


def modelled_occupancy(location: SafetyLocation, *, hours_since_landfall: float, seed: int) -> int:
    """How many people are at this location at this simulated hour.

    Zero outside the affected districts. A national register where every school in Galle
    is quietly holding forty people would make the affected districts impossible to pick
    out, which is the one thing an operator needs from this list.
    """
    if location.district_code not in AFFECTED_DISTRICTS:
        return 0

    rng = random.Random((seed, location.location_id).__hash__())  # noqa: S311 - synthetic
    # Per-location scatter, drawn once and stable: two schools a kilometre apart do not
    # fill at the same rate, and the one on the wrong side of a flooded road fills first.
    scatter = rng.uniform(0.7, 1.15)
    fraction = _fill_fraction(hours_since_landfall) * location.fill_target * scatter
    return max(0, round(location.capacity_persons * fraction))


@dataclass(frozen=True, slots=True)
class SituationReport:
    """One DMC situation report."""

    report_id: str
    issued_at: datetime
    hazard: str
    districts_affected: tuple[str, ...]
    persons_affected: int
    persons_displaced: int
    deaths: int
    injured: int
    summary: str


# The DMC issues a situation report roughly twice a day during an event.
SITREP_INTERVAL_HOURS: Final = 12

# Persons affected per displaced person. Displacement is the number that gets reported;
# affected is the larger population whose water, power or road is gone.
_AFFECTED_MULTIPLE: Final = 6.5

# Casualty rates per thousand displaced. Deliberately small and deliberately non-zero:
# a demo that reports no deaths in a cyclone teaches the wrong thing about what these
# systems are counting, and one that reports many is grotesque.
_DEATHS_PER_THOUSAND: Final = 0.9
_INJURED_PER_THOUSAND: Final = 4.0


def situation_reports(
    *, landfall_at: datetime, hours_since_landfall: float, displaced_now: int, seed: int
) -> list[SituationReport]:
    """Every situation report issued up to the current simulated hour, newest first.

    Each report is a snapshot at its own issue time, so the series shows the numbers
    climbing. Regenerating the whole series on each request rather than accumulating it
    keeps the mock a pure function of the clock — advancing, restarting or replaying gives
    the same history.
    """
    if hours_since_landfall < 0:
        return []

    rng = random.Random((seed, "sitrep").__hash__())  # noqa: S311 - synthetic
    reports: list[SituationReport] = []
    issued_hour = 0.0
    sequence = 1

    while issued_hour <= hours_since_landfall:
        # The displacement figure at the moment this report was written, scaled from the
        # current total by where the filling curve had got to.
        progress = _fill_fraction(issued_hour) / max(_fill_fraction(hours_since_landfall), 1e-6)
        displaced = round(displaced_now * min(1.0, progress))
        affected = round(displaced * _AFFECTED_MULTIPLE)
        reports.append(
            SituationReport(
                report_id=f"DMC-SITREP-{sequence:03d}",
                issued_at=landfall_at + timedelta(hours=issued_hour),
                hazard="CYCLONE",
                districts_affected=tuple(sorted(AFFECTED_DISTRICTS)),
                persons_affected=affected,
                persons_displaced=displaced,
                deaths=round(displaced * _DEATHS_PER_THOUSAND / 1000),
                injured=round(displaced * _INJURED_PER_THOUSAND / 1000),
                summary=(
                    f"Situation report {sequence}. {displaced:,} persons displaced across "
                    f"{len(AFFECTED_DISTRICTS)} districts; {affected:,} affected. "
                    "Safety locations open and receiving."
                ),
            )
        )
        issued_hour += SITREP_INTERVAL_HOURS
        sequence += 1

    # Unused draw kept so the RNG is consumed identically whatever the hour, which keeps
    # the sequence stable if a future field starts drawing from it.
    rng.random()
    return list(reversed(reports))


@dataclass(frozen=True, slots=True)
class EvacuationOrder:
    """One evacuation order."""

    order_id: str
    issued_at: datetime
    effective_from: datetime
    ds_division_codes: tuple[str, ...]
    reason: str
    issued_by: str


# Evacuation orders go out before landfall, which is the whole point of a warning, and are
# lifted well after it. The gap between the Met warning standing down at T+48h and people
# being told they may go home is real and is worth showing: the weather ending is not the
# emergency ending, and a mock where the two coincide teaches the opposite.
EVACUATION_ORDER_HOUR: Final = -18.0
EVACUATION_STAND_DOWN_HOUR: Final = 96.0


def evacuation_orders(
    *, landfall_at: datetime, hours_since_landfall: float
) -> list[EvacuationOrder]:
    """Evacuation orders in force at the current simulated hour.

    One per affected district, issued together at T-18h. The `issued_by` field is always
    populated: an evacuation order with no named authority is not one, and a consumer
    should be able to rely on that rather than defending against a blank.
    """
    if not EVACUATION_ORDER_HOUR <= hours_since_landfall < EVACUATION_STAND_DOWN_HOUR:
        return []

    issued_at = landfall_at + timedelta(hours=EVACUATION_ORDER_HOUR)
    orders: list[EvacuationOrder] = []
    for district in DISTRICTS:
        if district.code not in AFFECTED_DISTRICTS:
            continue
        orders.append(
            EvacuationOrder(
                order_id=f"DMC-EVAC-{district.code[3:]}-001",
                issued_at=issued_at,
                effective_from=issued_at + timedelta(hours=2),
                ds_division_codes=tuple(ds_codes(district)),
                reason=(
                    "Storm surge and severe flooding expected within 24 hours in coastal "
                    "and low-lying areas."
                ),
                issued_by=f"District Secretary, {district.en}",
            )
        )
    return orders


def district_for_location(location: SafetyLocation) -> District | None:
    """The district record for a location, for callers that need its coordinates."""
    return next((d for d in DISTRICTS if d.code == location.district_code), None)
