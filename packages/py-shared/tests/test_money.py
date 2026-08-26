"""LKR arithmetic. Integer minor units, schedule-versioned, never a float."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from sarana_shared.domain.money import Money, cents_to_rupees, format_lkr, rupees_to_cents

SCHEDULE = "2025.11"


def test_rupees_convert_exactly() -> None:
    assert rupees_to_cents(Decimal("1250000.00")) == 125_000_000
    assert rupees_to_cents("0.01") == 1
    assert cents_to_rupees(125_000_075) == Decimal("1250000.75")


def test_float_is_refused_at_the_boundary() -> None:
    """0.1 has no exact binary representation, and this value ends up in a payment."""
    with pytest.raises(TypeError, match="float is not accepted"):
        rupees_to_cents(1250.10)  # type: ignore[arg-type]  # the point of the test


def test_format_matches_the_convention_example() -> None:
    assert format_lkr(125_000_000) == "LKR 1,250,000.00"


def test_amounts_from_different_schedules_do_not_combine() -> None:
    """A schedule revision must never silently rewrite an existing entitlement basis."""
    november = Money(cents=100_000, cost_schedule_version="2025.11")
    december = Money(cents=100_000, cost_schedule_version="2025.12")

    with pytest.raises(ValueError, match="different cost schedules"):
        _ = november + december


def test_amounts_from_one_schedule_do_combine() -> None:
    total = Money(cents=100_000, cost_schedule_version=SCHEDULE) + Money(
        cents=50_000, cost_schedule_version=SCHEDULE
    )

    assert total.cents == 150_000
    assert total.cost_schedule_version == SCHEDULE


def test_proportional_entitlement_stays_in_integer_arithmetic() -> None:
    full = Money(cents=1_000_000, cost_schedule_version=SCHEDULE)

    assert full.scaled(1, 3).cents == 333_333


def test_cap_is_applied_without_reformatting() -> None:
    calculated = Money(cents=125_000_000, cost_schedule_version=SCHEDULE)
    cap = Money(cents=100_000_000, cost_schedule_version=SCHEDULE)

    assert calculated.capped_at(cap).cents == cap.cents


def test_an_implausible_amount_is_rejected_as_a_units_mistake() -> None:
    """Guards the classic bug: rupees passed where minor units were expected."""
    with pytest.raises(ValidationError):
        Money(cents=99_999_999_999_999_999, cost_schedule_version=SCHEDULE)


def test_schedule_version_shape_is_enforced() -> None:
    with pytest.raises(ValidationError):
        Money(cents=1, cost_schedule_version="November 2025")
