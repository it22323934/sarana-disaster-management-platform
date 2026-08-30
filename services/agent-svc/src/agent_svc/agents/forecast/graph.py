r"""The forecast and impact agent.

```
START -> ingest_feeds -> normalise_hazard -> reconcile_sources -> score_divisions
      -> attach_exposure -> explain -> check_triggers -> persist -> END
```

Eight nodes and **no interrupt**. This agent has no human gate, on purpose: it produces a
forecast and it notifies. Everything downstream that acts on a forecast - drafting a public
alert, releasing a dispatch, moving money - has its own gate and its own agent. A forecast
that could reach through to any of those would be a forecast that could evacuate a district
on a bad rainfall estimate.

## Where the model is used, and where it is not

Two nodes call one, and neither of them decides anything:

**`reconcile_sources`** writes the explanation when Met and NBRO disagree. It cannot lower
the hazard level below the most severe source - that floor is applied to its output, not
requested in its prompt.

**`explain`** turns the drivers into trilingual prose. Output containing a number that is
not in the drivers is discarded whole.

`score_divisions` reaches no model at all, which is what makes the degraded path
uninteresting: with OpenAI unreachable the classes, the confidences and the triggers are
byte-identical, and only the written English changes.

## What a run covers

The districts a source has actually warned about, not the country. Scoring all 14,022
divisions every generation would write a "no impact expected" row for every division in Sri
Lanka several times an hour and bury the forecasts somebody needs to read.

Within those districts, rows are written for divisions at class 1 and above. Class 0 means
the rain is not within striking distance of the division's own threshold, and a row saying
so is noise in a table whose whole purpose is to be scanned during an emergency.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Annotated, Any, Final

import structlog
from langgraph.graph import END, START, StateGraph

from agent_svc.agents.forecast import narrative as narrate
from agent_svc.agents.forecast import reconcile as reconciler
from agent_svc.agents.forecast import triggers as trigger_rules
from agent_svc.agents.forecast.exposure import (
    DivisionExposure,
    DivisionRainfall,
    StationReading,
    downscale,
    rainfall_at,
)
from agent_svc.agents.forecast.ports import (
    DivisionDirectory,
    ForecastStore,
    HazardFeeds,
    HazardWindow,
    ModelCall,
)
from agent_svc.agents.forecast.scoring import (
    CLASS_LOW,
    CLASS_MAJOR,
    CLASS_MODERATE,
    ImpactModel,
    ImpactScore,
    RuleThresholdModel,
    thresholds_for,
)
from agent_svc.runtime.nodes import audit_write, rg_append
from agent_svc.runtime.registry import AgentSpec
from agent_svc.runtime.state import AgentState

_log = structlog.get_logger(__name__)

AGENT: Final = "forecast"
SUBJECT_TYPE: Final = "hazard_event"

# The forward windows the Department publishes, and the ones the engine compares against a
# 24-hour threshold. Not configurable: `gov_mock` refuses any other value with a 422, and a
# window the source will not serve is a window that produces a silent gap.
FORECAST_WINDOWS: Final[tuple[int, ...]] = (24, 48, 72)

# A forecast is written for divisions at or above this class. See the module docstring.
PERSIST_FROM: Final = CLASS_LOW

# A narrative is generated for divisions at or above this class. Below it the static
# template is used, which says the same facts.
NARRATE_FROM: Final = CLASS_MODERATE

# A *model* is called only at or above this class. Spending tokens writing prose about a
# division at moderate impact, several hundred times per generation, is how an agent's cost
# ends up paging somebody at 3 a.m. during a cyclone.
MODEL_NARRATE_FROM: Final = CLASS_MAJOR

# How long a forecast is treated as current. Longer than the generation interval so there is
# no gap between successive runs, and short enough that a stale row is visibly stale.
VALIDITY_HOURS: Final = 6


class ForecastState(AgentState, total=False):
    """The forecast run's own state, on top of the shared base.

    Scores are carried between nodes and are the bulk of the checkpoint. Narratives are
    not: they are attached at `explain` and consumed by `persist` in the same superstep,
    and holding three languages of prose for a hundred divisions through every later
    checkpoint would put a page of text into every resume for no benefit.
    """

    district_codes: list[str]
    claims: list[dict[str, Any]]
    scored_total: int
    histogram: dict[str, int]
    reconciliation: dict[str, Any]
    scores: list[dict[str, Any]]
    exposure: dict[str, dict[str, Any]]
    narratives: dict[str, dict[str, str]]
    firings: Annotated[list[dict[str, Any]], list.__add__]
    written: int


# ---------------------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------------------


def build_nodes(
    *,
    feeds: HazardFeeds,
    directory: DivisionDirectory,
    store: ForecastStore | None,
    window: HazardWindow,
    model: ImpactModel | None = None,
    call: ModelCall | None = None,
    audit: Any = None,
    graph_writer: Any = None,
) -> dict[str, Any]:
    """Build the eight nodes, closed over their dependencies.

    Closures rather than a class because LangGraph nodes are functions and a class would
    add a layer whose only job is to hold four attributes. Everything a node touches
    arrives here, which is what makes the whole agent runnable against fakes.
    """
    engine: ImpactModel = model or RuleThresholdModel()

    async def ingest_feeds(state: ForecastState) -> dict[str, Any]:
        """Read the feeds. The only node that talks to a government system."""
        districts = await feeds.warned_districts()
        observations = await feeds.observations()
        claims = await feeds.claims(district_codes=districts)

        _log.info(
            "forecast_feeds_ingested",
            districts=list(districts),
            stations=len(observations),
            silent=sum(1 for reading in observations if not reading.reporting),
            claims=len(claims),
        )
        return {
            "district_codes": list(districts),
            "claims": [_claim_as_dict(claim) for claim in claims],
            # Readings are not put in state: forty stations of raw gauge data would ride in
            # every subsequent checkpoint, and `score_divisions` re-reads them from the
            # feed in the same run. A checkpoint holds references, not payloads.
            "notes": [f"ingested {len(observations)} station readings"],
        }

    async def normalise_hazard(state: ForecastState) -> dict[str, Any]:
        """Check the run has something to work with, before spending anything on it."""
        districts = state.get("district_codes", [])
        claims = state.get("claims", [])
        if not districts:
            _log.warning(
                "forecast_no_warned_districts",
                impact="no source has issued against any district; this run scores nothing",
            )
        return {"notes": [f"{len(claims)} source claims across {len(districts)} districts"]}

    async def reconcile_sources(state: ForecastState) -> dict[str, Any]:
        """Decide the hazard level where sources disagree.

        The model is called only when they actually do, which is a minority of hours. A
        token spent agreeing with an agreement buys the answer the floor gives for free.
        """
        claims = [_claim_from_dict(raw) for raw in state.get("claims", [])]
        result = await reconciler.reconcile(claims, call=call)

        _log.info(
            "forecast_sources_reconciled",
            level=result.level,
            method=result.method,
            disagreed=reconciler.sources_disagree(claims),
        )
        return {
            "reconciliation": {
                "level": result.level,
                "severity": result.severity,
                "chosen_source": result.chosen_source,
                "rationale": result.rationale,
                "confidence": result.confidence,
                "method": result.method,
            },
            "notes": [f"hazard level {result.level} ({result.method})"],
        }

    async def score_divisions(state: ForecastState) -> dict[str, Any]:
        """The deterministic core. No model, no clock, no network beyond the feeds."""
        districts = tuple(state.get("district_codes", []))
        if not districts:
            return {"scores": [], "notes": ["nothing warned; no divisions scored"]}

        divisions = await directory.divisions_in(districts)
        observations = await feeds.observations()
        thresholds = await feeds.thresholds()

        forecasts = await _district_forecasts(feeds, districts)
        district_observed = _district_means(observations, divisions)

        scores: list[ImpactScore] = []
        for division in divisions:
            rainfall = _rainfall_for(division, observations, forecasts, district_observed)
            scores.append(
                engine.score(
                    division,
                    rainfall,
                    thresholds=thresholds_for(division.landslide_zone, thresholds),
                    # -1 asks the engine to report the window that peaked, which is the
                    # honest lead time: "class 3 within 48 hours".
                    lead_time_hours=-1,
                )
            )

        by_class = _histogram(scores)
        # Only divisions that will produce a row travel onward. During Ditwah the Met
        # Department warns every district in the country, so a national Amber puts all
        # 14,022 divisions through this node - and carrying the ones at class 0 would put
        # half a megabyte of "no impact expected" into every checkpoint of every run, for
        # rows that are never written and text nobody reads.
        #
        # The histogram is kept, so the record still shows the whole country was looked at.
        carried = [score for score in scores if score.impact_class >= PERSIST_FROM]

        _log.info(
            "forecast_divisions_scored",
            divisions=len(scores),
            carried=len(carried),
            by_class=by_class,
            method=engine.method,
            version=engine.version,
        )
        return {
            "scores": [score.model_dump(mode="json") for score in carried],
            "scored_total": len(scores),
            "histogram": {str(klass): count for klass, count in by_class.items()},
            "notes": [f"scored {len(scores)} divisions: {by_class}"],
        }

    async def attach_exposure(state: ForecastState) -> dict[str, Any]:
        """The denominators a person reads: households, elderly, under-5, coverage.

        Separate from scoring because these do not move the class. They are what turns
        "class 3" into "340 of those households contain someone over 70", which is the
        translation this whole agent exists to make.
        """
        districts = tuple(state.get("district_codes", []))
        if not districts:
            return {"exposure": {}}

        divisions = {
            division.gn_division_id: division
            for division in await directory.divisions_in(districts)
        }

        exposure: dict[str, dict[str, Any]] = {}
        for raw in state.get("scores", []):
            division = divisions.get(raw["gn_division_id"])
            if division is None:
                continue
            exposure[raw["gn_division_id"]] = {
                "households": division.household_count,
                "population": division.population,
                "elderly_households": division.elderly_households,
                "under5_households": division.under5_households,
                "road_access_class": division.road_access_class,
                "cell_coverage_pct": division.cell_coverage_pct,
                "ds_division_code": division.ds_division_code,
                "district_code": division.district_code,
            }
        return {
            "exposure": exposure,
            "notes": [f"exposure attached for {len(exposure)} divisions"],
        }

    async def explain(state: ForecastState) -> dict[str, Any]:
        """Trilingual prose, from the drivers and nothing else."""
        wanted = [
            ImpactScore.model_validate(raw)
            for raw in state.get("scores", [])
            if raw["impact_class"] >= NARRATE_FROM
        ]
        if not wanted:
            return {"narratives": {}}

        names = await directory.names([score.gn_division_id for score in wanted])

        narratives: dict[str, dict[str, str]] = {}
        generated = 0
        for score in wanted:
            # The model only writes about divisions in real trouble. Below that the static
            # template says the same facts, and the tokens buy nothing.
            writer = call if score.impact_class >= MODEL_NARRATE_FROM else None
            result = await narrate.explain(
                score, division_name=names.get(score.gn_division_id), call=writer
            )
            narratives[score.gn_division_id] = result.text
            generated += 1 if result.method == "LLM" else 0

        _log.info(
            "forecast_narratives_written",
            divisions=len(narratives),
            model_written=generated,
            template_written=len(narratives) - generated,
        )
        return {
            "narratives": narratives,
            "notes": [f"{generated} model narratives, {len(narratives) - generated} template"],
        }

    async def check_triggers(state: ForecastState) -> dict[str, Any]:
        """Evaluate the pre-agreed rules. They notify; they do not dispatch or spend."""
        districts = tuple(state.get("district_codes", []))
        if not districts:
            return {"firings": []}

        divisions = {
            division.gn_division_id: division
            for division in await directory.divisions_in(districts)
        }
        scores = [ImpactScore.model_validate(raw) for raw in state.get("scores", [])]
        firings = trigger_rules.evaluate(scores, divisions)

        summary = trigger_rules.summarise(firings)
        if firings:
            _log.info("forecast_triggers_fired", **summary)
        return {
            "firings": [_firing_as_dict(firing) for firing in firings],
            "notes": [f"{summary['fired']} anticipatory triggers fired"],
        }

    async def persist(state: ForecastState) -> dict[str, Any]:
        """Write the forecasts, link the firings to them, and record the run.

        Last node, and the only one that writes. Everything above it is pure enough to
        replay, which is what makes `replay.py` an honest reconstruction of what the agent
        would have said rather than a separate implementation of it.
        """
        scores = [raw for raw in state.get("scores", []) if raw["impact_class"] >= PERSIST_FROM]
        exposure = state.get("exposure", {})
        narratives = state.get("narratives", {})

        rows = [
            _forecast_row(
                raw,
                window=window,
                exposure=exposure.get(raw["gn_division_id"], {}),
                narrative=narratives.get(raw["gn_division_id"], {}),
                correlation_id=str(state.get("correlation_id", "")),
                reconciliation=state.get("reconciliation", {}),
            )
            for raw in scores
        ]

        forecast_ids: list[str] = []
        if store is not None and rows:
            forecast_ids = await store.save_forecasts(rows)
            by_division = dict(
                zip([row["gn_division_id"] for row in rows], forecast_ids, strict=True)
            )
            firings = [
                {
                    **firing,
                    "hazard_event_id": window.hazard_event_id,
                    "forecast_id": by_division.get(firing["gn_division_id"]),
                }
                for firing in state.get("firings", [])
            ]
            if firings:
                await store.save_firings(firings)
        elif rows:
            _log.info(
                "forecast_not_persisted",
                rows=len(rows),
                impact="no store configured; this run produced forecasts and wrote none",
            )

        observations = [
            {
                "subject_type": "gn_division",
                "subject_id": raw["gn_division_id"],
                "observation": "predicted_impact",
                "value": raw["impact_class"],
                "confidence": raw["confidence"],
                "source": f"{AGENT}:{engine.method}:{engine.version}",
            }
            for raw in scores
            if raw["impact_class"] >= CLASS_MODERATE
        ]
        await rg_append(state, observations=observations, writer=graph_writer)

        audited = await audit_write(
            state,
            action="forecast.impact.generated",
            subject=window.hazard_event_id,
            detail={
                "districts": state.get("district_codes", []),
                "divisions_scored": state.get("scored_total", 0),
                "by_impact_class": state.get("histogram", {}),
                "forecasts_written": len(rows),
                "triggers_fired": len(state.get("firings", [])),
                "method": engine.method,
                "model_version": engine.version,
                "hazard_level": state.get("reconciliation", {}).get("level"),
            },
            writer=audit,
        )

        return {
            **audited,
            "written": len(rows),
            "status": "COMPLETED",
            "output": {
                "hazard_event_id": window.hazard_event_id,
                "districts": state.get("district_codes", []),
                "divisions_scored": state.get("scored_total", 0),
                "by_impact_class": state.get("histogram", {}),
                "forecasts_written": len(rows),
                "triggers_fired": len(state.get("firings", [])),
                "method": engine.method,
                "model_version": engine.version,
                "confidence": state.get("reconciliation", {}).get("confidence", 0.5),
                "reasoning": state.get("reconciliation", {}).get("rationale", ""),
                "needs_human_review": False,
                "provenance": "DETERMINISTIC",
            },
        }

    return {
        "ingest_feeds": ingest_feeds,
        "normalise_hazard": normalise_hazard,
        "reconcile_sources": reconcile_sources,
        "score_divisions": score_divisions,
        "attach_exposure": attach_exposure,
        "explain": explain,
        "check_triggers": check_triggers,
        "persist": persist,
    }


# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------


async def _district_forecasts(
    feeds: HazardFeeds, districts: tuple[str, ...]
) -> dict[str, dict[int, float]]:
    """Expected rainfall per district per forward window.

    Fetched once per district rather than once per division: there are 24 divisions per
    district in the seed and several hundred in reality, and the Department publishes by
    district anyway.
    """
    return {
        code: {
            hours: await feeds.district_forecast(district_code=code, hours=hours)
            for hours in FORECAST_WINDOWS
        }
        for code in districts
    }


def _district_means(
    observations: list[StationReading], divisions: list[DivisionExposure]
) -> dict[str, float]:
    """Mean observed rainfall across each district's divisions.

    The denominator the per-division downscaling is a ratio against. Computed from the
    interpolated division values rather than from the stations directly, so a district
    with one gauge in a corner is not represented by that corner.
    """
    by_district: dict[str, list[float]] = {}
    for division in divisions:
        value, _, _ = rainfall_at(division.centroid_lon, division.centroid_lat, observations)
        by_district.setdefault(division.district_code, []).append(value)
    return {
        code: (sum(values) / len(values) if values else 0.0) for code, values in by_district.items()
    }


def _rainfall_for(
    division: DivisionExposure,
    observations: list[StationReading],
    forecasts: dict[str, dict[int, float]],
    district_observed: dict[str, float],
) -> DivisionRainfall:
    """One division's observed and expected rainfall."""
    observed, used, silent = rainfall_at(division.centroid_lon, division.centroid_lat, observations)
    district = forecasts.get(division.district_code, {})
    mean = district_observed.get(division.district_code, 0.0)
    return DivisionRainfall(
        observed_24h=observed,
        expected_24h=downscale(district.get(24, 0.0), observed, mean),
        expected_48h=downscale(district.get(48, 0.0), observed, mean),
        expected_72h=downscale(district.get(72, 0.0), observed, mean),
        stations_used=used,
        stations_silent=silent,
    )


