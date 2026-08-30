"""Replay a scenario through the forecast agent, and assert what it would have said.

```bash
python -m agent_svc.agents.forecast.replay --scenario ditwah --assert-lead-time 24
```

This is the headline claim of the whole platform, made checkable: **Kandy's fragile slopes
reach major impact at least 24 hours before landfall.** Build file 13 is explicit that it
has to be a test rather than a hope, and this is the test. It exits non-zero when the claim
fails, so it can sit in CI beside the unit tests.

## What it actually does

Feeds the committed Ditwah fixture through the real graph, one timeline point at a time,
with no network, no database and no model provider. The nodes are the production nodes; only
the ports are fakes. An agent that had to be reimplemented to be replayable would be an
agent whose replay proves nothing about the agent.

## What the lead-time assertion means

For each timeline point before landfall, the replay records the highest impact class reached
in the target district. The claim holds if some point at or earlier than `-N` hours already
reached the asserted class. It is deliberately not "every division" - a forecast that put
every division in Kandy at major impact three days out would be useless in a different way,
and the report prints the division counts so that failure is visible too.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from agent_svc.agents.forecast.exposure import DivisionExposure, StationReading
from agent_svc.agents.forecast.graph import build_nodes
from agent_svc.agents.forecast.ports import HazardWindow
from agent_svc.agents.forecast.reconcile import SourceClaim
from agent_svc.agents.forecast.scoring import CLASS_MAJOR, ZoneThresholds

DEFAULT_FIXTURE: Final = Path("data/fixtures/ditwah/replay.json")

# The district the headline claim is about. Ditwah's rain reached the central highlands on
# its way through, and Kandy is where the landslide risk concentrates.
DEFAULT_DISTRICT: Final = "LK-21"


class FixtureFeeds:
    """The hazard feeds, served from a frozen snapshot.

    Implements `HazardFeeds`. A source claim is synthesised from the snapshot rather than
    stored, because what the Department *said* at a given hour is a function of the curve
    and storing both invites them to disagree.
    """

    def __init__(self, snapshot: dict[str, Any], fixture: dict[str, Any]) -> None:
        self._snapshot = snapshot
        self._fixture = fixture

    async def warned_districts(self) -> tuple[str, ...]:
        return tuple(self._fixture["districts"])

    async def observations(self) -> list[StationReading]:
        return [
            StationReading(
                station_id=row["station_id"],
                lon=row["lon"],
                lat=row["lat"],
                rainfall_mm_24h=row["rainfall_mm_24h"],
                reporting=row["reporting"],
            )
            for row in self._snapshot["observations"]
        ]

    async def district_forecast(self, *, district_code: str, hours: int) -> float:
        return float(
            self._snapshot["district_forecasts"].get(district_code, {}).get(str(hours), 0.0)
        )

    async def thresholds(self) -> dict[int, ZoneThresholds]:
        return {
            int(zone): ZoneThresholds(**values)
            for zone, values in self._fixture["thresholds"].items()
        }

    async def claims(self, *, district_codes: tuple[str, ...]) -> list[SourceClaim]:
        """One Met claim, scaled to how close landfall is.

        Not read from the fixture: the Department's escalation schedule is a property of the
        scenario, and duplicating it into the file would let the two drift.
        """
        hours_out = self._snapshot["hours_to_landfall"]
        level = "RED" if hours_out <= 12 else "AMBER" if hours_out <= 48 else "YELLOW"
        return [
            SourceClaim(
                source="DEPT_METEOROLOGY",
                level=level,
                scope_type="district",
                scope_code=district_codes[0] if district_codes else "LK",
                issued_at=datetime.fromisoformat(self._snapshot["now"]),
                headline=f"Cyclone Ditwah, {hours_out:.0f} hours to landfall",
            )
        ]


class FixtureDirectory:
    """Division exposure, served from the same snapshot. Implements `DivisionDirectory`."""

    def __init__(self, fixture: dict[str, Any]) -> None:
        self._rows = fixture["divisions"]

    async def divisions_in(self, district_codes: tuple[str, ...]) -> list[DivisionExposure]:
        wanted = set(district_codes)
        return [
            DivisionExposure(
                gn_division_id=row["gn_division_id"],
                gn_division_code=row["gn_division_code"],
                ds_division_code=row["ds_division_code"],
                district_code=row["district_code"],
                centroid_lon=row["centroid_lon"],
                centroid_lat=row["centroid_lat"],
                household_count=row["household_count"],
                population=row["population"],
                landslide_zone=row["landslide_zone"],
                flood_return_period_m=row["flood_return_period_m"],
                road_access_class=row["road_access_class"],
                cell_coverage_pct=row["cell_coverage_pct"],
                elderly_pct=row["elderly_pct"],
                under5_pct=row["under5_pct"],
            )
            for row in self._rows
            if row["district_code"] in wanted
        ]

    async def names(self, gn_division_ids: list[str]) -> dict[str, dict[str, str]]:
        wanted = set(gn_division_ids)
        return {
            row["gn_division_id"]: row["name"]
            for row in self._rows
            if row["gn_division_id"] in wanted
        }


@dataclass(frozen=True, slots=True)
class PointResult:
    """What the agent said at one point on the timeline."""

    hours_to_landfall: float
    scored: int
    written: int
    triggers: int
    hazard_level: str
    district_max_class: int
    district_at_or_above: int
    by_class: dict[str, int]


async def run_point(
    snapshot: dict[str, Any],
    fixture: dict[str, Any],
    *,
    district: str,
    threshold_class: int,
) -> PointResult:
    """Run every node in order for one timeline point.

    The nodes are called directly rather than through a compiled graph. The graph adds a
    checkpointer and an edge list; neither changes what a node computes, and a replay of
    nine points that wrote nine sets of checkpoints would be measuring LangGraph.
    """
    feeds = FixtureFeeds(snapshot, fixture)
    directory = FixtureDirectory(fixture)
    window = HazardWindow(
        hazard_event_id="ditwah-replay",
        hazard_type="CYCLONE",
        now=datetime.fromisoformat(snapshot["now"]),
        landfall_at=datetime.fromisoformat(fixture["landfall_at"]),
    )

    nodes = build_nodes(feeds=feeds, directory=directory, store=None, window=window)

    state: dict[str, Any] = {
        "agent": "forecast",
        "subject_type": "hazard_event",
        "subject_id": window.hazard_event_id,
        "correlation_id": f"replay-{snapshot['hours_to_landfall']:.0f}",
        "notes": [],
        "firings": [],
    }
    for name in (
        "ingest_feeds",
        "normalise_hazard",
        "reconcile_sources",
        "score_divisions",
        "attach_exposure",
        "explain",
        "check_triggers",
        "persist",
    ):
        update = await nodes[name](state)
        for key, value in update.items():
            if key in ("notes", "firings") and isinstance(value, list):
                state[key] = list(state.get(key, [])) + value
            else:
                state[key] = value

    in_district = [
        score for score in state.get("scores", []) if score["gn_division_code"].startswith(district)
    ]
    return PointResult(
        hours_to_landfall=snapshot["hours_to_landfall"],
        scored=state.get("scored_total", 0),
        written=len(state.get("scores", [])),
        triggers=len(state.get("firings", [])),
        hazard_level=state.get("reconciliation", {}).get("level", "NONE"),
        district_max_class=max((score["impact_class"] for score in in_district), default=0),
        district_at_or_above=sum(
            1 for score in in_district if score["impact_class"] >= threshold_class
        ),
        by_class=state.get("histogram", {}),
    )


def load_fixture(path: Path) -> dict[str, Any]:
    """Read the frozen scenario. Synchronous, and called before the event loop starts."""
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


async def replay(
    fixture: dict[str, Any] | Path,
    *,
    district: str = DEFAULT_DISTRICT,
    threshold_class: int = CLASS_MAJOR,
) -> list[PointResult]:
    if isinstance(fixture, Path):
        fixture = load_fixture(fixture)
    return [
        await run_point(snapshot, fixture, district=district, threshold_class=threshold_class)
        for snapshot in fixture["timeline"]
    ]


def earliest_lead_time(results: list[PointResult], threshold_class: int) -> float | None:
    """The greatest lead time at which the district reached the class, or None.

    "Greatest" because the claim is about how early the warning was available. A forecast
    that only reaches major impact at T-2h has technically reached it and has told nobody
    anything they could act on.
    """
    reached = [
        point.hours_to_landfall
        for point in results
        if point.hours_to_landfall > 0 and point.district_max_class >= threshold_class
    ]
    return max(reached) if reached else None


def render(results: list[PointResult], *, district: str) -> str:
    lines = [
        f"Ditwah replay - impact in {district}",
        "",
        f"{'lead':>6}  {'level':<9} {'scored':>7} {'written':>8} {'triggers':>9} "
        f"{'max':>4} {'at/above':>9}",
        "-" * 62,
    ]
    for point in results:
        lead = f"T{-point.hours_to_landfall:+.0f}h"
        lines.append(
            f"{lead:>6}  {point.hazard_level:<9} {point.scored:>7} {point.written:>8} "
            f"{point.triggers:>9} {point.district_max_class:>4} {point.district_at_or_above:>9}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agent_svc.agents.forecast.replay",
        description="Replay a scenario through the forecast agent and check its lead time.",
    )
    parser.add_argument("--scenario", default="ditwah")
    parser.add_argument("--fixture", type=Path, default=None)
    parser.add_argument("--district", default=DEFAULT_DISTRICT)
    parser.add_argument("--impact-class", type=int, default=CLASS_MAJOR)
    parser.add_argument(
        "--assert-lead-time",
        type=float,
        default=None,
        help="Fail unless the district reached the impact class at least this many hours "
        "before landfall.",
    )
    args = parser.parse_args(argv)

    path = args.fixture or Path(f"data/fixtures/{args.scenario}/replay.json")
    if not path.exists():
        sys.stderr.write(
            f"error: no fixture at {path}. Generate it with `uv run python -m tools.seed.ditwah`.\n"
        )
        return 2

    results = asyncio.run(replay(path, district=args.district, threshold_class=args.impact_class))
    sys.stdout.write(render(results, district=args.district) + "\n")

    earliest = earliest_lead_time(results, args.impact_class)
    if earliest is None:
        sys.stdout.write(
            f"\n{args.district} never reached impact class {args.impact_class} before landfall.\n"
        )
    else:
        sys.stdout.write(
            f"\n{args.district} first reached impact class {args.impact_class} "
            f"{earliest:.0f} hours before landfall.\n"
        )

    if args.assert_lead_time is None:
        return 0
    if earliest is not None and earliest >= args.assert_lead_time:
        sys.stdout.write(f"PASS: lead time {earliest:.0f}h >= {args.assert_lead_time:.0f}h\n")
        return 0

    sys.stderr.write(
        f"FAIL: needed impact class {args.impact_class} in {args.district} at least "
        f"{args.assert_lead_time:.0f}h before landfall; "
        + (f"got {earliest:.0f}h" if earliest is not None else "never reached it")
        + "\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
