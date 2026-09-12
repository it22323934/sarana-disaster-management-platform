"""The graph end to end, the anticipatory triggers, and the Ditwah lead-time claim.

`test_kandy_reaches_major_impact_a_day_before_landfall` is the headline claim of the whole
platform. Build file 13 says it must be a test rather than a hope; this is that test, and it
runs against the committed Ditwah fixture with no network, no database and no model provider.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_svc.agents.forecast import triggers as trigger_rules
from agent_svc.agents.forecast.exposure import DivisionExposure, StationReading
from agent_svc.agents.forecast.graph import (
    MODEL_NARRATE_FROM,
    PERSIST_FROM,
    build,
)
from agent_svc.agents.forecast.ports import HazardWindow
from agent_svc.agents.forecast.reconcile import SourceClaim
from agent_svc.agents.forecast.replay import earliest_lead_time, load_fixture, replay
from agent_svc.agents.forecast.scoring import (
    CLASS_MAJOR,
    CLASS_SEVERE,
    Driver,
    ImpactScore,
    ZoneThresholds,
)
from agent_svc.repo.base import TRIGGER_ACTIONS
from agent_svc.runtime.checkpoint import config_for, memory_checkpointer
from agent_svc.runtime.state import initial_state

FIXTURE = Path("data/fixtures/ditwah/replay.json")

THRESHOLDS = {
    zone: ZoneThresholds(
        zone=zone,
        window_hours=24,
        watch_mm=watch,
        warning_mm=warning,
        evacuate_mm=evacuate,
        provenance="NBRO 2019",
    )
    for zone, (watch, warning, evacuate) in {
        1: (200.0, 275.0, 350.0),
        2: (150.0, 200.0, 275.0),
        3: (100.0, 150.0, 200.0),
        4: (75.0, 100.0, 150.0),
    }.items()
}


# What a gauge reads now, as a share of what is forecast. Below 1.0 on purpose: a feed
# whose observation equals its forecast has no lead time at all - the rain is already on the
# ground - and every trigger with a `min_lead_time_hours` would correctly decline to fire.
OBSERVED_SHARE = 0.4


class Feeds:
    """A hazard feed under the test's control."""

    def __init__(
        self,
        *,
        rain: float = 180.0,
        districts: tuple[str, ...] = ("LK-21",),
        claims: list[SourceClaim] | None = None,
        silent: int = 0,
    ) -> None:
        self.rain = rain
        self.districts = districts
        self._claims = claims or [
            SourceClaim("DEPT_METEOROLOGY", "AMBER", "district", "LK-21", None, "Ditwah")
        ]
        self.silent = silent

    async def warned_districts(self) -> tuple[str, ...]:
        return self.districts

    async def observations(self) -> list[StationReading]:
        observed = self.rain * OBSERVED_SHARE
        return [
            StationReading("MET-006", 80.63, 7.29, observed, reporting=True),
            StationReading("MET-007", 80.62, 7.33, observed, reporting=self.silent == 0),
        ]

    async def district_forecast(self, *, district_code: str, hours: int) -> float:
        return self.rain

    async def thresholds(self) -> dict[int, ZoneThresholds]:
        return THRESHOLDS

    async def claims(self, *, district_codes: tuple[str, ...]) -> list[SourceClaim]:
        return self._claims


class Directory:
    def __init__(self, divisions: list[DivisionExposure]) -> None:
        self._divisions = divisions

    async def divisions_in(self, district_codes: tuple[str, ...]) -> list[DivisionExposure]:
        return [d for d in self._divisions if d.district_code in set(district_codes)]

    async def names(self, gn_division_ids: list[str]) -> dict[str, dict[str, str]]:
        return {
            division.gn_division_id: {"si": "කන්දේ", "ta": "கண்டி", "en": "Kandy"}
            for division in self._divisions
        }


class Store:
    def __init__(self) -> None:
        self.forecasts: list[dict[str, Any]] = []
        self.firings: list[dict[str, Any]] = []

    async def save_forecasts(self, rows: list[dict[str, Any]]) -> list[str]:
        self.forecasts.extend(rows)
        return [f"forecast-{index}" for index in range(len(rows))]

    async def save_firings(self, rows: list[dict[str, Any]]) -> None:
        self.firings.extend(rows)


