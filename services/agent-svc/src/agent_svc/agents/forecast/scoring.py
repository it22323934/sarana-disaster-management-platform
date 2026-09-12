"""The impact scoring engine: a documented threshold table, and nothing else.

**There is no trained model here and the code says so everywhere.** Phase 1 has no
historical dataset in hand, so this is a rule-based threshold engine over NBRO's published
rainfall thresholds and the static exposure attributes. Every forecast it produces carries
`method="RULE_THRESHOLD"` and `model_version="v1"`, the UI shows it, and the demo says it
out loud. That is a legitimate Phase 1. Implying a model exists is not.

The seam is real: `ImpactModel` is a Protocol with `RuleThresholdModel` as the only
implementation. A trained model drops in behind it once a data-sharing agreement lands, and
`method="MODEL"` distinguishes its output from this one's forever after — so the Learn loop
can compare them honestly rather than assuming the newer one is better.

## Why the number comes out where it does

**NBRO's own escalation points are the spine.** They publish, per hazard zone, the
cumulative rainfall at which a slope goes to watch, to warning, and to evacuate. Those are
the three decisions the country already makes; mapping them onto moderate / major / severe
is a translation, not an invention. Anything else here only adjusts around them.

**It scores the forecast, not the rain gauge.** A division is scored on the worst 24-hour
accumulation in view - which may be the last 24 hours, or a window up to three days out -
and reports which window that was as its lead time. An engine that scored only what had
already fallen would produce excellent forecasts several hours after they stopped being
useful.

**The comparison is like for like.** Every window is a 24-hour accumulation and every NBRO
threshold is a 24-hour figure. Summing an observation and a forecast instead would give a
two-day total measured against a one-day threshold, crossing every evacuate level about a
day early - and from the outside that looks exactly like a working early warning, which
makes it the most dangerous mistake available here.

**Every factor consulted becomes a driver, including the ones that changed nothing.** A
driver list showing only what fired makes "we checked the flood history and it was fine"
indistinguishable from "we never looked" — and for an engine whose entire selling point is
that you can see how the decision was made, that difference is the product. It also means
`drivers` is non-empty by construction, which the database requires.

## Reading a class

| Class | Meaning |
|---|---|
| 0 | Nothing expected |
| 1 | Rain approaching the watch threshold; worth monitoring |
| 2 | Moderate — NBRO watch level reached |
| 3 | Major — NBRO warning level, or watch on already-fragile ground |
| 4 | Severe — NBRO evacuate level |
"""

from __future__ import annotations

from typing import Any, Final, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_svc.agents.forecast.exposure import DivisionExposure, DivisionRainfall

# What goes in `hazard.impact_forecast.method`. The schema's CHECK allows RULE_THRESHOLD and
# MODEL and nothing else, so build file 13's `"RULE_THRESHOLD_v1"` is split across the two
# columns the schema actually has: the method here, the version below.
METHOD: Final = "RULE_THRESHOLD"
MODEL_VERSION: Final = "v1"

# Class boundaries, named so a comparison never reads as a bare integer.
CLASS_NONE: Final = 0
CLASS_LOW: Final = 1
CLASS_MODERATE: Final = 2
CLASS_MAJOR: Final = 3
CLASS_SEVERE: Final = 4

# Rain at or above this share of the watch threshold, but below it, is class 1. Without a
# band here the engine steps from "nothing" straight to "moderate" at one millimetre, and a
# division sitting at 99% of its threshold reads identically to one at 10%.
APPROACHING_SHARE: Final = 0.75

# The zone whose slopes are fragile enough that reaching watch is already a major concern.
# NBRO zones 3 and 4 are the surveyed high and very-high hazard areas.
FRAGILE_ZONE: Final = 3

# Months between floods at or below which a division is treated as frequently flooded. A
# year: a division that floods more often than annually has flood-adapted housing and
# infrastructure in worse condition, and its residents have less to fall back on each time.
FREQUENT_FLOOD_MONTHS: Final = 12

# Road access class at or above which access is treated as fragile. Higher is worse; see
# `exposure.py` for why that direction is fixed there and not guessed here.
FRAGILE_ROAD_CLASS: Final = 3

# The floor a modifier cannot push a division below. Modifiers adjust; they do not create a
# forecast out of nothing. A division whose rainfall is nowhere near its threshold does not
# become moderate because it happens to sit in a high hazard zone — the zone has been there
# for decades and is not news.
MODIFIER_FLOOR: Final = CLASS_MODERATE

