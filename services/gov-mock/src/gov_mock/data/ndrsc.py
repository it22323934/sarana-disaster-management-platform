"""Synthetic NDRSC data: two published cost schedules, and the claims register.

**Two versions, on purpose.** `2024.03` and `2025.11`. Version pinning is the property that
makes an entitlement defensible years later — `ledger_svc.domain.entitlement` records which
schedule it calculated against, and a new schedule never moves an existing entitlement. A
mock serving one version lets that property go untested until the first time the real
government publishes a revision, which is the worst moment to discover it.

**The version string shape is not free.** `aid.cost_schedule` constrains it to
`^\\d{4}\\.\\d{2}(\\.\\d+)?$`. A schedule this mock served in any other shape could be read
by the platform and then never stored, so the shape is asserted here at import.

**The rates are illustrative.** They are the right order of magnitude for Sri Lankan
disaster relief and they are internally consistent — every line sits under the household
ceiling, so `CostSchedule` in the ledger will accept them — but they are not the gazetted
figures. `formula` on each line is the string a household is shown, so it has to describe
what was actually computed, not a summary of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from gov_mock.data.derive import choose, falls_within

# Mirrors the CHECK constraint on `aid.cost_schedule.version`.
VERSION_PATTERN: Final = re.compile(r"^\d{4}\.\d{2}(\.\d+)?$")

# Mirrors `aid.cost_schedule_line.category`. A line in any other category would be
# rejected by the database the moment the platform tried to store the schedule.
DAMAGE_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "HOUSE_FULL",
        "HOUSE_PARTIAL",
        "HOUSEHOLD_GOODS",
        "LIVELIHOOD_TOOLS",
        "CROP",
        "LIVESTOCK",
        "FISHING_GEAR",
        "DEATH",
        "INJURY",
    }
)


@dataclass(frozen=True, slots=True)
class Line:
    """One priced line."""

    line_id: str
    category: str
    unit_amount_cents: int
    max_units: int
    formula: str


@dataclass(frozen=True, slots=True)
class Schedule:
    """One published version of the compensation schedule."""

    version: str
    published_at: datetime
    effective_from: datetime
    household_cap_cents: int
    lines: tuple[Line, ...]

    def __post_init__(self) -> None:
        if not VERSION_PATTERN.match(self.version):
            raise ValueError(
                f"schedule version {self.version!r} does not match the shape "
                "aid.cost_schedule enforces; the platform could read it and never store it"
            )
        for line in self.lines:
            if line.category not in DAMAGE_CATEGORIES:
                raise ValueError(f"{line.category!r} is not a damage category the schema allows")
            if line.unit_amount_cents > self.household_cap_cents:
                # The same refusal `ledger_svc.domain.entitlement.CostSchedule` makes. A
                # line that can never be paid in full is a misconfigured schedule, and
                # finding out one household at a time is the expensive way to learn it.
                raise ValueError(
                    f"schedule {self.version}: {line.category} is priced above the "
                    f"household ceiling of {self.household_cap_cents}"
                )


def _lines(version: str, rates: dict[str, tuple[int, int, str]]) -> tuple[Line, ...]:
    """Build the lines for one version.

    `line_id` is derived from the version and category rather than random, so the same
    schedule served twice carries the same line ids — which matters because an entitlement
    trace records them and an auditor will compare.
    """
    return tuple(
        Line(
            line_id=f"NDRSC-{version}-{category}",
            category=category,
            unit_amount_cents=amount,
            max_units=units,
            formula=formula,
        )
        for category, (amount, units, formula) in sorted(rates.items())
    )


# LKR, in cents. The ceiling is per household across all categories for one event.
_CAP_2024: Final = 400_000_00
_CAP_2025: Final = 500_000_00

_RATES_2024: Final[dict[str, tuple[int, int, str]]] = {
    "HOUSE_FULL": (250_000_00, 1, "250,000 per fully destroyed house"),
    "HOUSE_PARTIAL": (75_000_00, 1, "75,000 per partially damaged house"),
    "HOUSEHOLD_GOODS": (25_000_00, 1, "25,000 per household for furniture and goods"),
    "LIVELIHOOD_TOOLS": (50_000_00, 1, "50,000 per household for livelihood assets"),
    "CROP": (15_000_00, 5, "15,000 per acre, to a maximum of 5 acres"),
    "LIVESTOCK": (20_000_00, 10, "20,000 per animal lost, to a maximum of 10"),
    "FISHING_GEAR": (60_000_00, 1, "60,000 per household for boats and gear"),
    "DEATH": (100_000_00, 8, "100,000 per death"),
    "INJURY": (25_000_00, 8, "25,000 per person injured"),
}

# The 2025 revision. Housing and household goods rose; the rest held. A revision that
# moved every line by the same percentage would let a rounding bug hide.
_RATES_2025: Final[dict[str, tuple[int, int, str]]] = {
    **_RATES_2024,
    "HOUSE_FULL": (300_000_00, 1, "300,000 per fully destroyed house"),
    "HOUSE_PARTIAL": (100_000_00, 1, "100,000 per partially damaged house"),
    "HOUSEHOLD_GOODS": (40_000_00, 1, "40,000 per household for furniture and goods"),
}

SCHEDULES: Final[tuple[Schedule, ...]] = (
    Schedule(
        version="2025.11",
        published_at=datetime(2025, 11, 1, 4, 0, tzinfo=UTC),
        effective_from=datetime(2025, 11, 15, 18, 30, tzinfo=UTC),
        household_cap_cents=_CAP_2025,
        lines=_lines("2025.11", _RATES_2025),
    ),
    Schedule(
        version="2024.03",
        published_at=datetime(2024, 3, 12, 4, 0, tzinfo=UTC),
        effective_from=datetime(2024, 4, 1, 18, 30, tzinfo=UTC),
        household_cap_cents=_CAP_2024,
        lines=_lines("2024.03", _RATES_2024),
    ),
)

BY_VERSION: Final[dict[str, Schedule]] = {schedule.version: schedule for schedule in SCHEDULES}

CURRENT_VERSION: Final = SCHEDULES[0].version


# How the CMS moves a claim along, in hours after it was received. A claim is not
# instantly approved: the review window is what makes the ledger's "submitted, awaiting
# the CMS" state a real state that the ops console has to render.
REVIEW_AFTER_HOURS: Final = 6.0
DECISION_AFTER_HOURS: Final = 30.0
PAID_AFTER_HOURS: Final = 72.0

# Share of claims the CMS returns rather than approves. Returned is not rejected: it is
# "we need something else from you", and it is the common case in a real claims system.
RETURN_SHARE: Final = 0.08

_RETURN_REASONS: Final[tuple[str, ...]] = (
    "Assessment photograph not legible; resubmit with a clear image of the damage.",
    "Household reference does not match the divisional register for this GN division.",
    "A claim already exists for this household under a different event reference.",
)


def return_reason(client_reference: str) -> str:
    """Which return reason this claim gets. Stable for a given reference."""
    return choose(client_reference, _RETURN_REASONS, salt="ndrsc-reason")


def is_returned(client_reference: str) -> bool:
    """Whether the CMS returns this claim rather than approving it.

    Derived from the reference rather than drawn at random, so a claim's fate does not
    change between the submit call and the status poll — which would be indistinguishable
    from the CMS changing its mind, and much harder to debug.
    """
    # A digest, not a checksum over the characters: see `gov_mock.data.derive`. A batch
    # of sequential claim references must not come back all returned or all approved.
    return falls_within(client_reference, share=RETURN_SHARE, salt="ndrsc-return")