def a_division(index: int, *, zone: int = 3, road: int = 3) -> DivisionExposure:
    return DivisionExposure(
        gn_division_id=f"gn-{index}",
        gn_division_code=f"LK-21-01-{index:03d}",
        ds_division_code="LK-21-01",
        district_code="LK-21",
        centroid_lon=80.63,
        centroid_lat=7.29,
        household_count=300,
        population=1200,
        landslide_zone=zone,
        flood_return_period_m=30,
        road_access_class=road,
        elderly_pct=10.0,
        under5_pct=6.0,
    )


async def run_graph(
    *,
    feeds: Feeds | None = None,
    divisions: list[DivisionExposure] | None = None,
    store: Store | None = None,
    call: Any = None,
) -> dict[str, Any]:
    """Run the compiled graph, exactly as the service would."""
    graph = build(
        memory_checkpointer(),
        feeds=feeds or Feeds(),
        directory=Directory(divisions or [a_division(1)]),
        store=store,
        window=HazardWindow("evt-1", "CYCLONE", datetime(2026, 11, 26, 12, tzinfo=UTC)),
        call=call,
    )
    state = initial_state(
        agent="forecast",
        subject_type="hazard_event",
        subject_id="evt-1",
        correlation_id="test-corr",
    )
    result: dict[str, Any] = await graph.ainvoke(state, config_for("forecast:hazard_event:evt-1"))
    return result


# =======================================================================================
# The headline claim
# =======================================================================================


@pytest.mark.skipif(not FIXTURE.exists(), reason="run `uv run python -m tools.seed.ditwah`")
async def test_kandy_reaches_major_impact_a_day_before_landfall() -> None:
    """The claim this whole platform is built to make.

    Ditwah's rain reaches the central highlands on its way through, and Kandy is where the
    landslide risk concentrates. If the forecast only reaches major impact after the rain
    has already fallen, everything downstream - the alert, the preposition, the dispatch -
    is a response rather than an anticipation, and the platform is a reporting tool.
    """
    results = await replay(load_fixture(FIXTURE), district="LK-21", threshold_class=CLASS_MAJOR)

    lead = earliest_lead_time(results, CLASS_MAJOR)

    assert lead is not None, "Kandy never reached major impact before landfall"
    assert lead >= 24, f"only {lead}h of lead time; the demo claims a day"


@pytest.mark.skipif(not FIXTURE.exists(), reason="run `uv run python -m tools.seed.ditwah`")
async def test_the_forecast_does_not_flag_the_whole_country() -> None:
    """The failure that would make the lead-time test pass for the wrong reason.

    A forecast putting every division in Sri Lanka at major impact three days out has
    technically warned Kandy and has told nobody anything. The mock's rainfall curve was
    reshaped once already for exactly this: a flat national peak made every district issue
    an identical bulletin and let targeting logic look correct while doing nothing.
    """
    results = await replay(load_fixture(FIXTURE), district="LK-21", threshold_class=CLASS_MAJOR)
    fixture = load_fixture(FIXTURE)
    total_divisions = len(fixture["divisions"])

    at_peak = max(results, key=lambda point: point.written)

    assert at_peak.written < total_divisions * 0.8, (
        "nearly every division in the country produced a forecast row; the hazard is not "
        "being discriminated"
    )


@pytest.mark.skipif(not FIXTURE.exists(), reason="run `uv run python -m tools.seed.ditwah`")
async def test_the_replay_is_reproducible() -> None:
    """The fixture is frozen and the engine is pure, so two replays agree exactly.

    This is what a replay is for: an after-action review that produced different numbers
    each time it ran would answer nothing.
    """
    fixture = load_fixture(FIXTURE)

    first = await replay(fixture, district="LK-21")
    second = await replay(fixture, district="LK-21")

    assert first == second


# =======================================================================================
# The graph
# =======================================================================================


async def test_the_graph_runs_end_to_end_without_a_model_provider() -> None:
    """Build file 13: with OpenAI unreachable, forecasts are still produced with `method`
    unchanged."""
    result = await run_graph()

    assert result["status"] == "COMPLETED"
    assert result["output"]["method"] == "RULE_THRESHOLD"
    assert result["output"]["forecasts_written"] >= 1
    assert result["output"]["provenance"] == "DETERMINISTIC"


async def test_the_graph_never_pauses_for_a_person() -> None:
    """This agent has no human gate on purpose. It forecasts and it notifies; everything
    that acts on a forecast has its own gate."""
    result = await run_graph()

    assert "__interrupt__" not in result


