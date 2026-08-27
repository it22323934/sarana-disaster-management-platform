"""Schema constants for alerting-svc.

Owns the `alerting` schema - CAP alert templates, alerts, channel fan-out and delivery
proof - and its slice of `outbox`.

The values below follow the OASIS Common Alerting Protocol 1.2, so an alert SARANA
produces is directly consumable by anything that already speaks CAP.
"""

from __future__ import annotations

from typing import Final

ALERTING_SCHEMA: Final = "alerting"

CAP_SEVERITIES: Final[tuple[str, ...]] = ("EXTREME", "SEVERE", "MODERATE", "MINOR", "UNKNOWN")
CAP_URGENCIES: Final[tuple[str, ...]] = ("IMMEDIATE", "EXPECTED", "FUTURE", "PAST", "UNKNOWN")
CAP_CERTAINTIES: Final[tuple[str, ...]] = (
    "OBSERVED",
    "LIKELY",
    "POSSIBLE",
    "UNLIKELY",
    "UNKNOWN",
)

HAZARD_TYPES: Final[tuple[str, ...]] = (
    "FLOOD",
    "LANDSLIDE",
    "CYCLONE",
    "DROUGHT",
    "STORM_SURGE",
)

# A template is only dispatchable once a native speaker has reviewed each language.
# Machine translation at dispatch time is never acceptable for a life-safety message.
TEMPLATE_STATUSES: Final[tuple[str, ...]] = (
    "DRAFT",
    "NATIVE_REVIEWED",
    "PUBLISHED",
    "RETIRED",
)

ALERT_STATUSES: Final[tuple[str, ...]] = (
    "DRAFT",
    "PENDING_SIGNOFF",
    "DISPATCHING",
    "DISPATCHED",
    "CANCELLED",
)

# The mesh tier is simulated end to end in Phase 1; there is no LoRa hardware. PAPER_QR
# is the genuinely offline last resort: a printed sheet a GN officer carries door to door.
DISPATCH_CHANNELS: Final[tuple[str, ...]] = (
    "SMS",
    "USSD",
    "PUSH",
    "APP",
    "LORA",
    "RADIO",
    "PAPER_QR",
)

DISPATCH_STATUSES: Final[tuple[str, ...]] = (
    "QUEUED",
    "SENDING",
    "COMPLETED",
    "PARTIAL",
    "FAILED",
)

DELIVERY_STATUSES: Final[tuple[str, ...]] = (
    "QUEUED",
    "SENT",
    "DELIVERED",
    "READ",
    "FAILED",
    "EXPIRED",
)
