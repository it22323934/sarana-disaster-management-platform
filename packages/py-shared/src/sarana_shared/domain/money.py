"""LKR money as integer minor units — never a float, never a bare Decimal-in-JSON.

Per docs/build-prompts/02-conventions.md: "LKR minor units as integers. Type alias
LKRCents = int. Format only at the render boundary. Every monetary field carries the
cost_schedule_version that produced it."
"""

from __future__ import annotations

from typing import NewType

LKRCents = NewType("LKRCents", int)
"""1 LKRCents = LKR 0.01. A `LKRCents` is always a whole number of cents — construct it
with `to_lkr_cents`, never by casting a float directly."""


def to_lkr_cents(rupees: str | int | float) -> LKRCents:
    """Parse a rupee amount into LKRCents. Accepts a string ("1250.50") to avoid float
    rounding entirely; a float/int input is rounded to the nearest cent (used only for
    values that are already known-exact, e.g. a rate already stored as a float column
    from an external mock — never for a value a citizen typed in)."""
    if isinstance(rupees, str):
        whole, _, frac = rupees.strip().replace(",", "").partition(".")
        frac = (frac + "00")[:2]
        sign = -1 if whole.startswith("-") else 1
        whole = whole.lstrip("-")
        return LKRCents(sign * (int(whole or "0") * 100 + int(frac)))
    return LKRCents(round(float(rupees) * 100))


def format_lkr(cents: LKRCents) -> str:
    """Rs. X,XXX.XX — the one money format used everywhere in the UI regardless of
    locale (docs/build-prompts/20-ops-console.md: "a mixed-language operations room
    needs one unambiguous money format")."""
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(int(cents)), 100)
    return f"{sign}Rs. {whole:,}.{frac:02d}"


def add(*amounts: LKRCents) -> LKRCents:
    return LKRCents(sum(int(a) for a in amounts))


def apply_rate(base: LKRCents, multiplier: float) -> LKRCents:
    """Round-half-up to the nearest cent — used by the entitlement calculator, which
    must be pure and deterministic (docs/build-prompts/10-aid-ledger-service.md)."""
    return LKRCents(int(int(base) * multiplier + 0.5))


def apply_cap(amount: LKRCents, cap: LKRCents | None) -> tuple[LKRCents, bool]:
    """Returns (final_amount, was_capped)."""
    if cap is not None and amount > cap:
        return cap, True
    return amount, False
