"""One clock, one story.

The property build file 11 asks for: advancing the scenario produces consistent state
across all seven mocks. Seven mocks each reading their own `datetime.now()` would produce a
demo where NBRO issues its bulletin before the rain arrives, which is the one thing a
disaster simulation must not do.

Everything here is checked at a specific offset rather than "after some time passes",
because the clock is pinned. A test that has to sleep to observe a value is a test that
will be flaky on somebody else's laptop.
"""

from __future__ import annotations

from httpx import AsyncClient


async def _advance(client: AsyncClient, offset: str) -> None:
    response = await client.post("/mock/v1/scenario/advance", json={"to": offset})
    assert response.status_code == 200, response.text


async def test_loading_a_scenario_starts_before_landfall(client: AsyncClient) -> None:
    """`ditwah_kandy` starts at T-72h.

    Not at landfall. The three days before are where anticipatory action happens, and a
    scenario that opened at T+0 would skip the only part of the story where a forecast can
    still change an outcome.
    """
    response = await client.post("/mock/v1/scenario/load", json={"scenario_id": "ditwah_kandy"})

    assert response.status_code == 200
    assert response.json()["clock"]["offset"] == "T-3d"


async def test_an_unknown_scenario_is_refused(client: AsyncClient) -> None:
    """A typo in a scenario id must not silently load nothing."""
    response = await client.post("/mock/v1/scenario/load", json={"scenario_id": "nope"})

    assert response.status_code == 404


async def test_the_clock_refuses_to_run_backwards(client: AsyncClient) -> None:
    """Advancing to an earlier offset is refused, not applied.

    Rewinding would leave shelters holding people who have not yet arrived and claims
    received in the future. A scenario that needs an earlier state reloads.
    """
    await client.post("/mock/v1/scenario/load", json={"scenario_id": "ditwah_kandy"})
    await _advance(client, "T+24h")

    response = await client.post("/mock/v1/scenario/advance", json={"to": "T+6h"})

    assert response.status_code == 422
    assert "already at" in response.json()["detail"]


async def test_advancing_moves_every_mock_together(client: AsyncClient) -> None:
    """At T+24h all seven mocks describe the same moment of the same storm.

    The assertions are deliberately about *relationships between* the mocks rather than
    about individual values. A test pinning exact millimetres would fail every time the
    curve was tuned; these fail only when the mocks stop agreeing with each other, which
    is the thing that must never happen.
    """
    await client.post("/mock/v1/scenario/load", json={"scenario_id": "ditwah_kandy"})
    await _advance(client, "T+24h")

    state = (await client.get("/mock/v1/state")).json()
    # Checked in hours, not against the rendered offset: `format_relative` picks the
    # coarsest exact unit, so T+24h renders as "T+1d". Asserting on the rendering would
    # make this test about a string formatter rather than about where the clock is.
    assert state["clock"]["hours_since_landfall"] == 24.0
    now = state["clock"]["now"]

    # 1. Met: it has rained hard on the east coast and much less on the west.
    east = (
        await client.get("/met/v1/forecast/rainfall", params={"district": "LK-51", "hours": 24})
    ).json()["forecast"]
    west = (
        await client.get("/met/v1/forecast/rainfall", params={"district": "LK-11", "hours": 24})
    ).json()["forecast"]
    assert east["expected_mm"] > west["expected_mm"] * 2, (
        "the east coast must be hit far harder than the west, or targeting cannot be tested"
    )

    # 2. NBRO: bulletins are in force, and only where it actually rained.
    bulletins = (await client.get("/nbro/v1/bulletins")).json()["bulletins"]
    assert bulletins, "rain this heavy must have produced bulletins"
    covered = {code.rsplit("-", 1)[0] for b in bulletins for code in b["ds_division_codes"]}
    assert "LK-51" in covered
    assert "LK-11" not in covered, "Colombo must not be under a landslide bulletin in this storm"

    # 3. DMC: shelters in the affected districts hold people; elsewhere they do not.
    affected = (await client.get("/dmc/v1/shelters", params={"district": "LK-51"})).json()
    unaffected = (await client.get("/dmc/v1/shelters", params={"district": "LK-41"})).json()
    assert sum(s["current_occupancy"] for s in affected["shelters"]) > 0
    assert sum(s["current_occupancy"] for s in unaffected["shelters"]) == 0

    # 4. DMC: situation reports exist, and the newest one is not in the future.
    reports = (await client.get("/dmc/v1/situation-reports")).json()["situation_reports"]
    assert reports
    assert reports[0]["issued_at"] <= now

    # 5. Telco: coverage in a battered district is below its own normal-day baseline.
    from gov_mock.data.telco import baseline_coverage_pct

    coverage = (
        await client.get("/telco/v1/coverage", params={"gn_division_id": "LK-51-01-001"})
    ).json()["coverage"]
    assert coverage["percent"] < baseline_coverage_pct("LK-51-01-001"), (
        "cell sites must have degraded; a warning that still reaches everyone during a "
        "cyclone is the failure this mock exists to make visible"
    )

    # 6. Every mock timestamps against the same clock, not the wall clock.
    observation = (await client.get("/met/v1/observations", params={"station": "MET-020"})).json()[
        "observations"
    ][0]
    assert observation["observed_at"] == now == coverage["measured_at"]


