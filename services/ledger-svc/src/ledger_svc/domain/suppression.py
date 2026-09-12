"""The privacy floor: which cells are published, which are withheld, and what is disclosed.

Small-cell suppression is the one rule on the public surface that is a *policy* decision
rather than a technical one, so it lives in the domain with a name and a test rather than
as a loop inside a request handler. Three properties it has to hold, and each is a way the
obvious implementation gets it wrong:

**A zero is published; a small non-zero cell is withheld.** Only a small non-zero cell
identifies anybody. "Nothing was paid in this division" is the single most useful row on a
transparency page and withholding it would hide exactly the finding a reader came for. An
implementation that filtered on `count < min_cell` would drop both.

**The withheld rows are still counted, and their money is still in the total.** A page whose
DS subtotals do not add up to the district figure on the previous screen costs more
credibility than the suppression saves - a reader who noticed would be right to distrust
both numbers. So the totals are computed over every row and the published list is a subset.

**Suppression is disclosed, never silent.** The result carries how many divisions were
withheld and how much money they held. A gap in a table reads as missing data and invites
the reader to conclude nothing happened there, which is the opposite of what the floor is
protecting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

# The minimum number of disbursements in a cell before it is published.
#
# Five, from build file 21, and it is a re-identification-risk decision rather than a tuning
# parameter. The API accepts a *higher* floor and refuses a lower one: a caller who could
# pass `min_cell=1` would make the rule decorative.
MIN_CELL_SIZE: Final = 5

# The columns totalled across every row, published or not. Listed rather than derived from
# the row's keys so that a new column added to the query is a deliberate decision here -
# a median, for instance, must not be summed.
_SUMMED: Final = (
    "assessed_count",
    "assessed_households",
    "assessed_divisions",
    "assessed_lkr_cents",
    "approved_count",
    "approved_lkr_cents",
    "disbursed_count",
    "disbursed_lkr_cents",
    "confirmed_count",
)


@dataclass(frozen=True)
class Suppressed:
    """The published rows, the district total, and what was withheld."""

    rows: list[dict[str, Any]]
    totals: dict[str, int]
    divisions: int
    disbursements: int
    lkr_cents: int


def apply_minimum_cell_size(
    rows: list[dict[str, Any]], *, min_cell: int = MIN_CELL_SIZE
) -> Suppressed:
    """Split rows into what may be published and what may only be counted.

    `min_cell` may be raised but never lowered below `MIN_CELL_SIZE`; the caller is
    responsible for rejecting a smaller value, and the API does so at the query parameter.
    """
    published: list[dict[str, Any]] = []
    totals = dict.fromkeys(_SUMMED, 0)

    divisions = 0
    disbursements = 0
    lkr_cents = 0

    for row in rows:
        for column in _SUMMED:
            totals[column] += int(row.get(column) or 0)

        count = int(row.get("disbursed_count") or 0)
        amount = int(row.get("disbursed_lkr_cents") or 0)

        if 0 < count < min_cell:
            divisions += 1
            disbursements += count
            lkr_cents += amount
            continue

        published.append(row)

    return Suppressed(
        rows=published,
        totals=totals,
        divisions=divisions,
        disbursements=disbursements,
        lkr_cents=lkr_cents,
    )
