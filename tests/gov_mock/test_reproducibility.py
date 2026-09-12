"""Every synthetic series is a pure function of its inputs, across processes.

Each mock's docstring makes this claim - "the same simulated hour produces the same reading
on every machine and every replay" - and the whole demo rests on it. A scenario replayed
before a ministry has to show the same weather it showed in rehearsal.

It was false. Nine call sites seeded `random.Random` from `hash()` of a tuple containing a
string, and **Python randomises string hashing per process**. Nothing raised; the mock
simply returned 67.9 mm, then 54.4 mm, then 48.6 mm for the same station and the same hour
in three consecutive runs. Any test that pinned a value would have been quietly flaky, and
the Ditwah replay the forecast agent is judged against would have been unrepeatable.

These tests run the derivation in a **subprocess**, because in-process repetition cannot
see the bug: within one interpreter `hash()` is perfectly stable. That is exactly why it
survived a suite that already had 122 tests over these mocks.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

from gov_mock.data import derive

RUNS = 3


def in_fresh_processes(body: str) -> list[str]:
    """Run a snippet in `RUNS` separate interpreters and collect what each printed.

    Separate processes, not separate calls: a per-process hash seed is identical to itself
    all day long.
    """
    script = textwrap.dedent(body)
    return [
        subprocess.run(  # noqa: S603 - our own script, no shell, no user input
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for _ in range(RUNS)
    ]


def test_the_same_hour_produces_the_same_rainfall_in_every_process() -> None:
    """The headline claim, and the one the Ditwah replay depends on."""
    outputs = in_fresh_processes("""
        from gov_mock.data import met
        station = met.STATIONS[5]
        print([met.rainfall_mm_24h(station, hours_since_landfall=h, seed=42)
               for h in (-48.0, -24.0, 0.0, 24.0)])
    """)

    assert len(set(outputs)) == 1, f"rainfall differs between processes: {outputs}"


def test_station_outages_are_reproducible() -> None:
    """A station that is down in rehearsal must be down in the demo.

    Otherwise the coverage gap the platform is meant to surface moves between runs, and
    the one screen that shows it becomes untrustworthy.
    """
    outputs = in_fresh_processes("""
        from gov_mock.data import met
        print([met.is_reporting(s, hours_since_landfall=0.0, seed=42) for s in met.STATIONS])
    """)

    assert len(set(outputs)) == 1, f"outages differ between processes: {outputs}"


def test_telco_coverage_is_reproducible() -> None:
    outputs = in_fresh_processes("""
        from gov_mock.data import telco
        print(telco.coverage_for("LK-21-01-001", hours_since_landfall=0.0, seed=42))
    """)

    assert len(set(outputs)) == 1, f"coverage differs between processes: {outputs}"


def test_shelter_occupancy_is_reproducible() -> None:
    outputs = in_fresh_processes("""
        from gov_mock.data import dmc
        location = dmc.build_locations(seed=42)[0]
        print(dmc.modelled_occupancy(location, hours_since_landfall=24.0, seed=42))
    """)

    assert len(set(outputs)) == 1, f"occupancy differs between processes: {outputs}"


def test_the_seed_helper_is_stable_across_processes() -> None:
    """The fix itself, tested directly so a regression names the cause rather than a
    symptom three modules away."""
    outputs = in_fresh_processes("""
        from gov_mock.data.derive import seed_for
        print(seed_for(42, "MET-006", -24))
    """)

    assert len(set(outputs)) == 1
    assert outputs[0] == str(derive.seed_for(42, "MET-006", -24))


def test_different_inputs_give_different_seeds() -> None:
    """A stable seed that ignored its arguments would pass every test above."""
    seeds = {derive.seed_for(42, "MET-006", hour) for hour in range(-48, 48, 6)}

    assert len(seeds) == 16