async def test_the_same_offset_produces_the_same_data_twice(client: AsyncClient) -> None:
    """Reproducibility. The same scenario at the same hour is the same data.

    This is what makes a demo replayable and every other test in this suite stable. If it
    fails, something has started drawing from a shared running stream rather than from a
    generator keyed on the entity and the hour.
    """
    await client.post("/mock/v1/scenario/load", json={"scenario_id": "ditwah_kandy"})
    await _advance(client, "T+12h")
    first = (await client.get("/met/v1/observations")).json()

    second = (await client.get("/met/v1/observations")).json()
    assert first == second

    # And again after a reload that returns to the same point.
    await client.post("/mock/v1/scenario/load", json={"scenario_id": "ditwah_kandy"})
    await _advance(client, "T+12h")
    third = (await client.get("/met/v1/observations")).json()
    assert first == third


async def test_the_quiet_scenario_has_nothing_happening(client: AsyncClient) -> None:
    """`quiet` exists so "nothing fires when nothing is happening" is testable.

    An agent that raises an alert on a calm day is as broken as one that misses a cyclone,
    and it is much easier to ship, because every test written against a storm passes.
    """
    await client.post("/mock/v1/scenario/load", json={"scenario_id": "quiet"})

    warnings = await client.get("/met/v1/warnings")
    assert "<warning>" not in warnings.text

    bulletins = (await client.get("/nbro/v1/bulletins")).json()["bulletins"]
    assert bulletins == []

    orders = (await client.get("/dmc/v1/evacuation-orders")).json()["evacuation_orders"]
    assert orders == []


async def test_loading_a_scenario_discards_recorded_state(client: AsyncClient) -> None:
    """A reload starts clean.

    A scenario that kept the previous run's claims would replay differently the second
    time, which defeats the point of loading one.
    """
    await client.post(
        "/ndrsc/v1/claims",
        json={
            "client_reference": "SARANA-CLAIM-RESET",
            "household_reference": "HH-5101001-0001",
            "gn_division_code": "LK-51-01-001",
            "cost_schedule_version": "2025.11",
            "amount_lkr_cents": 100_000_00,
            "assessed_at": "2025-11-29T04:00:00+00:00",
            "approved_by": ["ds.kandy@sarana.lk"],
        },
    )
    assert (await client.get("/mock/v1/state")).json()["recorded"]["claims"] == 1

    await client.post("/mock/v1/scenario/load", json={"scenario_id": "ditwah_kandy"})

    assert (await client.get("/mock/v1/state")).json()["recorded"]["claims"] == 0
