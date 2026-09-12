"""Generate the entitlement parity fixture. `uv run python -m tools.fixtures.entitlement_cases`

The Field Companion computes a provisional entitlement on the device so a GN officer sees
an obvious data-entry error while they are still standing in front of the house, rather
than three weeks later in a rejection. The server recomputes and its answer is the
authoritative one — which means the two implementations have to agree exactly, and
"exactly" includes the working, not just the total.

**This file writes the fixture; it is not the test.** `data/fixtures/entitlement/cases.json`
is a golden file: the *inputs* are hand-chosen to exercise every branch of
`ledger_svc.domain.entitlement.calculate`, and the *expected outputs* are produced by that
function and committed. Two tests then read it:

  `tests/ledger/test_entitlement_fixtures.py` — the Python still produces these results.
  `apps/mobile/test/entitlement-parity.test.ts` — the device produces them too.

The Python test is a regression guard rather than an independent derivation, and saying so
matters: it cannot catch a bug that was in `calculate` when the fixture was generated. What
it does catch is the change that silently moves every household's number, and what the
TypeScript test catches is the device drifting from the server — which is the failure this
fixture exists for, because it shows up as an officer being told one figure and a household
receiving another.

Regenerate only when the calculation is *meant* to change, and read the diff: every line
that moves is a number some household would have been told.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from ledger_svc.domain.entitlement import (
    AssessedItem,
    CostSchedule,
    ScheduleLine,
    calculate,
)
from ledger_svc.repo.base import DAMAGE_CATEGORIES

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "data" / "fixtures" / "entitlement" / "cases.json"

# Fixed UUIDs, not `uuid7()`. The trace carries `schedule_line_ids`, so a generated id
# would make the fixture change on every run and the diff would be noise hiding a real
# movement in the numbers.
_LINE_IDS = {
    category: UUID(f"018f4a2b-0000-7000-8000-0000000{index:05d}")
    for index, category in enumerate(DAMAGE_CATEGORIES, start=1)
}

# One line per category the schema allows, because the brief asks for parity across *all*
# categories. The amounts are plausible rather than official - the fixture is about the
# arithmetic agreeing, and the real rates live in the published schedule.
#
# `max_units` varies on purpose: a category with a unit ceiling of 1 and one with a
# ceiling of 5 exercise different branches, and a fixture where every line behaved the
# same way would prove the cap logic on none of them.
_UNIT_AMOUNTS: dict[str, tuple[int, int]] = {
    # category: (unit_amount_cents, max_units)
    "HOUSE_FULL": (250_000_00, 1),
    "HOUSE_PARTIAL": (75_000_00, 1),
    "HOUSEHOLD_GOODS": (25_000_00, 2),
    "LIVELIHOOD_TOOLS": (40_000_00, 2),
    "CROP": (15_000_00, 5),
    "LIVESTOCK": (30_000_00, 4),
    "FISHING_GEAR": (60_000_00, 2),
    "DEATH": (100_000_00, 3),
    "INJURY": (20_000_00, 6),
}

# Above the default 200,000 so a single fully-damaged house does not immediately hit the
# ceiling; the ceiling gets its own cases below by combining categories.
HOUSEHOLD_CAP_CENTS = 400_000_00
SCHEDULE_VERSION = "2026-03"

SCHEDULE = CostSchedule(
    version=SCHEDULE_VERSION,
    lines={
        category: ScheduleLine(
            _LINE_IDS[category],
            category,
            amount,
            max_units,
            f"{category.lower()} * {amount // 100}",
        )
        for category, (amount, max_units) in _UNIT_AMOUNTS.items()
    },
    household_cap_cents=HOUSEHOLD_CAP_CENTS,
)


def _case(
    name: str, why: str, items: list[tuple[str, int]], already_disbursed_cents: int = 0
) -> dict[str, Any]:
    trace = calculate(
        [AssessedItem(category, units) for category, units in items],
        SCHEDULE,
        already_disbursed_cents=already_disbursed_cents,
    )
    return {
        "name": name,
        "why": why,
        "items": [{"category": category, "units": units} for category, units in items],
        "already_disbursed_cents": already_disbursed_cents,
        "expected": trace.as_dict(),
    }


def build() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []

    # Every category, one unit each. The brief's "all categories" requirement, literally.
    for category in DAMAGE_CATEGORIES:
        cases.append(
            _case(
                f"single-{category.lower()}",
                f"one unit of {category} valued at its schedule rate",
                [(category, 1)],
            )
        )

    cases.extend(
        [
            _case(
                "empty",
                "no items at all. Produces zero with a trace, never a bare zero - an "
                "entitlement of nothing still has to say why.",
                [],
            ),
            _case(
                "zero-units",
                "a category entered with zero units. Zero is a measured answer and it "
                "keeps its step in the working.",
                [("CROP", 0)],
            ),
            _case(
                "units-capped",
                "six acres of crop against a five-acre ceiling. The cap is applied and "
                "named, so the officer can see why the total is not what they expected.",
                [("CROP", 6)],
            ),
            _case(
                "units-capped-multiple-lines",
                "two categories both over their unit ceilings in one assessment.",
                [("CROP", 9), ("INJURY", 8)],
            ),
            _case(
                "household-ceiling",
                "a house destroyed plus livelihood tools plus livestock, which together "
                "exceed the household ceiling. The ceiling wins and says so.",
                [("HOUSE_FULL", 1), ("LIVELIHOOD_TOOLS", 2), ("LIVESTOCK", 4)],
            ),
            _case(
                "already-disbursed",
                "a partially-damaged house where an interim payment has already gone out.",
                [("HOUSE_PARTIAL", 1)],
                already_disbursed_cents=25_000_00,
            ),
            _case(
                "already-disbursed-exceeds",
                "more has been paid than the schedule allows. The result is zero, never "
                "negative - a household is not asked for money back by an arithmetic "
                "accident.",
                [("HOUSEHOLD_GOODS", 1)],
                already_disbursed_cents=90_000_00,
            ),
            _case(
                "ceiling-then-disbursed",
                "both caps in one calculation, in the order the server applies them: the "
                "household ceiling first, then the deduction.",
                [("HOUSE_FULL", 1), ("FISHING_GEAR", 2), ("DEATH", 1)],
                already_disbursed_cents=50_000_00,
            ),
            _case(
                "entry-order-does-not-matter",
                "the same three categories entered in a different order. The trace sorts "
                "by category, so two identical assessments hash alike however the officer "
                "typed them - which is what makes the ledger entry reproducible.",
                [("LIVESTOCK", 1), ("CROP", 2), ("HOUSE_PARTIAL", 1)],
            ),
        ]
    )

    return {
        "note": (
            "Generated by tools/fixtures/entitlement_cases.py from "
            "ledger_svc.domain.entitlement.calculate. Read by the Python regression test "
            "and by the Field Companion's on-device parity test. Regenerate only when the "
            "calculation is meant to change, and read the diff: every line that moves is a "
            "number some household would have been told."
        ),
        "schedule": {
            "version": SCHEDULE_VERSION,
            "household_cap_cents": HOUSEHOLD_CAP_CENTS,
            "lines": [
                {
                    "line_id": str(_LINE_IDS[category]),
                    "category": category,
                    "unit_amount_cents": amount,
                    "max_units": max_units,
                    "formula": f"{category.lower()} * {amount // 100}",
                }
                for category, (amount, max_units) in _UNIT_AMOUNTS.items()
            ],
        },
        "cases": cases,
    }


def main() -> None:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
