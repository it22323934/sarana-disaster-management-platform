"""Money.

Conventions:
  - LKR minor units as integers. Never a float, never a Decimal-in-JSON.
  - Type alias LKRCents = int. Format only at the render boundary.
  - Every monetary field carries the cost_schedule_version that produced it.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# LKR minor units ("cents"). 100 cents = LKR 1.00.
type LKRCents = int

CENTS_PER_RUPEE: Final = 100

CURRENCY_CODE: Final = "LKR"

# A cost schedule is published by the NDRSC and revised over time. Every calculated
# entitlement records which revision produced it, so a recalculation is auditable and a
# schedule change never silently rewrites history.
CostScheduleVersion = Annotated[
    str,
    Field(
        pattern=r"^\d{4}\.\d{2}(?:\.\d+)?$",
        description="NDRSC cost schedule revision, e.g. 2025.11 or 2025.11.2",
    ),
]


def rupees_to_cents(rupees: Decimal | int | str) -> LKRCents:
    """Convert a rupee amount to minor units, rounding half up to the nearest cent.

    Accepts Decimal, int or str. Deliberately does not accept float: binary floating
    point cannot represent 0.1 exactly, and this value ends up in a disbursement.
    """
    if isinstance(rupees, float):  # pragma: no cover - guarded by the type signature
        raise TypeError("float is not accepted for money; pass Decimal, int or str")
    amount = Decimal(rupees) if not isinstance(rupees, Decimal) else rupees
    minor = (amount * CENTS_PER_RUPEE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(minor)


def cents_to_rupees(cents: LKRCents) -> Decimal:
    """Convert minor units to an exact Decimal rupee amount."""
    return (Decimal(cents) / CENTS_PER_RUPEE).quantize(Decimal("0.01"))


def format_lkr(cents: LKRCents, *, with_symbol: bool = True, group: bool = True) -> str:
    """Render minor units for display, e.g. `LKR 1,250,000.00`.

    Rendering happens only at the boundary. Nothing downstream of this function should
    parse the string back into a number.
    """
    amount = cents_to_rupees(abs(cents))
    body = f"{amount:,.2f}" if group else f"{amount:.2f}"
    sign = "-" if cents < 0 else ""
    return f"{sign}{CURRENCY_CODE} {body}" if with_symbol else f"{sign}{body}"


class Money(BaseModel):
    """An LKR amount bound to the cost schedule revision that produced it.

    Two Money values from different schedule versions are not interchangeable: adding
    them raises rather than silently mixing entitlement bases.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cents: LKRCents = Field(description="LKR minor units. 100 = LKR 1.00.")
    cost_schedule_version: CostScheduleVersion

    @model_validator(mode="after")
    def _reject_absurd(self) -> Self:
        # A guard against a units mix-up (rupees passed where cents were expected).
        # LKR 100bn in minor units is far beyond any single household entitlement.
        if abs(self.cents) > 10_000_000_000_000:
            raise ValueError(
                f"{self.cents} minor units is implausible for a single amount; "
                "check whether rupees were passed where cents were expected"
            )
        return self

    def __add__(self, other: Money) -> Money:
        self._assert_same_schedule(other)
        return Money(
            cents=self.cents + other.cents,
            cost_schedule_version=self.cost_schedule_version,
        )

    def __sub__(self, other: Money) -> Money:
        self._assert_same_schedule(other)
        return Money(
            cents=self.cents - other.cents,
            cost_schedule_version=self.cost_schedule_version,
        )

    def _assert_same_schedule(self, other: Money) -> None:
        if self.cost_schedule_version != other.cost_schedule_version:
            raise ValueError(
                "refusing to combine amounts from different cost schedules "
                f"({self.cost_schedule_version} and {other.cost_schedule_version}); "
                "recalculate both against one revision first"
            )

    def scaled(self, numerator: int, denominator: int) -> Money:
        """Apply an integer ratio, rounding half up. Used for proportional entitlements.

        Integer arithmetic throughout: a percentage of an entitlement never round-trips
        through a float.
        """
        if denominator == 0:
            raise ValueError("denominator must not be zero")
        scaled = (Decimal(self.cents) * numerator / denominator).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        return Money(cents=int(scaled), cost_schedule_version=self.cost_schedule_version)

    def capped_at(self, ceiling: Money) -> Money:
        """Return this amount, or the ceiling if it is exceeded."""
        self._assert_same_schedule(ceiling)
        return self if self.cents <= ceiling.cents else ceiling

    @property
    def display(self) -> str:
        """Formatted for a UI surface."""
        return format_lkr(self.cents)

    def __str__(self) -> str:
        return f"{self.display} (schedule {self.cost_schedule_version})"
