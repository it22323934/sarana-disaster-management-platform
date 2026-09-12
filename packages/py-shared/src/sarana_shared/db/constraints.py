"""CHECK-constraint builders shared by every service's models.

These exist so the same rule is written once. A trilingual constraint spelled slightly
differently in five schemas is five chances for one of them to be wrong, and the one
that is wrong is the one that lets a single-language alert reach a citizen.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint

from sarana_shared.db.sql import localised_check, rationale_privacy_check


def in_list(column: str, values: tuple[str, ...]) -> str:
    """Render `column IN ('a','b')` for a CHECK constraint.

    Written out rather than relying on Python's tuple repr happening to be valid SQL: a
    reviewer should not have to verify that coincidence.
    """
    rendered = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({rendered})"


def localised(column: str, *, nullable: bool = False) -> CheckConstraint:
    """CHECK that a citizen-facing column carries a non-blank si, ta and en.

    Named after the column, so a violation says which field was written in fewer than
    three languages rather than merely that some constraint failed.
    """
    condition = localised_check(column)
    if nullable:
        condition = f"{column} IS NULL OR {condition}"
    return CheckConstraint(condition, name=f"{column}_all_locales")


def no_individual_named(column: str) -> CheckConstraint:
    """CHECK that a JSONB column names no individual, at any nesting depth.

    ADR-009: an anomaly flag describes a pattern that warrants review. It is never
    public and never names an officer. Flagging someone on a statistical artifact can
    end a career, and divisions with genuinely worse damage will legitimately look like
    outliers - that is the damage behaving as expected, not evidence about a person.
    """
    return CheckConstraint(rationale_privacy_check(column), name=f"{column}_names_no_one")


def confidence_range(column: str, *, nullable: bool = False) -> CheckConstraint:
    """CHECK that a confidence score sits in [0, 1]."""
    condition = f"{column} BETWEEN 0 AND 1"
    if nullable:
        condition = f"{column} IS NULL OR {condition}"
    return CheckConstraint(condition, name=f"{column}_range")
