"""The threshold engine.

Every number this produces ends up in front of a district officer with the government's name
on it, so the tests here are mostly about the ways it could be confidently wrong rather than
merely wrong.

The one to read first is `test_a_forecast_is_never_a_two_day_total_against_a_one_day_line`.
Summing an observation and a forecast crosses every evacuate threshold about a day early,
produces a plausible-looking table, and looks from the outside exactly like a working early
warning system.
"""

from __future__ import annotations

import pytest

from agent_svc.agents.forecast.exposure import DivisionExposure, DivisionRainfall
from agent_svc.agents.forecast.scoring import (
    APPROACHING_SHARE,
    CLASS_LOW,
    CLASS_MAJOR,
    CLASS_MODERATE,
    CLASS_NONE,
    CLASS_SEVERE,
    DEFAULT_ZONE,
    METHOD,
    MODEL_VERSION,
    RuleThresholdModel,
    ZoneThresholds,
    thresholds_for,
)

ZONE_3 = ZoneThresholds(
    zone=3,
    window_hours=24,
    watch_mm=100.0,
    warning_mm=150.0,
    evacuate_mm=200.0,
    provenance="NBRO 2019 zonation",
)
ZONE_1 = ZoneThresholds(
    zone=1,
    window_hours=24,
    watch_mm=200.0,
    warning_mm=275.0,
    evacuate_mm=350.0,
    provenance="NBRO 2019 zonation",
)


def division(**overrides: object) -> DivisionExposure:
    defaults: dict[str, object] = {
        "gn_division_id": "gn-1",
        "gn_division_code": "LK-21-01-001",
        "ds_division_code": "LK-21-01",
        "district_code": "LK-21",
        "centroid_lon": 80.63,
        "centroid_lat": 7.29,
        "household_count": 300,
        "population": 1200,
        "landslide_zone": 3,
        "flood_return_period_m": 30,
        "road_access_class": 2,
        "elderly_pct": 10.0,
        "under5_pct": 6.0,
    }
    return DivisionExposure(**{**defaults, **overrides})  # type: ignore[arg-type]


def rainfall(peak: float, *, window: int = 48, used: int = 6, silent: int = 0) -> DivisionRainfall:
    """Rainfall whose peak 24-hour accumulation is `peak`, in the named window."""
    values = {0: 0.0, 24: 0.0, 48: 0.0, 72: 0.0}
    values[window] = peak
    return DivisionRainfall(
        observed_24h=values[0],
        expected_24h=values[24],
        expected_48h=values[48],
        expected_72h=values[72],
        stations_used=used,
        stations_silent=silent,
    )


def score(rain: DivisionRainfall, div: DivisionExposure | None = None, thresholds=ZONE_3):
    return RuleThresholdModel().score(
        div or division(), rain, thresholds=thresholds, lead_time_hours=-1
    )


# --------------------------------------------------------------------------------------
# The bands
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("peak", "expected"),
    [
        (0.0, CLASS_NONE),
        (74.0, CLASS_NONE),
        (75.0, CLASS_LOW),
        (99.0, CLASS_LOW),
        (100.0, CLASS_MODERATE),
        (149.0, CLASS_MODERATE),
        (150.0, CLASS_MAJOR),
        (199.0, CLASS_MAJOR),
        (200.0, CLASS_SEVERE),
        (400.0, CLASS_SEVERE),
    ],
)
def test_the_class_comes_from_nbros_own_escalation_points(peak: float, expected: int) -> None:
    """Watch, warning and evacuate are decisions the country already makes.

    Mapping them onto moderate / major / severe is a translation. Anything else in this
    engine only adjusts around them, so if this mapping is wrong nothing else can be right.
    """
    result = score(rainfall(peak), division(landslide_zone=None), ZONE_3)

    assert result.impact_class == expected


def test_a_forecast_is_never_a_two_day_total_against_a_one_day_line() -> None:
    """The dimensional error that would look exactly like a working early warning.

    90 mm already fallen and 90 mm forecast is not 180 mm of rain against a 24-hour
    threshold - it is two separate 24-hour accumulations, neither of which reaches the
    warning level. Summing them would report major impact where there is moderate, a full
    day early, every time.
    """
    rain = DivisionRainfall(
        observed_24h=90.0,
        expected_24h=90.0,
        expected_48h=0.0,
        expected_72h=0.0,
        stations_used=5,
    )

    assert rain.peak() == (90.0, 0), "the peak window, not the sum of the windows"
    # 90 mm is below zone 3's 100 mm watch line, so this is class 1 on a stable slope.
    # Summed it would be 180 mm - past the 150 mm warning line, and class 3.
    assert score(rain, division(landslide_zone=1), ZONE_3).impact_class == CLASS_LOW


