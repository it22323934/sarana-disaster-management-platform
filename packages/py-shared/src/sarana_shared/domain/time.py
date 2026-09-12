"""Time helpers.

Conventions:
  - Store UTC (timestamptz). Render in Asia/Colombo (UTC+5:30).
  - Never store a naive datetime. Never do timezone maths in the frontend.
  - Disaster timelines are expressed relative to landfall as T-72h / T+0 / T+14d.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

COLOMBO: Final = ZoneInfo("Asia/Colombo")

# T+0, T-72h, T+14d, T+30m, T-7d. Case-insensitive on the unit.
_RELATIVE_PATTERN: Final = re.compile(r"^T(?P<sign>[+-])(?P<value>\d+)(?P<unit>[mhd])?$", re.I)

_UNIT_TO_TIMEDELTA: Final[dict[str, timedelta]] = {
    "m": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
}

_SECONDS_PER_DAY: Final = 86_400
_SECONDS_PER_HOUR: Final = 3_600

# Units an offset may be rendered in. Weeks and months are deliberately absent:
# a disaster timeline that has moved to weeks belongs to the Learn loop, which
# speaks in calendar dates rather than offsets.
type RelativeUnit = Literal["m", "h", "d"]


def utc_now() -> datetime:
    """Current instant, timezone-aware, in UTC."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Return value in UTC, rejecting naive datetimes.

    Raises:
        ValueError: if value has no timezone. A naive datetime is always a bug here -
            we cannot know whether it meant Colombo local or UTC, and guessing wrong
            shifts a disaster timeline by five and a half hours.
    """
    if value.tzinfo is None:
        raise ValueError("naive datetime rejected: attach a timezone before storing")
    return value.astimezone(UTC)


def to_colombo(value: datetime) -> datetime:
    """Convert an instant to Sri Lanka local time for rendering."""
    return ensure_utc(value).astimezone(COLOMBO)


def format_colombo(value: datetime, *, with_seconds: bool = False) -> str:
    """Render an instant as Colombo local time, e.g. 2025-11-28 04:30 +0530."""
    pattern = "%Y-%m-%d %H:%M:%S %z" if with_seconds else "%Y-%m-%d %H:%M %z"
    return to_colombo(value).strftime(pattern)


def parse_relative(offset: str) -> timedelta:
    """Parse T-72h, T+14d, T+30m or T+0 into a signed timedelta.

    A bare T+0 / T-0 means landfall itself. An offset with a non-zero value and no unit
    is rejected rather than assumed - T+14 is ambiguous between minutes and days.
    """
    match = _RELATIVE_PATTERN.match(offset.strip())
    if match is None:
        raise ValueError(f"unparseable disaster-relative offset: {offset!r}")

    value = int(match.group("value"))
    unit = match.group("unit")

    if unit is None:
        if value != 0:
            raise ValueError(f"offset {offset!r} needs a unit: m, h or d")
        return timedelta(0)

    magnitude = _UNIT_TO_TIMEDELTA[unit.lower()] * value
    return -magnitude if match.group("sign") == "-" else magnitude


def format_relative(delta: timedelta, *, unit: RelativeUnit | None = None) -> str:
    """Render a timedelta as a landfall-relative offset.

    With no unit, picks the coarsest one that stays exact: 72 hours renders as T-3d,
    25 hours as T+25h, 90 seconds as T+1m (truncated).

    Pass a unit to force it. The Warn loop is defined in hours - operators, runbooks and
    the DMC all say "T-72h", never "T-3d" - so warning surfaces render with unit="h"
    even though both strings denote the same instant.
    """
    total_seconds = int(delta.total_seconds())
    if total_seconds == 0:
        return "T+0"

    sign = "-" if total_seconds < 0 else "+"
    magnitude = abs(total_seconds)

    if unit is not None:
        divisor = int(_UNIT_TO_TIMEDELTA[unit].total_seconds())
        return f"T{sign}{magnitude // divisor}{unit}"

    if magnitude % _SECONDS_PER_DAY == 0:
        return f"T{sign}{magnitude // _SECONDS_PER_DAY}d"
    if magnitude % _SECONDS_PER_HOUR == 0:
        return f"T{sign}{magnitude // _SECONDS_PER_HOUR}h"
    return f"T{sign}{magnitude // 60}m"


@dataclass(frozen=True, slots=True)
class DisasterClock:
    """Converts between absolute instants and landfall-relative offsets.

    A hazard event landfall_at anchors the whole timeline. Operators, runbooks and the
    demo script all speak in T-72h / T+14d; storage is always absolute UTC.
    """

    landfall_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "landfall_at", ensure_utc(self.landfall_at))

    def absolute(self, offset: str) -> datetime:
        """Resolve a relative offset such as T-72h to an absolute UTC instant."""
        return self.landfall_at + parse_relative(offset)

    def relative(self, moment: datetime, *, unit: RelativeUnit | None = None) -> str:
        """Render an absolute instant as an offset from landfall.

        Defaults to the coarsest exact unit; pass `unit` to force one.
        """
        return format_relative(ensure_utc(moment) - self.landfall_at, unit=unit)
