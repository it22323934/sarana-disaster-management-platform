"""Colombo timezone helpers and disaster-relative time (T-72h / T+0 / T+14d).

Per docs/build-prompts/02-conventions.md: store UTC always, render in Asia/Colombo,
never a naive datetime, never timezone maths in the frontend. Disaster timelines are
expressed relative to landfall (T-72h, T+0, T+14d) throughout the product — the design
system's "time spine" (docs/build-prompts/19-design-system.md) is built on this.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

COLOMBO_TZ = ZoneInfo("Asia/Colombo")  # UTC+5:30, no DST

_RELATIVE_PATTERN = re.compile(r"^T([+-])(\d+(?:\.\d+)?)(h|d)$", re.IGNORECASE)


def now_utc() -> datetime:
    return datetime.now(UTC)


def ensure_utc(moment: datetime) -> datetime:
    """Reject naive datetimes rather than silently guessing their timezone."""
    if moment.tzinfo is None:
        raise ValueError(
            f"Naive datetime {moment!r} is not allowed — attach a timezone explicitly."
        )
    return moment.astimezone(UTC)


def to_colombo(moment: datetime) -> datetime:
    return ensure_utc(moment).astimezone(COLOMBO_TZ)


def format_colombo(moment: datetime, *, fmt: str = "%Y-%m-%d %H:%M") -> str:
    return to_colombo(moment).strftime(fmt)


def relative_to_landfall(moment: datetime, landfall_at: datetime) -> str:
    """UTC datetime -> "T-72h" / "T+0" / "T+14d" style label, relative to landfall.

    Uses whole hours up to 72h out from landfall in either direction, and whole days
    beyond that — matching how the proposal and the design system's time spine both
    express the six loops (Anticipate/Warn at hour granularity, Sustain/Learn at day
    granularity).
    """
    delta = ensure_utc(moment) - ensure_utc(landfall_at)
    total_hours = delta.total_seconds() / 3600
    sign = "+" if total_hours >= 0 else "-"
    magnitude = abs(total_hours)

    if magnitude == 0:
        return "T+0"
    if magnitude <= 72:
        hours = round(magnitude)
        return f"T{sign}{hours}h"
    days = round(magnitude / 24)
    return f"T{sign}{days}d"


def landfall_relative_to_absolute(label: str, landfall_at: datetime) -> datetime:
    """Inverse of relative_to_landfall: "T-72h" + landfall -> an absolute UTC datetime."""
    match = _RELATIVE_PATTERN.match(label.strip())
    if not match:
        raise ValueError(f"Not a valid disaster-relative time label: {label!r}")
    sign, magnitude, unit = match.groups()
    amount = float(magnitude)
    delta = timedelta(hours=amount) if unit.lower() == "h" else timedelta(days=amount)
    if sign == "-":
        delta = -delta
    return ensure_utc(landfall_at) + delta
