"""The forecast agent, in the shape the evaluation harness can score.

```bash
make eval AGENT=forecast
python -m agent_svc.runtime.eval --agent forecast --fixtures data/fixtures/smoke
```

## What this measures, and what it does not

The production graph talks to the Met Department, NBRO and core-api. A harness that had to
stand all three up before it could report an accuracy figure is a harness nobody runs before
pushing. So what is evaluated is the part of this agent that has a **confidence worth
calibrating**: the scoring engine, one division at a time.

That is the honest boundary. Reconciliation and the narrative are guarded by their own
tests - a floor that cannot be talked down, a numeral check that discards a whole
generation - and neither produces a probability. Scoring does, and `confidence` drives real
decisions, so it is the thing that has to be calibrated.

## What "accuracy" means here, honestly

**Until file 28 lands there is no labelled historical dataset**, so the labels in the smoke
fixtures are agreed expectations: a reading of what NBRO's own escalation points should
produce for a given division and rainfall, written from the thresholds rather than from this
code. That makes this a regression gate, not a measure of skill. If somebody changes a
constant and a division that should reach major impact stops doing so, the eval fails - which
is what it is for.

Calling it accuracy against a trained baseline would be the same overclaim the whole agent is
built to avoid.
"""

from __future__ import annotations

from typing import Any, Final

from langgraph.graph import END, START, StateGraph

from agent_svc.agents.forecast.exposure import DivisionExposure, DivisionRainfall
from agent_svc.agents.forecast.scoring import RuleThresholdModel, ZoneThresholds
from agent_svc.runtime.state import AgentState

# The thresholds a case is scored against when it does not supply its own. NBRO's four
# zones, at the values gov-mock serves - which are labelled synthetic stand-ins, not NBRO's
# operational figures, everywhere they are shown.
DEFAULT_THRESHOLDS: Final[dict[int, tuple[float, float, float]]] = {
    1: (200.0, 275.0, 350.0),
    2: (150.0, 200.0, 275.0),
    3: (100.0, 150.0, 200.0),
    4: (75.0, 100.0, 150.0),
}


def thresholds_for_zone(zone: int) -> ZoneThresholds:
    watch, warning, evacuate = DEFAULT_THRESHOLDS.get(zone, DEFAULT_THRESHOLDS[1])
    return ZoneThresholds(
        zone=zone,
        window_hours=24,
        watch_mm=watch,
        warning_mm=warning,
        evacuate_mm=evacuate,
        provenance="SYNTHETIC - gov-mock stand-in values, not NBRO's operational figures",
    )


def division_from(raw: dict[str, Any]) -> DivisionExposure:
    """One case's division. Everything is optional except the identity.

    A case that omits an attribute is testing what the engine does without it, which is a
    real state: the NBRO survey does not cover every division in the country.
    """
    return DivisionExposure(
        gn_division_id=str(raw.get("gn_division_id", "eval")),
        gn_division_code=str(raw.get("gn_division_code", "LK-21-01-001")),
        ds_division_code=str(raw.get("ds_division_code", "LK-21-01")),
        district_code=str(raw.get("district_code", "LK-21")),
        centroid_lon=float(raw.get("centroid_lon", 80.63)),
        centroid_lat=float(raw.get("centroid_lat", 7.29)),
        household_count=int(raw.get("household_count", 300)),
        population=int(raw.get("population", 1200)),
        landslide_zone=raw.get("landslide_zone"),
        flood_return_period_m=raw.get("flood_return_period_m"),
        road_access_class=raw.get("road_access_class"),
        cell_coverage_pct=raw.get("cell_coverage_pct"),
        elderly_pct=raw.get("elderly_pct"),
        under5_pct=raw.get("under5_pct"),
    )


def rainfall_from(raw: dict[str, Any]) -> DivisionRainfall:
    """One case's rainfall.

    Four separate 24-hour accumulations, never a total. A case that gave one figure and
    expected the engine to spread it over three days would be testing an engine that does
    not exist and hiding the dimensional rule that matters most.
    """
    return DivisionRainfall(
        observed_24h=float(raw.get("observed_24h", 0.0)),
        expected_24h=float(raw.get("expected_24h", 0.0)),
        expected_48h=float(raw.get("expected_48h", 0.0)),
        expected_72h=float(raw.get("expected_72h", 0.0)),
        stations_used=int(raw.get("stations_used", 6)),
        stations_silent=int(raw.get("stations_silent", 0)),
    )


async def score_one(state: AgentState) -> dict[str, Any]:
    """Score the single division a case describes.

    The output keys are what the fixtures label against: `impact_class` is the answer,
    `confidence` is what gets calibrated, and `provenance` says a rule produced it.
    """
    raw = dict(state.get("output", {}))
    division = division_from(raw)
    rainfall = rainfall_from(raw)
    zone = division.landslide_zone if division.landslide_zone is not None else 1

    score = RuleThresholdModel().score(
        division,
        rainfall,
        thresholds=thresholds_for_zone(zone),
        lead_time_hours=-1,
    )

    return {
        "status": "COMPLETED",
        "output": {
            "impact_class": score.impact_class,
            "lead_time_hours": score.lead_time_hours,
            "expected_road_access_loss": score.expected_road_access_loss,
            "expected_households_affected": score.expected_households_affected,
            "confidence": score.confidence,
            "reasoning": "; ".join(
                f"{driver.factor}={driver.value}" for driver in score.drivers if driver.contribution
            )
            or "no factor moved the class",
            "needs_human_review": False,
            # Always. A rule presented as a judgement is a lie about how the decision was
            # made, and the eval report is one of the places somebody checks.
            "provenance": "DETERMINISTIC",
        },
        "notes": [f"class {score.impact_class} at {score.lead_time_hours}h"],
    }


def build(checkpointer: Any) -> Any:
    """A one-node graph over the scoring engine.

    Deliberately not the production graph. See the module docstring for why, and for what
    that means the resulting numbers do and do not say.
    """
    builder = StateGraph(AgentState)
    builder.add_node("score", score_one)
    builder.add_edge(START, "score")
    builder.add_edge("score", END)
    return builder.compile(checkpointer=checkpointer)