# The ceiling a modifier cannot push a division through. **Only NBRO's own evacuate
# threshold produces class 4.** Class 4 is what an evacuation advisory is written against,
# and an advisory that moves families out of their homes has to rest on the published line
# the country already agreed to - not on our judgement that a slope looked fragile. The
# modifiers can take a division to major, which is the level at which somebody prepositions
# and looks harder. They cannot take it to severe.
MODIFIER_CEILING: Final = CLASS_MAJOR

# Confidence. A rule engine's confidence is about the *inputs*, not about the rule: the
# thresholds either were or were not crossed. What varies is how much we trust the number
# that was compared against them.
BASE_CONFIDENCE: Final = 0.85
# What a total gauge blackout costs, scaled by the share of nearby stations that are
# silent. **The share, not the count**: stations go offline in exactly the weather that
# matters, and at the peak of Ditwah roughly a fifth of the network is down nationally. A
# per-station penalty would read that as forty separate failures and drive every division
# in the country below any review threshold at the exact hour the forecast matters most -
# which is not a calibrated confidence, it is a broken one. Two silent gauges out of three
# nearby is a real problem; six out of thirty is a Tuesday.
OUTAGE_PENALTY: Final = 0.50
# No gauge in range at all. Not zero — the district forecast still says something — but low
# enough that the review gate catches it.
NO_STATION_CONFIDENCE: Final = 0.25
# Missing zonation means the thresholds were guessed from the national default. Real: the
# survey does not cover every division.
UNSURVEYED_PENALTY: Final = 0.15
MIN_CONFIDENCE: Final = 0.10

# The zone assumed when NBRO's survey has nothing for a division. The *least* hazardous, so
# a missing survey cannot manufacture an evacuation advisory — an absent record is not
# evidence of safe ground, but acting on it as though it were evidence of danger would put
# the platform's credibility behind a guess. The driver says the zone was assumed.
DEFAULT_ZONE: Final = 1


class Driver(BaseModel):
    """One factor, what it was, what it was measured against, and what it did.

    `contribution` is in classes, so 1.0 means this factor moved the impact class up by
    one. It is signed: a factor that pulled the class down reports a negative number, which
    is what stops a drivers list from reading as a prosecution case.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    factor: str
    value: float | str
    threshold: float | str | None = None
    contribution: float = 0.0
    note: str | None = Field(
        default=None,
        description="Why, when the number alone does not say it — an assumed value, a "
        "missing survey, a gauge outage.",
    )


class ImpactScore(BaseModel):
    """One division's forecast impact.

    `drivers` is required and non-empty, in the model and again as a database CHECK. A
    forecast with no account of what produced it is not allowed to exist: the entire
    complaint this platform answers is that nobody could see how the decision was made.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gn_division_id: str
    gn_division_code: str
    impact_class: int = Field(ge=CLASS_NONE, le=CLASS_SEVERE)
    confidence: float = Field(ge=0.0, le=1.0)
    lead_time_hours: int = Field(ge=0)
    drivers: list[Driver] = Field(min_length=1)
    expected_households_affected: int = Field(ge=0)
    expected_road_access_loss: bool
    method: str = METHOD
    model_version: str = MODEL_VERSION

    def drivers_as_object(self) -> dict[str, Any]:
        """`drivers` in the shape the database column takes.

        `hazard.impact_forecast.drivers` is a JSONB **object** with a CHECK enforcing it —
        build file 13 describes a list. Keyed by factor name rather than wrapped in
        `{"items": [...]}`, because the key then enforces one entry per factor, which a list
        cannot, and because `drivers->'peak_rainfall_24h'` is a query somebody will want to
        write.
        """
        return {
            driver.factor: {
                "value": driver.value,
                "threshold": driver.threshold,
                "contribution": driver.contribution,
                "note": driver.note,
            }
            for driver in self.drivers
        }