def test_the_lead_time_is_the_window_that_peaked() -> None:
    """ "Class 3 within 48 hours" is actionable. "Class 3" alone is a weather report."""
    assert score(rainfall(160.0, window=48)).lead_time_hours == 48
    assert score(rainfall(160.0, window=72)).lead_time_hours == 72
    assert score(rainfall(160.0, window=0)).lead_time_hours == 0


def test_rain_approaching_a_threshold_is_not_the_same_as_no_rain() -> None:
    """Without the low band the engine steps from nothing to moderate at one millimetre,
    and a division at 99% of its threshold reads identically to one at 10%."""
    just_under = ZONE_3.watch_mm * APPROACHING_SHARE

    assert score(rainfall(just_under - 1)).impact_class == CLASS_NONE
    assert score(rainfall(just_under)).impact_class == CLASS_LOW


# --------------------------------------------------------------------------------------
# The modifiers
# --------------------------------------------------------------------------------------


def test_a_fragile_slope_at_watch_level_is_a_major_concern() -> None:
    at_watch = ZONE_3.watch_mm

    fragile = score(rainfall(at_watch), division(landslide_zone=4))
    stable = score(rainfall(at_watch), division(landslide_zone=2))

    assert fragile.impact_class == CLASS_MAJOR
    assert stable.impact_class == CLASS_MODERATE


def test_a_modifier_cannot_reach_severe() -> None:
    """**Only NBRO's own evacuate line produces class 4.**

    Class 4 is what an evacuation advisory is written against, and moving families out of
    their homes has to rest on the published threshold the country agreed to - not on our
    judgement that a slope looked fragile.
    """
    at_warning = ZONE_3.warning_mm

    result = score(rainfall(at_warning), division(landslide_zone=4, flood_return_period_m=6))

    assert result.impact_class == CLASS_MAJOR


def test_the_evacuate_threshold_still_reaches_severe() -> None:
    """The cap constrains modifiers, not the band. Otherwise nothing is ever severe."""
    assert score(rainfall(ZONE_3.evacuate_mm)).impact_class == CLASS_SEVERE


def test_a_modifier_does_not_manufacture_a_forecast_out_of_a_dry_day() -> None:
    """A hazard zone has been there for decades. It is not news until the rain arrives."""
    result = score(rainfall(10.0), division(landslide_zone=4, flood_return_period_m=5))

    assert result.impact_class == CLASS_NONE


def test_frequent_flooding_raises_a_division_that_has_not_recovered() -> None:
    often = score(rainfall(ZONE_3.watch_mm), division(landslide_zone=1, flood_return_period_m=6))
    rarely = score(rainfall(ZONE_3.watch_mm), division(landslide_zone=1, flood_return_period_m=40))

    assert often.impact_class == CLASS_MAJOR
    assert rarely.impact_class == CLASS_MODERATE


# --------------------------------------------------------------------------------------
# Drivers
# --------------------------------------------------------------------------------------


def test_every_forecast_carries_a_non_empty_drivers_list() -> None:
    """Required by the model and again by a database CHECK.

    A forecast with no account of what produced it is not allowed to exist: the entire
    complaint this platform answers is that nobody could see how the decision was made.
    """
    for peak in (0.0, 80.0, 120.0, 180.0, 300.0):
        assert score(rainfall(peak)).drivers


def test_a_factor_that_changed_nothing_is_still_a_driver() -> None:
    """ "We checked the flood history and it was fine" must be distinguishable from "we
    never looked". For an engine whose selling point is that you can see how the decision
    was made, that difference is the product."""
    result = score(rainfall(ZONE_3.watch_mm), division(flood_return_period_m=40))

    flood = next(d for d in result.drivers if d.factor == "flood_return_period_m")
    assert flood.contribution == 0.0
    assert flood.value == 40


def test_the_contributions_account_for_the_class() -> None:
    """A drivers list whose numbers do not add up to the answer is a decoration."""
    result = score(rainfall(ZONE_3.watch_mm), division(landslide_zone=4))

    assert sum(driver.contribution for driver in result.drivers) == result.impact_class


def test_the_drivers_serialise_to_the_object_the_column_requires() -> None:
    """`hazard.impact_forecast.drivers` has a CHECK requiring a non-empty JSONB object;
    build file 13 describes a list. The database wins."""
    result = score(rainfall(180.0))

    stored = result.drivers_as_object()

    assert isinstance(stored, dict)
    assert stored
    assert "peak_rainfall_24h" in stored
    assert set(stored["peak_rainfall_24h"]) == {"value", "threshold", "contribution", "note"}


