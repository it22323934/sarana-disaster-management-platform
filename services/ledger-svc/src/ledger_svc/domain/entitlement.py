"""Entitlement calculation, and the trace that makes it auditable.

**The trace is the product.** A number without one is exactly the opacity this platform
exists to replace: "you were assessed at 47,500 rupees" is not something a household can
argue with, and "house fully damaged, 250,000 per the March schedule, capped at the
per-household ceiling of 200,000, less 152,500 already disbursed" is.

Three properties hold, and each is tested:

  **Pure.** No I/O, no clock, no randomness, no model. The same assessment and the same
  schedule version produce the same number forever.

  **Pinned.** An entitlement records the schedule version it used. A new government
  schedule does not move existing entitlements; recalculation is an explicit, audited
  action that supersedes rather than edits.

  **Integer.** Money is integer cents throughout. A float would make the hash chain
  depend on the platform's floating-point behaviour, and would eventually lose a cent
  where somebody notices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final
from uuid import UUID

# Damage categories, matching `aid.assessment`'s CHECK constraint.
from ledger_svc.repo.base import DAMAGE_CATEGORIES

# The per-household ceiling across all categories in one event. Without it, an assessment
# listing every category at full value produces a number nobody would approve and everyone
# would have to argue down by hand.
DEFAULT_HOUSEHOLD_CAP_CENTS: Final = 200_000_00


class CalculationRefused(ValueError):
    """The entitlement cannot be computed as specified.

    Always a refusal, never a fallback to zero. A silently-zero entitlement is a household
    that receives nothing and has no reason recorded.
    """


@dataclass(frozen=True, slots=True)
class ScheduleLine:
    """One line of a published cost schedule."""

    line_id: UUID
    category: str
    unit_amount_cents: int
    max_units: int
    formula: str

    def __post_init__(self) -> None:
        if self.category not in DAMAGE_CATEGORIES:
            raise CalculationRefused(
                f"{self.category!r} is not a damage category the schema allows"
            )
        if self.unit_amount_cents < 0:
            raise CalculationRefused("a schedule line cannot carry a negative amount")


@dataclass(frozen=True, slots=True)
class CostSchedule:
    """A published, versioned cost schedule.

    Immutable. A new schedule is a new version, because an entitlement that pinned this
    one must be recomputable from it years later during an audit.
    """

    version: str
    lines: dict[str, ScheduleLine]
    household_cap_cents: int = DEFAULT_HOUSEHOLD_CAP_CENTS
    published_at: datetime | None = None

    def __post_init__(self) -> None:
        # A line whose single unit already exceeds the household ceiling can never be paid
        # in full. That is almost always a misconfigured schedule, and finding out one
        # household at a time - each capped, each needing an explanation - is the
        # expensive way to discover it.
        for line in self.lines.values():
            if line.unit_amount_cents > self.household_cap_cents:
                raise CalculationRefused(
                    f"schedule {self.version}: {line.category} is priced at "
                    f"{line.unit_amount_cents} but the household ceiling is "
                    f"{self.household_cap_cents}, so this category can never be paid in "
                    "full. Raise the ceiling or reprice the line."
                )

    def line_for(self, category: str) -> ScheduleLine:
        line = self.lines.get(category)
        if line is None:
            raise CalculationRefused(
                f"the {self.version} schedule has no line for {category!r}. An assessment "
                "cannot be valued against a schedule that does not price it."
            )
        return line


@dataclass(frozen=True, slots=True)
class AssessedItem:
    """One damage line from a GN officer's assessment."""

    category: str
    units: int

    def __post_init__(self) -> None:
        if self.units < 0:
            raise CalculationRefused(f"{self.category}: units cannot be negative")


@dataclass(frozen=True, slots=True)
class CalculationStep:
    """One step of the working, in the order it was applied."""

    description: str
    expression: str
    result_cents: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "expression": self.expression,
            "result_cents": self.result_cents,
        }


