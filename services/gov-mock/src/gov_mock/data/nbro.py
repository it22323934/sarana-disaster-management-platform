"""Synthetic NBRO data: landslide zonation, rainfall thresholds, and bulletins.

**The zonation deliberately agrees with SARANA's seed.** `admin.gn_division.landslide_zone`
is populated from NBRO's survey, so the mock has to produce the same zone for the same
division or the platform would be reasoning about one hazard map while the warning came
from another. `zone_for()` mirrors the rule in `tools/seed/generate.py` exactly, and
`tests/gov_mock/test_zonation_agrees.py` asserts it stays that way.

**The thresholds are stand-ins and say so.** Every `ThresholdSet` this module builds
carries a provenance string beginning `SYNTHETIC`, which makes `ThresholdSet.is_official`
report False everywhere the figures are used. NBRO's operational thresholds are not
published in a form this repository can cite, and a number that reads as authoritative
while being invented is how a warning gets issued at the wrong time. Replacing them is a
one-line change here and a provenance string; it does not need code anywhere else, which
is the reason they are served rather than hardcoded in the agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from gov_mock.data.districts import DS_PER_DISTRICT, GN_PER_DS

# Mirrors `tools/seed/generate.py`. Kept as its own constant with its own name so that
# changing one and not the other is a test failure rather than a silent divergence.
_ZONE_COUNT: Final = 4

# Cumulative rainfall over 24 hours, in millimetres, at which each zone escalates.
#
# SYNTHETIC. Read the module docstring. These are plausible figures chosen so that a
# zone 4 division crosses `watch` early in a Ditwah-shaped curve and a zone 1 division
# never crosses `evacuate` at all - which is what makes the escalation demonstrable. They
# are not NBRO's numbers.
_PROVENANCE: Final = (
    "SYNTHETIC - plausible stand-in values, not NBRO's operational thresholds. "
    "Replace with the figures NBRO confirms in writing; see NbroRealClient.integration."
)

THRESHOLD_WINDOW_HOURS: Final = 24

_THRESHOLDS_MM: Final[dict[int, tuple[float, float, float]]] = {
    # zone: (watch, warning, evacuate)
    4: (75.0, 100.0, 150.0),
    3: (100.0, 150.0, 200.0),
    2: (150.0, 200.0, 275.0),
    1: (200.0, 275.0, 350.0),
}

# How long a bulletin stays in force once issued. NBRO reissues rather than extending, so
# an expired bulletin is a real state a consumer has to handle.
BULLETIN_VALIDITY_HOURS: Final = 12


@dataclass(frozen=True, slots=True)
class Threshold:
    """The escalation points for one hazard zone."""

    zone: int
    window_hours: int
    watch_mm: float
    warning_mm: float
    evacuate_mm: float
    provenance: str

    def level_for(self, rainfall_mm: float) -> str | None:
        """The escalation level this rainfall reaches, or None if it reaches none."""
        if rainfall_mm >= self.evacuate_mm:
            return "EVACUATE"
        if rainfall_mm >= self.warning_mm:
            return "WARNING"
        if rainfall_mm >= self.watch_mm:
            return "WATCH"
        return None


def zone_for(gn_division_code: str) -> int:
    """The landslide hazard zone for a GN division, 1 (low) to 4 (very high).

    Mirrors `tools/seed/generate.py`: `1 + (ds_index + gn_index) % 4`. The arithmetic is
    reproduced rather than imported because this service is a stand-in for NBRO's own
    register and must not depend on SARANA's seed tooling — but the two are asserted equal
    by a test, which is the only way a mock and the platform stay in step without one
    importing the other.

    Raises:
        ValueError: if the code is not a GN division code.
    """
    parts = gn_division_code.split("-")
    if len(parts) != 4:
        raise ValueError(f"not a GN division code: {gn_division_code!r}")
    try:
        ds_index = int(parts[2])
        gn_index = int(parts[3])
    except ValueError as error:
        raise ValueError(f"not a GN division code: {gn_division_code!r}") from error

    if not 1 <= ds_index <= DS_PER_DISTRICT or not 1 <= gn_index <= GN_PER_DS:
        raise ValueError(f"GN division code out of range: {gn_division_code!r}")

    return 1 + (ds_index + gn_index) % _ZONE_COUNT


def surveyed_year(gn_division_code: str) -> int:
    """The year this division was last surveyed.

    Spread across a decade because zonation surveys are, and a consumer that assumes a
    single national survey date will be wrong about how stale its hazard map is.
    """
    return 2014 + (sum(ord(character) for character in gn_division_code) % 10)


def thresholds() -> list[Threshold]:
    """The threshold set for every zone, highest hazard first."""
    return [
        Threshold(
            zone=zone,
            window_hours=THRESHOLD_WINDOW_HOURS,
            watch_mm=values[0],
            warning_mm=values[1],
            evacuate_mm=values[2],
            provenance=_PROVENANCE,
        )
        for zone, values in sorted(_THRESHOLDS_MM.items(), reverse=True)
    ]


def threshold_for(zone: int) -> Threshold:
    """The threshold set for one zone.

    Raises:
        KeyError: for a zone outside 1-4. There is no default: silently treating an
            unknown zone as low hazard would suppress a warning.
    """
    values = _THRESHOLDS_MM[zone]
    return Threshold(
        zone=zone,
        window_hours=THRESHOLD_WINDOW_HOURS,
        watch_mm=values[0],
        warning_mm=values[1],
        evacuate_mm=values[2],
        provenance=_PROVENANCE,
    )


@dataclass(frozen=True, slots=True)
class Bulletin:
    """One early-warning bulletin, as NBRO would issue it."""

    bulletin_id: str
    level: str
    issued_at: datetime
    valid_until: datetime
    ds_division_codes: tuple[str, ...]
    advice: str


# What NBRO actually tells people at each level, in English. The trilingual rendering is
# the Warning agent's job: NBRO issues in English and Sinhala, and the platform is
# responsible for the third language rather than pretending the source supplied it.
_ADVICE: Final[dict[str, str]] = {
    "WATCH": (
        "Be alert for cracks in the ground, tilting trees or poles, and sudden changes in "
        "spring water. Prepare to move."
    ),
    "WARNING": (
        "Move away from steep slopes and the base of cuttings. Do not remain in a house "
        "showing new cracks."
    ),
    "EVACUATE": (
        "Leave immediately for the nearest safety location. Do not wait for daylight or "
        "for transport to be arranged."
    ),
}


def bulletin_for(
    *,
    ds_division_codes: tuple[str, ...],
    level: str,
    issued_at: datetime,
    sequence: int,
) -> Bulletin:
    """Build one bulletin. Ids are sequential and stable for a given simulated hour."""
    return Bulletin(
        bulletin_id=f"NBRO-{issued_at:%Y%m%d}-{sequence:03d}",
        level=level,
        issued_at=issued_at,
        valid_until=issued_at + timedelta(hours=BULLETIN_VALIDITY_HOURS),
        ds_division_codes=ds_division_codes,
        advice=_ADVICE[level],
    )