def test_synthetic_thresholds_are_labelled_on_the_driver() -> None:
    """A forecast produced against the mock's stand-ins must not read as one produced
    against NBRO's published figures."""
    synthetic = ZONE_3.model_copy(update={"provenance": "SYNTHETIC - stand-in values"})

    result = score(rainfall(180.0), thresholds=synthetic)

    rain_driver = next(d for d in result.drivers if d.factor == "peak_rainfall_24h")
    assert "synthetic" in (rain_driver.note or "").lower()


# --------------------------------------------------------------------------------------
# Missing data
# --------------------------------------------------------------------------------------


def test_an_unsurveyed_division_scores_against_the_least_hazardous_zone() -> None:
    """An absent NBRO record is not evidence of safe ground - but acting on it as though
    it were evidence of *danger* would put the platform's credibility behind a guess."""
    assert thresholds_for(None, {1: ZONE_1, 3: ZONE_3}) is ZONE_1
    assert DEFAULT_ZONE == 1

    result = score(rainfall(120.0), division(landslide_zone=None), ZONE_1)

    zone_driver = next(d for d in result.drivers if d.factor == "landslide_zone")
    assert zone_driver.value == DEFAULT_ZONE
    assert "no NBRO survey" in (zone_driver.note or "")


def test_an_unsurveyed_division_is_less_confident() -> None:
    surveyed = score(rainfall(120.0), division(landslide_zone=3))
    unsurveyed = score(rainfall(120.0), division(landslide_zone=None))

    assert unsurveyed.confidence < surveyed.confidence


def test_gauge_outages_cost_confidence_in_proportion_not_in_count() -> None:
    """Stations go offline in exactly the weather that matters.

    At the peak of Ditwah roughly a fifth of the national network is down. A per-station
    penalty reads that as forty separate failures and drives every division in the country
    below any review threshold at the exact hour the forecast matters most - which is not a
    calibrated confidence, it is a broken one.
    """
    healthy = score(rainfall(120.0, used=30, silent=0))
    national_outage = score(rainfall(120.0, used=24, silent=6))
    local_blackout = score(rainfall(120.0, used=1, silent=3))

    assert healthy.confidence > national_outage.confidence > local_blackout.confidence
    assert national_outage.confidence > 0.7, "a fifth of gauges down is a Tuesday"


def test_no_gauge_in_range_is_reported_as_low_confidence_not_as_no_rain() -> None:
    """A national average would make every division look identical and let targeting
    appear to work while doing nothing."""
    result = score(rainfall(0.0, used=0, silent=0))

    assert result.confidence < 0.3


# --------------------------------------------------------------------------------------
# What comes out
# --------------------------------------------------------------------------------------


def test_every_row_says_it_came_from_a_rule_and_not_a_model() -> None:
    """Phase 1 has no trained model. Implying otherwise is the one thing build file 13
    says is not legitimate."""
    result = score(rainfall(180.0))

    assert result.method == METHOD == "RULE_THRESHOLD"
    assert result.model_version == MODEL_VERSION


def test_households_are_counted_only_where_there_is_impact() -> None:
    assert score(rainfall(10.0)).expected_households_affected == 0
    assert score(rainfall(ZONE_3.watch_mm)).expected_households_affected == 300


def test_road_access_loss_is_separate_from_severity() -> None:
    """Losing access changes *what a responder does* - preposition now, or plan to reach
    them later. Folding it into a severity number loses the distinction a dispatcher needs.
    """
    fragile = score(rainfall(160.0), division(road_access_class=4))
    solid = score(rainfall(160.0), division(road_access_class=1))

    assert fragile.expected_road_access_loss
    assert not solid.expected_road_access_loss
    assert fragile.impact_class == solid.impact_class


def test_road_access_is_not_lost_at_moderate_impact() -> None:
    """Fragile access matters once impact is major. Below that a division is wet, not cut
    off, and predicting isolation from every rain shower is how a map stops being read."""
    moderate = division(road_access_class=4, landslide_zone=1, flood_return_period_m=40)

    result = score(rainfall(ZONE_3.watch_mm), moderate)

    assert result.impact_class == CLASS_MODERATE
    assert not result.expected_road_access_loss


def test_the_engine_is_pure() -> None:
    """No clock, no network, no model. It is what makes the replay honest and what makes
    the degraded path identical to the normal one."""
    rain = rainfall(160.0)
    div = division()

    first = score(rain, div)
    second = score(rain, div)

    assert first == second
