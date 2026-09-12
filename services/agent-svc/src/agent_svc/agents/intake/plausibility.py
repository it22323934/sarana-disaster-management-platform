"""Sanity checks over a report, and the rule that a flag is never a rejection.

## Flagging is not rejection, and the asymmetry is the whole point

During a real disaster, the cost of ignoring a real report because it looked implausible is
a death. The cost of a human spending twenty seconds on a false one is twenty seconds.

So nothing in this module can drop a report, refuse one, or mark one as spam. Every check
produces a `Flag`, every flag routes the report to a person, and the report stays in the
queue and stays dispatchable throughout. A checker that could reject would eventually reject
somebody who was telling the truth from a flooded house at 3 a.m., and nobody would ever
know it happened.

## Deterministic first, and mostly deterministic only

Every check here is arithmetic or a set membership test. A model is not consulted, because
none of these questions needs one: whether a timestamp is in a sane window, whether a
coordinate is inside the country, whether a count is within an order of magnitude of a
household. Build file 15 reserves the LLM for "the residue" - the genuinely ambiguous spam
judgement - and that residue is deliberately not implemented here rather than approximated,
because a spam classifier that is wrong in a disaster silences somebody.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

from agent_svc.agents.intake.ports import RawReport
from sarana_shared.domain.geo import in_sri_lanka

# How far ahead of now a report may claim to have happened before it is worth a look. Small
# and non-zero: phone clocks drift by minutes, and a report from a phone five minutes fast
# is not suspicious.
FUTURE_TOLERANCE_MINUTES: Final = 15

# How far back a report may reach before it is flagged as probably a replay or a bad clock.
# Seven days: the Anticipate loop starts at T-7d, so a report older than that is outside the
# event this platform is responding to.
STALE_AFTER_DAYS: Final = 7

# The order-of-magnitude bound on a people count relative to a typical household. A Sri
# Lankan household averages under four people; a report claiming forty at one address is
# plausible for a shelter or a school and worth a person's eye, not a rejection.
TYPICAL_HOUSEHOLD_SIZE: Final = 4
PEOPLE_ORDER_OF_MAGNITUDE: Final = 10


@dataclass(frozen=True, slots=True)
class Flag:
    """One thing about this report that a person should look at.

    `code` is stable and machine-readable so the console can group them; `detail` is the
    sentence a reviewer reads. Both, because a flag with only a code is one nobody can
    triage and a flag with only prose is one nothing can count.
    """

    code: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class Verdict:
    """Everything the checks found. Never a rejection."""

    flags: list[Flag] = field(default_factory=list)

    @property
    def plausible(self) -> bool:
        """Whether anything needs a person. Not whether the report is true."""
        return not self.flags

    def as_dict(self) -> dict[str, Any]:
        return {"flags": [flag.as_dict() for flag in self.flags], "plausible": self.plausible}

    def as_sentence(self) -> str:
        if not self.flags:
            return "plausibility: nothing flagged"
        return f"plausibility: {', '.join(flag.code for flag in self.flags)}"


def check(
    report: RawReport,
    *,
    people_at_risk: int | None = None,
    gn_division_code: str | None = None,
    lon: float | None = None,
    lat: float | None = None,
    now: datetime | None = None,
    household_size: int = TYPICAL_HOUSEHOLD_SIZE,
) -> Verdict:
    """Run every check, and collect what they find.

    Every check runs even after one has flagged. A reviewer wants the whole list rather
    than whichever problem happened to be tested first - two flags on one report is a
    different situation from one, and stopping early would hide that.
    """
    moment = now or report.received_at
    flags: list[Flag] = []

    flags += _timestamp_flags(report, moment)
    flags += _location_flags(lon, lat, gn_division_code)
    flags += _people_flags(people_at_risk, household_size)

    return Verdict(flags=flags)


def _timestamp_flags(report: RawReport, now: datetime) -> list[Flag]:
    """Whether the report claims a sane time."""
    found: list[Flag] = []
    ahead = (report.received_at - now).total_seconds() / 60.0

    if ahead > FUTURE_TOLERANCE_MINUTES:
        found.append(
            Flag(
                code="timestamp_in_future",
                detail=(
                    f"this report is timestamped {ahead:.0f} minutes in the future. Usually "
                    "a phone clock; occasionally a replayed message. The report stands."
                ),
            )
        )

    behind = (now - report.received_at).days
    if behind > STALE_AFTER_DAYS:
        found.append(
            Flag(
                code="timestamp_stale",
                detail=(
                    f"this report is {behind} days old, outside the 7-day window the "
                    "Anticipate loop covers. It may be a replay or a bad clock."
                ),
            )
        )
    return found


def _location_flags(
    lon: float | None, lat: float | None, gn_division_code: str | None
) -> list[Flag]:
    """Whether the resolved location makes sense."""
    found: list[Flag] = []

    if lon is not None and lat is not None and not in_sri_lanka(lon, lat):
        found.append(
            Flag(
                code="location_outside_country",
                detail=(
                    "the resolved coordinate is outside Sri Lanka. The report stands and is "
                    "dispatchable on its division; the point should not be trusted."
                ),
            )
        )

    if gn_division_code is None:
        found.append(
            Flag(
                code="unplaced",
                detail=(
                    "nothing in this report locates it - no usable coordinate and no "
                    "recognised landmark. It is valid and it is not dispatchable until "
                    "somebody places it."
                ),
            )
        )
    return found


def _people_flags(people_at_risk: int | None, household_size: int) -> list[Flag]:
    """Whether the people count is within reach of a household.

    A missing count is not flagged. `None` means the report did not say, which is the
    ordinary case for an SMS and is not a problem with the report.
    """
    if people_at_risk is None:
        return []

    ceiling = household_size * PEOPLE_ORDER_OF_MAGNITUDE
    if people_at_risk > ceiling:
        return [
            Flag(
                code="people_at_risk_above_household_scale",
                detail=(
                    f"{people_at_risk} people at one address is more than {ceiling}, an "
                    "order of magnitude above a household. Plausible for a school or a "
                    "shelter, and worth twenty seconds of a person's time."
                ),
            )
        ]
    return []