async def test_a_run_writes_the_forecasts_and_links_the_triggers_to_them() -> None:
    """Without the link an after-action review can establish that a trigger fired and not
    whether it should have, which is the only question worth asking about a pre-agreed
    rule."""
    store = Store()

    await run_graph(divisions=[a_division(i) for i in range(1, 4)], store=store)

    assert store.forecasts
    assert store.firings
    for firing in store.firings:
        assert firing["forecast_id"], "a firing with no forecast cannot be reviewed"
        assert firing["action_taken"] in TRIGGER_ACTIONS


async def test_every_persisted_row_carries_a_non_empty_drivers_object() -> None:
    """The database CHECK requires it. Failing at the INSERT during a cyclone, after the
    forecast has been computed, is the worst place to find out."""
    store = Store()

    await run_graph(store=store)

    for row in store.forecasts:
        assert isinstance(row["drivers"], dict)
        assert row["drivers"]
        assert row["method"] in ("RULE_THRESHOLD", "MODEL")


async def test_divisions_with_no_expected_impact_do_not_produce_rows() -> None:
    """A row saying "no impact expected" for every division in the country, several times
    an hour, buries the forecasts somebody needs to read."""
    store = Store()

    await run_graph(feeds=Feeds(rain=5.0), store=store)

    assert store.forecasts == []


async def test_the_record_still_shows_the_whole_country_was_scored() -> None:
    """Carrying only the divisions above the threshold must not lose the fact that the
    others were looked at."""
    result = await run_graph(feeds=Feeds(rain=5.0), divisions=[a_division(i) for i in range(1, 6)])

    assert result["output"]["divisions_scored"] == 5
    assert result["output"]["forecasts_written"] == 0
    assert result["output"]["by_impact_class"]


async def test_the_narrative_reaches_the_persisted_row_in_three_languages() -> None:
    store = Store()

    await run_graph(store=store)

    narrative = store.forecasts[0]["drivers"]["_narrative"]
    assert set(narrative) == {"si", "ta", "en"}
    assert all(text.strip() for text in narrative.values())


async def test_the_exposure_denominators_reach_the_persisted_row() -> None:
    """ "340 of those households contain someone over 70" is the translation this agent
    exists to make, and it cannot be made from the impact class alone."""
    store = Store()

    await run_graph(store=store)

    exposure = store.forecasts[0]["drivers"]["_exposure"]
    assert exposure["households"] == 300
    assert exposure["elderly_households"] == 30