class ZoneThresholds(BaseModel):
    """NBRO's escalation points for one hazard zone, in cumulative millimetres."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    zone: int
    window_hours: int
    watch_mm: float
    warning_mm: float
    evacuate_mm: float
    provenance: str = ""

    @property
    def is_official(self) -> bool:
        """Whether these are NBRO's operational figures or the mock's stand-ins.

        Carried through to the driver note. A forecast produced against synthetic
        thresholds must not be presented as one produced against published ones.
        """
        return bool(self.provenance) and not self.provenance.startswith("SYNTHETIC")


class ImpactModel(Protocol):
    """The seam a trained model drops into.

    Deliberately narrow: everything a model needs about a division arrives in the two
    arguments, and everything the platform needs back is in `ImpactScore`. A model that
    needed more context than this would be one that had grown a dependency on how the
    platform happens to be wired today.
    """

    @property
    def method(self) -> str:
        """`RULE_THRESHOLD` or `MODEL`. Recorded on every row this produces."""
        ...

    @property
    def version(self) -> str: ...

    def score(
        self,
        division: DivisionExposure,
        rainfall: DivisionRainfall,
        *,
        thresholds: ZoneThresholds,
        lead_time_hours: int,
    ) -> ImpactScore: ...


class RuleThresholdModel:
    """The only implementation, and the one the demo runs on.

    Pure: no I/O, no clock, no model provider. Every input arrives as an argument, which is
    what makes the whole table unit-testable and what lets the eval harness replay a
    scenario without a network.
    """

    method: Final = METHOD
    version: Final = MODEL_VERSION

    def score(
        self,
        division: DivisionExposure,
        rainfall: DivisionRainfall,
        *,
        thresholds: ZoneThresholds,
        lead_time_hours: int,
    ) -> ImpactScore:
        """Score one division. See the module docstring for how the number is arrived at."""
        drivers: list[Driver] = []

        peak_mm, peak_window = rainfall.peak()
        base = self._band(peak_mm, thresholds)
        drivers.append(self._rainfall_driver(rainfall, thresholds, base))
        drivers.append(self._zone_driver(division, thresholds))

        modified = base
        for modifier in (self._fragile_slope, self._frequent_flooding):
            adjusted, driver = modifier(division, base)
            modified += adjusted
            drivers.append(driver)

        # The band alone may reach severe; modifiers may not lift anything past major.
        impact = max(CLASS_NONE, min(CLASS_SEVERE, max(base, min(MODIFIER_CEILING, modified))))

        road_loss, road_driver = self._road_access(division, impact)
        drivers.append(road_driver)

        return ImpactScore(
            gn_division_id=division.gn_division_id,
            gn_division_code=division.gn_division_code,
            impact_class=impact,
            confidence=self._confidence(division, rainfall),
            # The window that peaked, when the caller has not pinned one. "Class 3 within
            # 48 hours" is actionable; "class 3, lead time unspecified" is not.
            lead_time_hours=lead_time_hours if lead_time_hours >= 0 else peak_window,
            drivers=drivers,
            expected_households_affected=(
                division.household_count if impact >= CLASS_MODERATE else 0
            ),
            expected_road_access_loss=road_loss,
            method=self.method,
            model_version=self.version,
        )

    # ----------------------------------------------------------------------------------
    # The band, which is where the class actually comes from
    # ----------------------------------------------------------------------------------

    def _band(self, cumulative_mm: float, thresholds: ZoneThresholds) -> int:
        if cumulative_mm >= thresholds.evacuate_mm:
            return CLASS_SEVERE
        if cumulative_mm >= thresholds.warning_mm:
            return CLASS_MAJOR
        if cumulative_mm >= thresholds.watch_mm:
            return CLASS_MODERATE
        if cumulative_mm >= thresholds.watch_mm * APPROACHING_SHARE:
            return CLASS_LOW
        return CLASS_NONE

    def _rainfall_driver(
        self, rainfall: DivisionRainfall, thresholds: ZoneThresholds, base: int
    ) -> Driver:
        """The dominant driver, and the one an officer reads first.

        The threshold reported is the one the value was actually compared against — the
        next band up from where it landed, so the number answers "how far off the next
        level is this?" rather than restating the level it already reached.
        """
        peak_mm, peak_window = rainfall.peak()
        next_up = {
            CLASS_NONE: thresholds.watch_mm * APPROACHING_SHARE,
            CLASS_LOW: thresholds.watch_mm,
            CLASS_MODERATE: thresholds.warning_mm,
            CLASS_MAJOR: thresholds.evacuate_mm,
            CLASS_SEVERE: thresholds.evacuate_mm,
        }[base]

        when = "already fallen" if peak_window == 0 else f"forecast within {peak_window}h"
        note = f"worst 24-hour accumulation in view, {when}"
        if not thresholds.is_official:
            note += "; thresholds are synthetic stand-ins, not NBRO's published figures"

        return Driver(
            # Named for what it is. Build file 13's example says `cumulative_rainfall_72h`,
            # which would be a 72-hour total - and NBRO's thresholds are 24-hour figures.
            # Comparing the two would cross every evacuate level about a day early.
            factor="peak_rainfall_24h",
            value=round(peak_mm, 1),
            threshold=round(next_up, 1),
            contribution=float(base),
            note=note,
        )

    def _zone_driver(self, division: DivisionExposure, thresholds: ZoneThresholds) -> Driver:
        """The zone contributes no classes of its own. It chose the thresholds.

        Reported at zero contribution rather than left out, because "this was scored
        against zone 3's numbers" is the first thing anybody checks when they disagree with
        a forecast, and a driver list that omits it sends them to the source code.
        """
        assumed = division.landslide_zone is None
        return Driver(
            factor="landslide_zone",
            value=division.landslide_zone if division.landslide_zone is not None else DEFAULT_ZONE,
            threshold=f"watch {thresholds.watch_mm:.0f} / warning {thresholds.warning_mm:.0f} "
            f"/ evacuate {thresholds.evacuate_mm:.0f} mm over {thresholds.window_hours}h",
            contribution=0.0,
            note=(
                "no NBRO survey for this division; scored against the least hazardous "
                "zone so a missing record cannot manufacture an evacuation advisory"
                if assumed
                else None
            ),
        )

    # ----------------------------------------------------------------------------------
    # Modifiers. Each returns (classes added, the driver that says so)
    # ----------------------------------------------------------------------------------

    def _fragile_slope(self, division: DivisionExposure, base: int) -> tuple[int, Driver]:
        """A surveyed high-hazard slope that has reached watch is already a major concern.

        Only above the floor: the zone has been there for decades and is not news on a dry
        day. It is news the moment the rain reaches the level NBRO set for it.
        """
        zone = division.landslide_zone
        applies = zone is not None and zone >= FRAGILE_ZONE and base >= MODIFIER_FLOOR
        return (
            1 if applies else 0,
            Driver(
                factor="fragile_slope",
                value=zone if zone is not None else "unsurveyed",
                threshold=f"zone >= {FRAGILE_ZONE} and impact >= {MODIFIER_FLOOR}",
                contribution=1.0 if applies else 0.0,
                note=(
                    "surveyed high-hazard slope, already at or above watch level"
                    if applies
                    else None
                ),
            ),
        )

    def _frequent_flooding(self, division: DivisionExposure, base: int) -> tuple[int, Driver]:
        """A division that floods more often than annually has less to fall back on.

        Housing and drainage are in worse condition every time, and the households have
        absorbed the cost of the last one. Same floor as the slope modifier and for the
        same reason.
        """
        months = division.flood_return_period_m
        applies = months is not None and months <= FREQUENT_FLOOD_MONTHS and base >= MODIFIER_FLOOR
        return (
            1 if applies else 0,
            Driver(
                factor="flood_return_period_m",
                value=months if months is not None else "unknown",
                threshold=FREQUENT_FLOOD_MONTHS,
                contribution=1.0 if applies else 0.0,
                note=(
                    f"floods roughly every {months} months; recovery from the last one is "
                    "unlikely to be complete"
                    if applies
                    else None
                ),
            ),
        )

    def _road_access(self, division: DivisionExposure, impact: int) -> tuple[bool, Driver]:
        """Whether this division is likely to be cut off.

        Separate from the impact class on purpose. Losing road access changes *what a
        responder does* — preposition now, or plan to reach them later — and folding it into
        a severity number would lose exactly the distinction a dispatcher needs.
        """
        road = division.road_access_class
        applies = road is not None and road >= FRAGILE_ROAD_CLASS and impact >= CLASS_MAJOR
        return (
            applies,
            Driver(
                factor="road_access_class",
                value=road if road is not None else "unknown",
                threshold=FRAGILE_ROAD_CLASS,
                contribution=0.0,
                note=(
                    "access is fragile and impact is major or worse; expect this division "
                    "to be cut off"
                    if applies
                    else None
                ),
            ),
        )

    # ----------------------------------------------------------------------------------

    def _confidence(self, division: DivisionExposure, rainfall: DivisionRainfall) -> float:
        """How much to trust the inputs, not how much to trust the rule.

        The thresholds either were or were not crossed — that part carries no uncertainty.
        What varies is the rainfall number that was compared against them and whether the
        division was ever surveyed.
        """
        if rainfall.stations_used == 0:
            return NO_STATION_CONFIDENCE

        nearby = rainfall.stations_used + rainfall.stations_silent
        silent_share = rainfall.stations_silent / nearby if nearby else 0.0

        confidence = BASE_CONFIDENCE - OUTAGE_PENALTY * silent_share
        if division.landslide_zone is None:
            confidence -= UNSURVEYED_PENALTY
        return round(max(MIN_CONFIDENCE, min(1.0, confidence)), 3)


def thresholds_for(zone: int | None, table: dict[int, ZoneThresholds]) -> ZoneThresholds:
    """The threshold set for a division's zone, defaulting when it was never surveyed.

    Raises:
        KeyError: if the table has no entry for the default zone either, which means NBRO
            returned nothing usable and the caller should degrade rather than guess.
    """
    return table.get(zone if zone is not None else DEFAULT_ZONE, table[DEFAULT_ZONE])
