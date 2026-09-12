"""The useful, non-scary half: the numbers that make a recovery legible.

Build file 17 lists these alongside the detectors and they matter more day to day. A
district secretary asking "how much has actually reached households in my district, and how
long is it taking?" is asking a question no spreadsheet in the 2025 response could answer,
and it is the question the public dashboard exists to answer.

None of this is about suspicion. It runs whether or not a single flag is raised, and it
produces the same figures either way.

## Minimum cell size, applied here rather than at the edge

A count of one household in one GN division for one damage category is a person, however
anonymous the column headers are. Small cells are suppressed at the point the aggregate is
built, so nothing downstream has to remember to do it and no intermediate artefact carries
the row that would identify somebody.

Suppression is visible rather than silent: a suppressed cell reports `suppressed: true` and
its count is withheld, so a reader can see that a number exists and is not being shown -
which is different from a zero, and far different from an absence.

## Confirmation rate always carries its denominator

"62% confirmed" is unactionable and slightly dishonest, because the households that could
not be reached to confirm are not in the numerator or the denominator in the same way. The
rate here is reported with the count it was computed over and with the division's coverage
alongside, so a reader can see whether a low rate is a delivery problem or a coverage one.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Final

from agent_svc.agents.ledger_anomaly.ports import Assessment

# Below this, a cell is suppressed. Five is the usual disclosure-control floor and it is
# what file 27 applies to the public surfaces; applying it here as well means an
# intermediate artefact never holds the row either.
MIN_CELL_SIZE: Final = 5


@dataclass(frozen=True, slots=True)
class Cell:
    """One aggregate figure, and whether it may be shown."""

    key: str
    count: int
    total_lkr: int
    suppressed: bool = False

    def as_dict(self) -> dict[str, Any]:
        if self.suppressed:
            # The key is shown and the numbers are not. A reader can see a figure exists,
            # which is different from a zero and very different from an absence.
            return {
                "key": self.key,
                "suppressed": True,
                "reason": f"fewer than {MIN_CELL_SIZE} records; withheld to protect households",
            }
        return {
            "key": self.key,
            "count": self.count,
            "total_lkr": self.total_lkr,
            "suppressed": False,
        }


@dataclass(frozen=True, slots=True)
class Rollup:
    """The sector figures for one batch."""

    assessments: int
    divisions: int
    total_assessed_lkr: int
    by_district: list[Cell] = field(default_factory=list)
    by_category: list[Cell] = field(default_factory=list)
    confirmation: dict[str, Any] = field(default_factory=dict)
    median_approval_minutes: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "assessments": self.assessments,
            "divisions": self.divisions,
            "total_assessed_lkr": self.total_assessed_lkr,
            "by_district": [cell.as_dict() for cell in self.by_district],
            "by_category": [cell.as_dict() for cell in self.by_category],
            "confirmation": self.confirmation,
            "median_approval_minutes": self.median_approval_minutes,
        }


def _cells(grouped: dict[str, list[Assessment]]) -> list[Cell]:
    """One cell per group, suppressed where the group is too small to show."""
    cells = []
    for key, rows in sorted(grouped.items()):
        count = len(rows)
        cells.append(
            Cell(
                key=key,
                count=count,
                total_lkr=sum(row.assessed_value_lkr for row in rows),
                suppressed=count < MIN_CELL_SIZE,
            )
        )
    return cells


def _confirmation(batch: list[Assessment]) -> dict[str, Any]:
    """The confirmation rate, always with the denominator it was computed over.

    Three numbers rather than one. `asked` is how many households the question has reached
    at all, and a rate over a small `asked` says almost nothing however good it looks.
    """
    known = [item for item in batch if item.citizen_confirmed is not None]
    confirmed = sum(1 for item in known if item.citizen_confirmed)
    return {
        "confirmed": confirmed,
        "asked": len(known),
        "assessments": len(batch),
        "rate": round(confirmed / len(known), 4) if known else None,
        "note": (
            "the rate is over the households that have been asked, not over all "
            "assessments. A low rate in a low-coverage division is a coverage problem "
            "rather than a delivery one; join against cell coverage before reading it."
        ),
    }


def _median_approval(batch: list[Assessment]) -> float | None:
    times = sorted(item.approval_minutes for item in batch if item.approval_minutes is not None)
    if not times:
        return None
    middle = len(times) // 2
    if len(times) % 2:
        return round(times[middle], 1)
    return round((times[middle - 1] + times[middle]) / 2, 1)


def summarise(batch: list[Assessment]) -> Rollup:
    """The whole rollup for one batch of assessments.

    Deterministic, no model, and it runs before any detector - these figures are produced
    whether or not a single flag is raised, because they are what the response actually
    needs day to day.
    """
    by_district: dict[str, list[Assessment]] = defaultdict(list)
    by_category: dict[str, list[Assessment]] = defaultdict(list)
    for item in batch:
        by_district[item.district_code or "unknown"].append(item)
        by_category[item.category].append(item)

    return Rollup(
        assessments=len(batch),
        divisions=len({item.gn_division_code for item in batch}),
        total_assessed_lkr=sum(item.assessed_value_lkr for item in batch),
        by_district=_cells(by_district),
        by_category=_cells(by_category),
        confirmation=_confirmation(batch),
        median_approval_minutes=_median_approval(batch),
    )


def detector_counts(signals: list[Any]) -> dict[str, int]:
    """How many signals each detector produced, for the run's own record."""
    return dict(Counter(getattr(signal, "detector", signal.get("detector")) for signal in signals))
