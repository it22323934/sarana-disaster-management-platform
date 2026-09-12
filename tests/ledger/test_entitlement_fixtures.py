"""The entitlement fixture still describes what the server computes.

`data/fixtures/entitlement/cases.json` is the contract between two implementations of one
calculation: `ledger_svc.domain.entitlement.calculate` here, and
`apps/mobile/src/field/entitlement.ts` on a GN officer's handset. The Field Companion shows
a provisional figure while the officer is standing in front of the house; this service
recomputes it on submission and its answer becomes the money.

**This file is a regression guard, not an independent derivation, and the difference
matters.** The expected values were produced by `calculate` itself (see
`tools/fixtures/entitlement_cases.py`), so this cannot catch a bug that was already in
`calculate` when the fixture was written. What it catches is a change that silently moves
every household's number — and, paired with the TypeScript test over the same file, a
device that has drifted from the server.

If a case here fails, do not regenerate the fixture to make it pass. Every line that moves
is a figure some household would have been told.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from ledger_svc.domain.entitlement import (
    AssessedItem,
    CostSchedule,
    ScheduleLine,
    calculate,
)
from ledger_svc.repo.base import DAMAGE_CATEGORIES

FIXTURE = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "entitlement" / "cases.json"

_DATA: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))

SCHEDULE = CostSchedule(
    version=_DATA["schedule"]["version"],
    lines={
        line["category"]: ScheduleLine(
            UUID(line["line_id"]),
            line["category"],
            line["unit_amount_cents"],
            line["max_units"],
            line["formula"],
        )
        for line in _DATA["schedule"]["lines"]
    },
    household_cap_cents=_DATA["schedule"]["household_cap_cents"],
)

CASES: list[dict[str, Any]] = _DATA["cases"]


def _ids(cases: list[dict[str, Any]]) -> list[str]:
    return [case["name"] for case in cases]


def test_the_fixture_prices_every_category_the_schema_allows() -> None:
    """Guards the guard.

    A fixture that lost a category would pass every case below while covering eight ninths
    of the calculation. The device parity test asserts the same count from the other side.
    """
    assert set(SCHEDULE.lines) == set(DAMAGE_CATEGORIES)
    singles = [case for case in CASES if case["name"].startswith("single-")]
    assert len(singles) == len(DAMAGE_CATEGORIES)


def test_the_fixture_exercises_both_caps_and_the_deduction() -> None:
    """The three branches that change a number after the line items are summed."""
    names = {case["name"] for case in CASES}
    assert {
        "units-capped",
        "household-ceiling",
        "already-disbursed",
        "already-disbursed-exceeds",
        "ceiling-then-disbursed",
    } <= names


@pytest.mark.parametrize("case", CASES, ids=_ids(CASES))
def test_the_server_still_produces_the_recorded_trace(case: dict[str, Any]) -> None:
    """Every field, not just the total.

    A total that matched while the working differed would still be a failure: the trace is
    hashed into the ledger entry and read out to the household, so a step description that
    drifted is two different explanations of one payment.
    """
    trace = calculate(
        [AssessedItem(item["category"], item["units"]) for item in case["items"]],
        SCHEDULE,
        already_disbursed_cents=case["already_disbursed_cents"],
    )

    assert trace.as_dict() == case["expected"], (
        f"{case['name']} moved. {case['why']}\n"
        "If this change is intended, regenerate with "
        "`uv run python -m tools.fixtures.entitlement_cases` and read the whole diff: "
        "every line that moved is a figure some household would have been told."
    )


def test_the_fixture_on_disk_is_what_the_generator_writes() -> None:
    """The committed file has not been hand-edited away from the generator.

    A fixture edited by hand to make a test pass is a fixture that no longer describes the
    server, and the device would then be held to a number this service does not compute.
    """
    from tools.fixtures.entitlement_cases import build

    assert build() == _DATA, (
        "data/fixtures/entitlement/cases.json differs from what "
        "tools/fixtures/entitlement_cases.py produces. Regenerate it rather than editing it."
    )