@dataclass(frozen=True, slots=True)
class CalculationTrace:
    """Everything needed to check the number by hand.

    Attached to the anonymised public record. Mandatory and immutable: it is written once
    with the entitlement and never edited, because a trace that can be revised proves
    nothing about what was decided.
    """

    cost_schedule_version: str
    formula: str
    inputs: dict[str, int | str]
    steps: list[CalculationStep]
    result_lkr_cents: int
    caps_applied: list[str] = field(default_factory=list)
    schedule_line_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """The stored and published form.

        `computed_at` is deliberately absent. The trace goes into the hash chain, and a
        timestamp would make two identical calculations hash differently - which would
        defeat the determinism property this module exists to guarantee. When the
        calculation happened is a property of the entitlement row, not of the working.
        """
        return {
            "cost_schedule_version": self.cost_schedule_version,
            "formula": self.formula,
            "inputs": dict(self.inputs),
            "steps": [step.as_dict() for step in self.steps],
            "result_lkr_cents": self.result_lkr_cents,
            "caps_applied": list(self.caps_applied),
            "schedule_line_ids": list(self.schedule_line_ids),
        }

    def as_sentence(self) -> str:
        """The working in one line, for an SMS or a printed slip."""
        parts = [f"{step.description}: {step.result_cents / 100:,.2f}" for step in self.steps]
        caps = f" (capped: {', '.join(self.caps_applied)})" if self.caps_applied else ""
        return "; ".join(parts) + caps


def calculate(
    items: list[AssessedItem], schedule: CostSchedule, *, already_disbursed_cents: int = 0
) -> CalculationTrace:
    """Value an assessment against a pinned schedule.

    Deterministic and total: every path either produces a trace or raises. There is no
    branch that returns a number without the working that produced it.
    """
    if already_disbursed_cents < 0:
        raise CalculationRefused("already-disbursed cannot be negative")

    steps: list[CalculationStep] = []
    caps: list[str] = []
    line_ids: list[str] = []
    inputs: dict[str, int | str] = {"cost_schedule_version": schedule.version}
    running = 0

    # Sorted by category so the same assessment always produces the same trace, whatever
    # order the officer entered the lines in. Two identical assessments must hash alike.
    for item in sorted(items, key=lambda entry: entry.category):
        line = schedule.line_for(item.category)
        line_ids.append(str(line.line_id))

        units = item.units
        if units > line.max_units:
            caps.append(f"{item.category}: units capped at {line.max_units}")
            units = line.max_units

        amount = units * line.unit_amount_cents
        running += amount
        inputs[f"units:{item.category}"] = item.units

        steps.append(
            CalculationStep(
                description=f"{item.category} x{units}",
                expression=f"{units} * {line.unit_amount_cents}",
                result_cents=amount,
            )
        )

    subtotal = running
    steps.append(
        CalculationStep(
            description="subtotal",
            expression=" + ".join(str(step.result_cents) for step in steps) or "0",
            result_cents=subtotal,
        )
    )

    if running > schedule.household_cap_cents:
        caps.append(f"household ceiling {schedule.household_cap_cents}")
        running = schedule.household_cap_cents
        steps.append(
            CalculationStep(
                description="household ceiling applied",
                expression=f"min({subtotal}, {schedule.household_cap_cents})",
                result_cents=running,
            )
        )

    if already_disbursed_cents:
        inputs["already_disbursed_cents"] = already_disbursed_cents
        before = running
        # Never negative: a household that has already received more than the schedule
        # allows is owed nothing further, not asked for money back by an arithmetic
        # accident.
        running = max(0, running - already_disbursed_cents)
        steps.append(
            CalculationStep(
                description="less already disbursed",
                expression=f"max(0, {before} - {already_disbursed_cents})",
                result_cents=running,
            )
        )

    return CalculationTrace(
        cost_schedule_version=schedule.version,
        formula=" + ".join(
            schedule.line_for(item.category).formula
            for item in sorted(items, key=lambda entry: entry.category)
        )
        or "0",
        inputs=inputs,
        steps=steps,
        result_lkr_cents=running,
        caps_applied=caps,
        schedule_line_ids=line_ids,
    )
