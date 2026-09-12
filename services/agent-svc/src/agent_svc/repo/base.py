"""Schema constants for agent-svc.

Owns the `hazard` schema - hazard events, feed readings, impact forecasts and
anticipatory triggers - and its slice of `outbox`.

The Anticipate loop runs from T-7d to T-72h and produces impact forecasts at GN-division
level. Ditwah's red alerts went out 72 hours ahead and the forecast worked; what failed
was everything after it. This schema exists to make the forecast actionable per division
rather than accurate in aggregate.
"""

from __future__ import annotations

from typing import Final

HAZARD_SCHEMA: Final = "hazard"

HAZARD_TYPES: Final[tuple[str, ...]] = (
    "FLOOD",
    "LANDSLIDE",
    "CYCLONE",
    "DROUGHT",
    "STORM_SURGE",
)

HAZARD_STATUSES: Final[tuple[str, ...]] = (
    "MONITORING",
    "DECLARED",
    "ACTIVE",
    "SUBSIDING",
    "CLOSED",
)

# Every one of these is a mock service (file 11). No live integration exists with any
# Sri Lankan government system, and every mock response carries "source": "MOCK".
HAZARD_SOURCES: Final[tuple[str, ...]] = (
    "DEPT_METEOROLOGY",
    "NBRO",
    "DMC",
    "IRRIGATION_DEPT",
    "SATELLITE",
    "FIELD_REPORT",
)

# ADR-007 and the master context: thresholds are rule-based in Phase 1, with a documented
# model seam. `method` records which produced a given forecast so the Learn loop can
# compare them honestly rather than assuming the model is better.
FORECAST_METHODS: Final[tuple[str, ...]] = ("RULE_THRESHOLD", "MODEL")

TRIGGER_ACTIONS: Final[tuple[str, ...]] = (
    "ALERT_DRAFTED",
    "PREPOSITION_REQUESTED",
    "SHELTER_OPENED",
    "EVACUATION_ADVISED",
    "NO_ACTION",
)
