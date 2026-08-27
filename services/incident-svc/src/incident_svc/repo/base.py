"""Schema constants for incident-svc.

Owns the `incident` schema - citizen reports, verification, deduplication, triage and
dispatch planning - and its slice of `outbox`.
"""

from __future__ import annotations

from typing import Final

INCIDENT_SCHEMA: Final = "incident"

EMBEDDING_DIMENSIONS: Final = 1024

# Report processing states. RECEIVED is where a citizen report lands; HUMAN_REVIEW is
# where low-confidence transcription or translation goes, and it never auto-publishes.
PROCESSING_STATUSES: Final[tuple[str, ...]] = (
    "RECEIVED",
    "TRANSCRIBING",
    "VERIFYING",
    "LINKED",
    "REJECTED",
    "HUMAN_REVIEW",
)

INCIDENT_STATUSES: Final[tuple[str, ...]] = (
    "REPORTED",
    "VERIFIED",
    "TRIAGED",
    "DISPATCHED",
    "IN_PROGRESS",
    "RESOLVED",
    "DUPLICATE",
    "REJECTED",
)

# A dispatch plan may only reach RELEASED through a recorded human decision. That is one
# of the two mandatory gates, and it is enforced by a trigger, not only by these values.
DISPATCH_STATUSES: Final[tuple[str, ...]] = (
    "PROPOSED",
    "AWAITING_SIGNOFF",
    "APPROVED",
    "REJECTED",
    "RELEASED",
    "COMPLETED",
)

INTAKE_CHANNELS: Final[tuple[str, ...]] = (
    "SMS",
    "USSD",
    "VOICE",
    "APP",
    "WEB",
    "LORA",
    "FIELD_OFFICER",
    "PARTNER_API",
)

LOCATION_SOURCES: Final[tuple[str, ...]] = ("gps", "cell", "manual", "inferred")
