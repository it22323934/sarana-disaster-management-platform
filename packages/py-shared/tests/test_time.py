"""UTC storage, Colombo rendering, and landfall-relative disaster time."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sarana_shared.domain.time import (
    COLOMBO,
    DisasterClock,
    ensure_utc,
    format_colombo,
    format_relative,
    parse_relative,
    to_colombo,
)

# Cyclone Ditwah landfall on the east coast, 28 Nov 2025, 00:00 Colombo (UTC+5:30).
DITWAH_LANDFALL = datetime(2025, 11, 27, 18, 30, tzinfo=UTC)


def test_naive_datetimes_are_refused() -> None:
    """Guessing wrong shifts a disaster timeline by five and a half hours."""
    with pytest.raises(ValueError, match="naive datetime rejected"):
        ensure_utc(datetime(2025, 11, 28, 4, 30))  # noqa: DTZ001 - the point of the test


def test_colombo_is_utc_plus_five_thirty() -> None:
    local = to_colombo(DITWAH_LANDFALL)

    assert local.tzinfo is COLOMBO
    assert (local.hour, local.minute) == (0, 0)
    assert local.date().isoformat() == "2025-11-28"


def test_colombo_rendering_shows_the_offset() -> None:
    assert format_colombo(DITWAH_LANDFALL).endswith("+0530")


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        ("T+0", timedelta(0)),
        ("T-72h", timedelta(hours=-72)),
        ("T+14d", timedelta(days=14)),
        ("T+30m", timedelta(minutes=30)),
        ("T-7d", timedelta(days=-7)),
    ],
)
def test_relative_offsets_parse(offset: str, expected: timedelta) -> None:
    assert parse_relative(offset) == expected


def test_an_offset_without_a_unit_is_ambiguous_and_refused() -> None:
    with pytest.raises(ValueError, match="needs a unit"):
        parse_relative("T+14")


def test_rendering_picks_the_coarsest_exact_unit() -> None:
    assert format_relative(timedelta(days=1)) == "T+1d"
    assert format_relative(timedelta(hours=25)) == "T+25h"
    assert format_relative(timedelta(minutes=90)) == "T+90m"
    assert format_relative(timedelta(0)) == "T+0"


def test_the_clock_round_trips_the_red_alert_window() -> None:
    """Red alerts went out 72 hours ahead of Ditwah; that window is the anchor case."""
    clock = DisasterClock(landfall_at=DITWAH_LANDFALL)

    red_alert = clock.absolute("T-72h")

    assert to_colombo(red_alert).date().isoformat() == "2025-11-25"
    # 72 hours is exactly three days, so the default rendering coarsens to days.
    assert clock.relative(red_alert) == "T-3d"


def test_warning_surfaces_can_force_the_hours_operators_actually_say() -> None:
    """The Warn loop is defined in hours. Nobody at the DMC says "T-3d"."""
    clock = DisasterClock(landfall_at=DITWAH_LANDFALL)

    assert clock.relative(clock.absolute("T-72h"), unit="h") == "T-72h"
    assert format_relative(parse_relative("T-72h"), unit="h") == "T-72h"


def test_the_clock_normalises_a_non_utc_anchor() -> None:
    clock = DisasterClock(landfall_at=DITWAH_LANDFALL.astimezone(COLOMBO))

    assert clock.landfall_at.tzinfo is UTC
    assert clock.relative(clock.absolute("T+14d")) == "T+14d"
