"""Schema constants for ledger-svc.

Owns the `aid` schema - damage assessments, entitlements, approvals, the hash-chained
Transparent Aid Ledger, anomaly flags and grievances - and its slice of `outbox`.

This is the Sustain loop, and it is the differentiator. Existing tools live entirely in
Respond; nothing in Sri Lanka currently makes aid disbursement independently auditable by
the public.
"""

from __future__ import annotations

from typing import Final

AID_SCHEMA: Final = "aid"

DAMAGE_CATEGORIES: Final[tuple[str, ...]] = (
    "HOUSE_FULL",
    "HOUSE_PARTIAL",
    "HOUSEHOLD_GOODS",
    "LIVELIHOOD_TOOLS",
    "CROP",
    "LIVESTOCK",
    "FISHING_GEAR",
    "DEATH",
    "INJURY",
)

ASSESSMENT_STATUSES: Final[tuple[str, ...]] = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "ACCEPTED",
    "REJECTED",
    "SUPERSEDED",
)

ENTITLEMENT_STATUSES: Final[tuple[str, ...]] = (
    "CALCULATED",
    "AWAITING_DS",
    "AWAITING_DISTRICT",
    "APPROVED",
    "REJECTED",
    "DISBURSED",
)

# DS approves; District Secretariat gives second-level approval above a configurable
# threshold. Two levels, named after the offices that actually hold them.
APPROVAL_LEVELS: Final[tuple[str, ...]] = ("DS", "DISTRICT")
APPROVAL_DECISIONS: Final[tuple[str, ...]] = ("APPROVED", "REJECTED", "RETURNED")

PAYMENT_RAILS: Final[tuple[str, ...]] = ("BANK_TRANSFER", "MOBILE_MONEY", "POST_OFFICE", "CASH")

# ADR-009: a flag is advisory. Every flag needs a human disposition before it can close,
# and the false-positive rate is a first-class tracked metric reported alongside the
# detection rate.
ANOMALY_DISPOSITIONS: Final[tuple[str, ...]] = (
    "OPEN",
    "REVIEWED_NO_ACTION",
    "REVIEWED_ESCALATED",
    "FALSE_POSITIVE",
)

ANOMALY_SUBJECTS: Final[tuple[str, ...]] = (
    "ASSESSMENT",
    "ENTITLEMENT",
    "DISBURSEMENT",
    "GN_DIVISION",
    "COST_SCHEDULE",
)

# ADR-008: any citizen may dispute any assessment, entitlement or disbursement affecting
# their household, through any of these channels.
GRIEVANCE_CHANNELS: Final[tuple[str, ...]] = ("SMS", "USSD", "APP", "IN_PERSON", "PHONE", "WEB")

GRIEVANCE_STATUSES: Final[tuple[str, ...]] = (
    "RECEIVED",
    "ACKNOWLEDGED",
    "UNDER_REVIEW",
    "RESOLVED",
    "REJECTED",
    "ESCALATED",
)

GRIEVANCE_SUBJECTS: Final[tuple[str, ...]] = (
    "ASSESSMENT",
    "ENTITLEMENT",
    "DISBURSEMENT",
    "EXCLUSION",
)
