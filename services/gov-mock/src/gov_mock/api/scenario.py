"""The control plane: load a scenario, advance the clock, configure chaos, read state.

Everything here is exempt from chaos injection. That is deliberate and it is the reason
`/mock/v1/` is in `EXEMPT_PREFIXES`: injecting failures into the endpoint that turns
injection off would make 100% chaos an unrecoverable state, and the first person to try it
would have to restart the container to get their demo back.

`advance` moves **one** clock, and every mock reads it. That is what makes "advancing to
T+24h produces consistent state across all seven mocks" a property rather than a
coincidence: rainfall, bulletins, shelter occupancy, claim ages, transfer settlement and
cell coverage are all functions of the same offset.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from gov_mock.api import pay
from gov_mock.api.deps import SimulatedNowDep, StateDep, mock_json
from gov_mock.data import dmc as dmc_data
from gov_mock.data import ndrsc as ndrsc_data
from gov_mock.state import KNOWN_SCENARIOS

router = APIRouter(prefix="/mock/v1", tags=["control"])


class ScenarioIn(BaseModel):
    """Which scenario to load."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1, max_length=64)


class AdvanceIn(BaseModel):
    """Where to move the simulated clock to."""

    model_config = ConfigDict(extra="forbid")

    to: str = Field(min_length=2, max_length=16, description="Landfall-relative, e.g. T+6h")


class ChaosIn(BaseModel):
    """Failure injection settings. Omitted fields keep their current value."""

    model_config = ConfigDict(extra="forbid")

    timeout_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    error_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    malformed_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    stale_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    latency_ms: int | None = Field(default=None, ge=0, le=60_000)
    # Lowered by tests so a timeout injection does not cost thirty seconds a call. Left
    # alone, it is longer than any adapter's read timeout, which is what makes the client
    # give up first — the behaviour actually under test.
    timeout_hold_seconds: float | None = Field(default=None, ge=0.0, le=120.0)
    stale_window_hours: float | None = Field(default=None, ge=0.0, le=168.0)


class SpeedIn(BaseModel):
    """How fast simulated time runs."""

    model_config = ConfigDict(extra="forbid")

    speed: float = Field(ge=0.0, le=3600.0, description="Multiple of real time; 0 pins the clock")


@router.post("/scenario/load", summary="Load a scenario and reset recorded state")
def load_scenario(payload: ScenarioIn, state: StateDep) -> Any:
    """Reset to the start of a scenario.

    Everything recorded — claims, transfers, messages, headcounts — is discarded. A
    scenario that kept the previous run's claims would replay differently the second time,
    which defeats the point of loading one.
    """
    if payload.scenario_id not in KNOWN_SCENARIOS:
        raise HTTPException(
            status_code=404,
            detail=(f"Unknown scenario {payload.scenario_id!r}. Known: {sorted(KNOWN_SCENARIOS)}"),
        )

    state.load_scenario(payload.scenario_id)
    clock = state.clock.state()
    return mock_json(
        {
            "scenario_id": payload.scenario_id,
            "clock": {
                "landfall_at": clock.landfall_at.isoformat(),
                "offset": clock.relative,
                "speed": clock.speed,
            },
            "recorded": state.recorded_counts(),
        }
    )


@router.post("/scenario/advance", summary="Jump the simulated clock forward")
def advance(payload: AdvanceIn, state: StateDep) -> Any:
    """Move the clock to a landfall-relative offset such as `T+6h`.

    Forward only. Rewinding would leave shelters holding people who have not yet arrived
    and claims received in the future; a scenario that needs an earlier state reloads.
    """
    try:
        state.clock.advance_to(payload.to)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    clock = state.clock.state()
    return mock_json(
        {
            "clock": {
                "landfall_at": clock.landfall_at.isoformat(),
                "now": state.clock.now().isoformat(),
                "offset": clock.relative,
                "speed": clock.speed,
            }
        }
    )


@router.post("/scenario/speed", summary="Set how fast simulated time runs")
def set_speed(payload: SpeedIn, state: StateDep) -> Any:
    """Run simulated time at a multiple of real time, or pin it with 0.

    Pinned is the default. A live demo can set 60 to run an hour a minute; a test never
    should, because a test that has to sleep to observe a value is one that will be flaky
    on somebody else's laptop.
    """
    state.clock.set_speed(payload.speed)
    clock = state.clock.state()
    return mock_json({"clock": {"offset": clock.relative, "speed": clock.speed}})


@router.post("/chaos", summary="Configure failure injection")
def configure_chaos(payload: ChaosIn, state: StateDep) -> Any:
    """Change one or more injection rates. Omitted fields keep their current value."""
    changes = {key: value for key, value in payload.model_dump().items() if value is not None}
    try:
        config = state.chaos.configure(**changes)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return mock_json({"chaos": config.as_dict(), "injections": dict(state.chaos.injections)})


@router.get("/state", summary="Everything the mocks currently hold")
def read_state(state: StateDep, now: SimulatedNowDep) -> Any:
    """One view of the whole simulation, for a demo operator or a test.

    Deliberately includes the injection counters. "Why did that call fail?" is answered
    here rather than by reading logs, which during a demo is the difference between a
    ten-second answer and a lost audience.
    """
    clock = state.clock.state()
    hours = state.clock.hours_since_landfall()

    displaced = sum(
        (
            state.occupancy_counts[location.location_id].occupancy
            if location.location_id in state.occupancy_counts
            else dmc_data.modelled_occupancy(location, hours_since_landfall=hours, seed=state.seed)
        )
        for location in state.locations
    )

    return mock_json(
        {
            "scenario_id": state.scenario_id,
            "seed": state.seed,
            "clock": {
                "landfall_at": clock.landfall_at.isoformat(),
                "now": now.isoformat(),
                "offset": clock.relative,
                "hours_since_landfall": round(hours, 2),
                "speed": clock.speed,
            },
            "chaos": state.chaos.config.as_dict(),
            "injections": dict(state.chaos.injections),
            "recorded": state.recorded_counts(),
            "derived": {
                "persons_displaced": displaced,
                "cost_schedule_version": ndrsc_data.CURRENT_VERSION,
            },
            "transfers": pay.transfers_for_state(state, now),
        }
    )