async def test_a_model_is_only_called_for_divisions_in_real_trouble() -> None:
    """Writing prose about a moderate-impact division several hundred times per generation
    is how an agent's cost ends up paging somebody at 3 a.m. during a cyclone."""
    prompts: list[str] = []

    async def counting(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps({"si": "x", "ta": "x", "en": "x"})

    # Zone 1 at 180 mm is below its 200 mm watch line: class 1, well under the bar.
    await run_graph(
        feeds=Feeds(rain=180.0),
        divisions=[a_division(1, zone=1)],
        call=counting,
    )

    assert prompts == []
    assert MODEL_NARRATE_FROM > PERSIST_FROM


async def test_a_graph_with_no_feeds_refuses_rather_than_reporting_a_quiet_day() -> None:
    """The worst possible way for a forecasting service to be broken is to complete
    successfully having scored nothing."""
    graph = build(memory_checkpointer())
    state = initial_state(
        agent="forecast",
        subject_type="hazard_event",
        subject_id="evt-x",
        correlation_id="c",
    )

    with pytest.raises(RuntimeError, match="no hazard feeds"):
        await graph.ainvoke(state, config_for("forecast:hazard_event:evt-x"))


# =======================================================================================
# Triggers
# =======================================================================================


def test_every_rule_proposes_an_action_the_schema_allows() -> None:
    """A rule naming an action the column rejects fails at the INSERT - after the
    notification has already gone out."""
    for rule in trigger_rules.RULES:
        assert rule.action in TRIGGER_ACTIONS


def test_no_rule_can_dispatch_or_spend() -> None:
    """Triggers notify. A forecast that could reach through to a dispatch or a payment
    would be a forecast that evacuates a district on a bad rainfall estimate."""
    assert set(TRIGGER_ACTIONS) == trigger_rules.NOTIFY_ONLY
    for rule in trigger_rules.RULES:
        assert "RELEASE" not in rule.action
        assert "DISBURSE" not in rule.action


def test_a_kandy_rule_does_not_fire_in_jaffna() -> None:
    kandy = a_division(1, zone=4)
    jaffna = DivisionExposure(
        gn_division_id="gn-j",
        gn_division_code="LK-41-01-001",
        ds_division_code="LK-41-01",
        district_code="LK-41",
        centroid_lon=80.0,
        centroid_lat=9.66,
        landslide_zone=4,
    )
    rule = next(r for r in trigger_rules.RULES if r.id == "kandy_landslide_preposition")

    assert rule.applies_to(kandy)
    assert not rule.applies_to(jaffna)


def test_a_trigger_records_the_forecast_that_fired_it() -> None:
    division = a_division(1, zone=4)
    score = ImpactScore(
        gn_division_id=division.gn_division_id,
        gn_division_code=division.gn_division_code,
        impact_class=CLASS_MAJOR,
        confidence=0.8,
        lead_time_hours=48,
        drivers=[
            Driver(factor="peak_rainfall_24h", value=160.0, threshold=200.0, contribution=3.0)
        ],
        expected_households_affected=300,
        expected_road_access_loss=True,
    )

    firings = trigger_rules.evaluate([score], {division.gn_division_id: division})

    assert firings
    for firing in firings:
        assert firing.score is score
        assert firing.rule.as_condition()["rule_id"] == firing.rule.id


def test_a_trigger_notifies_once_per_division_per_run() -> None:
    """A rule that fires every generation puts the same request in front of the same
    officer every fifteen minutes for three days, and the fourth one is ignored along with
    everything after it."""
    division = a_division(1, zone=4)
    score = ImpactScore(
        gn_division_id=division.gn_division_id,
        gn_division_code=division.gn_division_code,
        impact_class=CLASS_SEVERE,
        confidence=0.9,
        lead_time_hours=48,
        drivers=[
            Driver(factor="peak_rainfall_24h", value=260.0, threshold=200.0, contribution=4.0)
        ],
        expected_households_affected=300,
        expected_road_access_loss=True,
    )
    firings = trigger_rules.evaluate([score], {division.gn_division_id: division})
    ledger = trigger_rules.TriggerLedger()

    assert ledger.new_firings(firings) == firings
    assert ledger.new_firings(firings) == []


def test_a_rule_naming_an_action_the_schema_rejects_fails_at_construction() -> None:
    """Loudly, at import, rather than at the INSERT during an event."""
    with pytest.raises(ValueError, match="not an action the schema allows"):
        trigger_rules.TriggerRule(
            id="bad", action="NOTIFY_DS_PREPOSITION", scope="national", description="x"
        )


# =======================================================================================
# The evaluation seam
# =======================================================================================


async def test_the_forecast_agent_meets_its_calibration_gate() -> None:
    """Build file 13: confidence calibration on the fixture set, ECE below 0.15.

    `confidence` drives real decisions, so it has to mean something. This is the number
    that says whether it does, and it is the reason the fixture set deliberately contains
    cases the engine cannot get right - a gauge blackout, an unsurveyed division. Without
    them the low-confidence bins are empty and the calibration figure is vacuous.
    """
    from agent_svc.runtime.eval import evaluate

    report = await evaluate("forecast", Path("data/fixtures/smoke"))

    assert report.ece <= 0.15, f"ECE {report.ece:.3f}"
    assert report.passed


async def test_low_confidence_marks_the_forecasts_that_are_actually_wrong() -> None:
    """A confidence that does not fall when the inputs fail is decoration.

    Both blind-gauge cases are wrong, and both state 0.25. That is the bin doing its job.
    """
    from agent_svc.runtime.eval import evaluate

    report = await evaluate("forecast", Path("data/fixtures/smoke"))

    blind = [result for result in report.results if result.confidence < 0.3]
    assert blind, "no low-confidence cases; the calibration set has nothing to calibrate"
    assert not any(result.agent_correct for result in blind)


def test_the_eval_graph_is_not_the_production_graph() -> None:
    """The production graph talks to the Met Department, NBRO and core-api. A harness that
    had to stand all three up is a harness nobody runs before pushing."""
    from agent_svc.agents.forecast import SPEC

    assert SPEC.eval_build is not None
    assert SPEC.eval_build is not SPEC.build
