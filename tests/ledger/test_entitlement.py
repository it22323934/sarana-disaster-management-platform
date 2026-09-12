"""Entitlement calculation and its trace.

The brief calls for a property test over 10,000 random assessments proving recalculation
is identical. That is here, along with the reason it matters: an entitlement that changes
when recomputed is one nobody can audit, and the audit is the product.
"""

from __future__ import annotations

import random

import pytest

from ledger_svc.domain.entitlement import (
    AssessedItem,
    CalculationRefused,
    CostSchedule,
    ScheduleLine,
    calculate,
)
from sarana_shared.crypto.canonical import canonical_bytes
from sarana_shared.domain.ids import uuid7

# A small schedule with the shape of a real one: per-unit amounts and a unit ceiling.
SCHEDULE = CostSchedule(
    version="2026-03",
    lines={
        "HOUSE_FULL": ScheduleLine(uuid7(), "HOUSE_FULL", 250_000_00, 1, "house_full * 250000"),
        "HOUSE_PARTIAL": ScheduleLine(
            uuid7(), "HOUSE_PARTIAL", 75_000_00, 1, "house_partial * 75000"
        ),
        "HOUSEHOLD_GOODS": ScheduleLine(
            uuid7(), "HOUSEHOLD_GOODS", 25_000_00, 1, "household_goods * 25000"
        ),
        "LIVELIHOOD_TOOLS": ScheduleLine(
            uuid7(), "LIVELIHOOD_TOOLS", 40_000_00, 2, "tools * 40000"
        ),
        "CROP": ScheduleLine(uuid7(), "CROP", 15_000_00, 5, "crop_acres * 15000"),
    },
    # Above the default, so a single fully-damaged house does not immediately hit the
    # ceiling. The ceiling is exercised separately by combining categories.
    household_cap_cents=400_000_00,
)

CATEGORIES = list(SCHEDULE.lines)


# --------------------------------------------------------------------------------------
# Determinism — the property the brief names
# --------------------------------------------------------------------------------------


def test_ten_thousand_random_assessments_recalculate_identically() -> None:
    """The case the brief names.

    An entitlement that changes on recalculation cannot be audited, and cannot be
    defended to the household it belongs to.
    """
    # Seeded so a failure is reproducible: a property test that cannot be replayed
    # tells you something is wrong and not what.
    generator = random.Random(20260828)  # noqa: S311 - generating test inputs, not secrets

    for _ in range(10_000):
        items = [
            AssessedItem(category=category, units=generator.randint(0, 6))
            for category in generator.sample(CATEGORIES, generator.randint(1, len(CATEGORIES)))
        ]
        already = generator.choice([0, 0, 0, 10_000_00, 150_000_00])

        first = calculate(items, SCHEDULE, already_disbursed_cents=already)
        second = calculate(items, SCHEDULE, already_disbursed_cents=already)

        assert first.result_lkr_cents == second.result_lkr_cents
        assert canonical_bytes(first.as_dict()) == canonical_bytes(second.as_dict())


def test_the_order_items_were_entered_does_not_change_the_result() -> None:
    """Two officers entering the same damage in a different order must agree.

    Not merely on the total - on the trace, byte for byte, because the trace is hashed
    into the ledger.
    """
    items = [
        AssessedItem("CROP", 3),
        AssessedItem("HOUSE_PARTIAL", 1),
        AssessedItem("HOUSEHOLD_GOODS", 1),
    ]

    forward = calculate(items, SCHEDULE)
    backward = calculate(list(reversed(items)), SCHEDULE)

    assert canonical_bytes(forward.as_dict()) == canonical_bytes(backward.as_dict())


def test_the_trace_carries_no_timestamp() -> None:
    """A timestamp would make two identical calculations hash differently.

    When the calculation happened belongs to the entitlement row; the working itself is
    timeless, and that is what makes it verifiable.
    """
    trace = calculate([AssessedItem("HOUSE_FULL", 1)], SCHEDULE)

    assert "computed_at" not in trace.as_dict()


# --------------------------------------------------------------------------------------
# The arithmetic
# --------------------------------------------------------------------------------------


def test_a_single_category_is_units_times_the_schedule_amount() -> None:
    trace = calculate([AssessedItem("HOUSE_FULL", 1)], SCHEDULE)

    assert trace.result_lkr_cents == 250_000_00


def test_categories_sum() -> None:
    trace = calculate(
        [AssessedItem("HOUSE_PARTIAL", 1), AssessedItem("HOUSEHOLD_GOODS", 1)], SCHEDULE
    )

    assert trace.result_lkr_cents == 100_000_00


def test_units_above_a_line_maximum_are_capped_and_the_cap_is_recorded() -> None:
    """Capped silently would be a household told a number with no explanation."""
    trace = calculate([AssessedItem("CROP", 99)], SCHEDULE)

    assert trace.result_lkr_cents == 5 * 15_000_00
    assert any("CROP" in cap for cap in trace.caps_applied)