def _histogram(scores: list[ImpactScore]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for score in scores:
        counts[score.impact_class] = counts.get(score.impact_class, 0) + 1
    return dict(sorted(counts.items()))


def _claim_as_dict(claim: reconciler.SourceClaim) -> dict[str, Any]:
    return {
        "source": claim.source,
        "level": claim.level,
        "scope_type": claim.scope_type,
        "scope_code": claim.scope_code,
        "issued_at": claim.issued_at.isoformat() if claim.issued_at else None,
        "headline": claim.headline,
    }


def _claim_from_dict(raw: dict[str, Any]) -> reconciler.SourceClaim:
    issued = raw.get("issued_at")
    return reconciler.SourceClaim(
        source=raw["source"],
        level=raw["level"],
        scope_type=raw["scope_type"],
        scope_code=raw["scope_code"],
        issued_at=datetime.fromisoformat(issued) if issued else None,
        headline=raw.get("headline", ""),
    )


def _firing_as_dict(firing: trigger_rules.Firing) -> dict[str, Any]:
    return {
        "rule_id": firing.rule.id,
        "gn_division_id": firing.score.gn_division_id,
        "gn_division_code": firing.score.gn_division_code,
        "condition": firing.rule.as_condition(),
        "action_taken": firing.action,
        "notes": firing.notes,
    }


def _forecast_row(
    raw: dict[str, Any],
    *,
    window: HazardWindow,
    exposure: dict[str, Any],
    narrative: dict[str, str],
    correlation_id: str,
    reconciliation: dict[str, Any],
) -> dict[str, Any]:
    """One `hazard.impact_forecast` row, in the shape the column set takes."""
    score = ImpactScore.model_validate(raw)
    return {
        "hazard_event_id": window.hazard_event_id,
        "gn_division_id": score.gn_division_id,
        "gn_division_code": score.gn_division_code,
        "generated_at": window.now,
        "valid_from": window.now,
        "valid_to": window.now + timedelta(hours=VALIDITY_HOURS),
        "impact_class": score.impact_class,
        "confidence": score.confidence,
        "lead_time_hours": score.lead_time_hours,
        "method": score.method,
        "model_version": score.model_version,
        # A JSONB object, not a list: `hazard.impact_forecast` has a CHECK requiring one.
        # The narrative and the exposure ride alongside the drivers because they are the
        # same explanation in different forms, and a UI showing a forecast wants all three.
        "drivers": {
            **score.drivers_as_object(),
            "_narrative": narrative,
            "_exposure": exposure,
            "_hazard_level": reconciliation.get("level"),
        },
        "expected_households_affected": score.expected_households_affected,
        "expected_road_access_loss": score.expected_road_access_loss,
        "correlation_id": correlation_id,
    }


# ---------------------------------------------------------------------------------------


def build(
    checkpointer: Any,
    *,
    feeds: HazardFeeds | None = None,
    directory: DivisionDirectory | None = None,
    store: ForecastStore | None = None,
    window: HazardWindow | None = None,
    model: ImpactModel | None = None,
    call: ModelCall | None = None,
    audit: Any = None,
    graph_writer: Any = None,
) -> Any:
    """Compile the graph.

    The dependencies are optional so `AgentRegistry.compile_all` can build this at boot the
    same way it builds every other agent, and so a test can supply fakes. A graph compiled
    with no feeds refuses at its first node rather than producing an empty forecast that
    looks like a quiet day.
    """
    if feeds is None or directory is None:
        feeds = feeds or _RefusingFeeds()
        directory = directory or _RefusingDirectory()

    nodes = build_nodes(
        feeds=feeds,
        directory=directory,
        store=store,
        window=window or HazardWindow("unknown", "FLOOD", datetime.now(UTC)),
        model=model,
        call=call,
        audit=audit,
        graph_writer=graph_writer,
    )

    builder = StateGraph(ForecastState)
    for name, node in nodes.items():
        builder.add_node(name, node)

    order = list(nodes)
    builder.add_edge(START, order[0])
    for current, following in pairwise(order):
        builder.add_edge(current, following)
    builder.add_edge(order[-1], END)

    return builder.compile(checkpointer=checkpointer)


class _RefusingFeeds:
    """Stands in when the service booted without gov-mock credentials.

    Refuses loudly at the first node. The alternative - returning nothing - produces a run
    that scores zero divisions and completes, which is indistinguishable from a quiet day
    and is the worst possible way for a forecasting service to be broken.
    """

    async def _refuse(self) -> Any:
        raise RuntimeError(
            "The forecast agent has no hazard feeds configured. Set the gov-mock client "
            "credentials (make service-clients) and restart; running without them would "
            "report a quiet day during a cyclone."
        )

    async def claims(self, *, district_codes: tuple[str, ...]) -> Any:
        return await self._refuse()

    async def observations(self) -> Any:
        return await self._refuse()

    async def district_forecast(self, *, district_code: str, hours: int) -> Any:
        return await self._refuse()

    async def thresholds(self) -> Any:
        return await self._refuse()

    async def warned_districts(self) -> Any:
        return await self._refuse()


class _RefusingDirectory:
    """Stands in when core-api is unreachable. Same reasoning as `_RefusingFeeds`."""

    async def divisions_in(self, district_codes: tuple[str, ...]) -> Any:
        raise RuntimeError(
            "The forecast agent cannot reach core-api for division exposure. Without it "
            "every division would score against a default zone and the forecast would be "
            "confidently wrong."
        )

    async def names(self, gn_division_ids: list[str]) -> dict[str, dict[str, str]]:
        return {}


SPEC: Final = AgentSpec(
    name=AGENT,
    subject_type=SUBJECT_TYPE,
    build=build,
    description=(
        "Turns rainfall forecasts into per-GN-division impact predictions with lead time, "
        "confidence and the drivers that produced them. Rule-based threshold engine; no "
        "trained model exists."
    ),
    degraded_note=(
        "Scoring never touches a model, so the impact classes, confidences and "
        "anticipatory triggers are identical with the provider down. Source reconciliation "
        "falls back to the most severe source - which is also the floor it applies when "
        "the model is up - and narratives fall back to a static trilingual template. "
        "Nothing about the forecast changes except the written English."
    ),
    gated=False,
)