def test_the_household_ceiling_applies_across_categories() -> None:
    """Without it, an assessment listing everything produces a number nobody approves."""
    trace = calculate(
        [
            AssessedItem("HOUSE_FULL", 1),
            AssessedItem("HOUSE_PARTIAL", 1),
            AssessedItem("LIVELIHOOD_TOOLS", 2),
            AssessedItem("CROP", 5),
        ],
        SCHEDULE,
    )

    assert trace.result_lkr_cents == SCHEDULE.household_cap_cents
    assert any("ceiling" in cap for cap in trace.caps_applied)


def test_already_disbursed_is_deducted() -> None:
    trace = calculate(
        [AssessedItem("HOUSE_PARTIAL", 1)], SCHEDULE, already_disbursed_cents=25_000_00
    )

    assert trace.result_lkr_cents == 50_000_00


def test_a_household_already_overpaid_is_owed_nothing_not_a_negative() -> None:
    """A negative entitlement would become a demand for money back by accident."""
    trace = calculate(
        [AssessedItem("HOUSEHOLD_GOODS", 1)], SCHEDULE, already_disbursed_cents=999_000_00
    )

    assert trace.result_lkr_cents == 0


def test_zero_units_is_zero_but_still_produces_a_trace() -> None:
    """A zero entitlement with no working is a household told nothing, for no stated reason."""
    trace = calculate([AssessedItem("CROP", 0)], SCHEDULE)

    assert trace.result_lkr_cents == 0
    assert trace.steps


# --------------------------------------------------------------------------------------
# The trace itself
# --------------------------------------------------------------------------------------


def test_the_trace_records_the_schedule_version_it_used() -> None:
    """An entitlement pins its schedule. A later schedule must not move it."""
    trace = calculate([AssessedItem("HOUSE_FULL", 1)], SCHEDULE)

    assert trace.cost_schedule_version == "2026-03"


def test_the_trace_shows_every_step_in_order() -> None:
    trace = calculate([AssessedItem("HOUSE_FULL", 1), AssessedItem("CROP", 2)], SCHEDULE)

    descriptions = [step.description for step in trace.steps]
    assert "subtotal" in descriptions
    assert descriptions.index("subtotal") == len(descriptions) - 1 or "ceiling" in " ".join(
        descriptions
    )


def test_the_trace_records_every_input_that_went_in() -> None:
    """A household arguing with a number needs to see what was counted."""
    trace = calculate([AssessedItem("CROP", 3)], SCHEDULE)

    assert trace.inputs["units:CROP"] == 3
    assert trace.inputs["cost_schedule_version"] == "2026-03"


def test_the_trace_names_the_schedule_lines_it_priced_against() -> None:
    trace = calculate([AssessedItem("HOUSE_FULL", 1)], SCHEDULE)

    assert trace.schedule_line_ids == [str(SCHEDULE.lines["HOUSE_FULL"].line_id)]


def test_the_trace_reads_as_a_sentence() -> None:
    """It goes on an SMS and a printed slip, so it has to be legible."""
    trace = calculate([AssessedItem("CROP", 99)], SCHEDULE)

    sentence = trace.as_sentence()
    assert "CROP" in sentence
    assert "capped" in sentence


# --------------------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------------------


def test_a_category_the_schedule_does_not_price_is_refused() -> None:
    """Never valued at zero: that would silently pay nothing for real damage."""
    with pytest.raises(CalculationRefused, match="no line for"):
        calculate([AssessedItem("DEATH", 1)], SCHEDULE)


def test_a_category_the_schema_does_not_allow_is_refused() -> None:
    with pytest.raises(CalculationRefused, match="not a damage category"):
        ScheduleLine(uuid7(), "SPACESHIP", 1, 1, "x")


def test_negative_units_are_refused() -> None:
    with pytest.raises(CalculationRefused, match="cannot be negative"):
        AssessedItem("CROP", -1)


def test_a_schedule_line_above_the_household_ceiling_is_refused() -> None:
    """A category that can never be paid in full is a misconfigured schedule.

    Caught when the schedule is built, not one capped household at a time.
    """
    with pytest.raises(CalculationRefused, match="never be paid in full"):
        CostSchedule(
            version="broken",
            lines={
                "HOUSE_FULL": ScheduleLine(
                    uuid7(), "HOUSE_FULL", 900_000_00, 1, "house_full * 900000"
                )
            },
            household_cap_cents=200_000_00,
        )


def test_a_negative_already_disbursed_is_refused() -> None:
    with pytest.raises(CalculationRefused, match="cannot be negative"):
        calculate([AssessedItem("CROP", 1)], SCHEDULE, already_disbursed_cents=-1)
