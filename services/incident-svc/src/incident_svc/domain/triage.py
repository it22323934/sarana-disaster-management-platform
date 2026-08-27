"""Deterministic triage, used whenever assisted ranking is unavailable.

This is not a degraded copy of the agent's model. It is a published formula a dispatcher
can check by hand, and that is the point: when the ranking is produced by a rule, the rule
is shown, and when it is produced by a model, the dispatcher is told that instead.

The failure this exists to prevent is a dispatcher believing an ordered list is
intelligent when it is arbitrary. An unranked queue that says so is safe. A queue that
looks ranked and is not gets someone left at the bottom of it.

Every weight below is a policy decision, not a tuned parameter. They are written here in
one place so a DMC officer can argue with them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from sarana_shared.domain.time import utc_now

# How much each factor can contribute. They sum to 1.0 so the score is readable as a
# fraction, and a dispatcher can see which half of the score came from which concern.
WEIGHT_PEOPLE_AT_RISK: Final = 0.40
WEIGHT_VULNERABILITY: Final = 0.20
WEIGHT_INCIDENT_TYPE: Final = 0.25
WEIGHT_AGE: Final = 0.15

# The count at which the people-at-risk factor saturates. Beyond this the incident is
# already the most serious kind there is, and further scaling would let one very large
# report crowd out every other.
PEOPLE_SATURATION: Final = 50

# Minutes after which the age factor saturates. Two hours: long enough that a fresh report
# does not outrank a serious older one, short enough that nothing waits a whole shift.
AGE_SATURATION_MINUTES: Final = 120

# Incident type weights, ordered by how quickly the situation kills someone unattended.
#
# The keys are exactly `incident.incident`'s CHECK vocabulary. A weight for a type the
# database rejects would be dead code; a type with no weight would silently drop to the
# mid-table default, which is the quieter and worse failure. A test asserts the two lists
# match.
INCIDENT_TYPE_WEIGHTS: Final[dict[str, float]] = {
    "MEDICAL": 1.00,
    "TRAPPED": 1.00,
    "STRUCTURAL_COLLAPSE": 0.95,
    "LANDSLIDE": 0.90,
    "FLOOD": 0.75,
    "MISSING_PERSON": 0.70,
    "EVACUATION_NEEDED": 0.65,
    "SUPPLIES_NEEDED": 0.40,
    "INFRASTRUCTURE": 0.35,
    "OTHER": 0.30,
}

# An unrecognised type sits mid-table rather than at either end. Bottom would bury a real
# emergency someone described in words we did not anticipate; top would let any unknown
# string jump the queue.
UNKNOWN_TYPE_WEIGHT: Final = 0.50

MODEL_VERSION: Final = "rule-v1"


@dataclass(frozen=True, slots=True)
class TriageInput:
    """What the rule needs. Everything is already known at intake."""

    incident_type: str
    people_at_risk: int
    minutes_since_reported: float
    has_over_70: bool = False
    has_under_5: bool = False
    has_mobility_impairment: bool = False


@dataclass(frozen=True, slots=True)
class TriageResult:
    """A score, and every factor that produced it.

    `factors` is stored on the row and shown in the UI. A ranking a dispatcher cannot
    interrogate is one they will either over-trust or ignore entirely.
    """

    score: float
    factors: dict[str, Any]
    model_version: str = MODEL_VERSION
    assisted: bool = False

    @property
    def explanation(self) -> str:
        """One line, in the order the weights are applied."""
        parts = [
            f"{name}={value:.2f}"
            for name, value in self.factors.items()
            if isinstance(value, int | float)
        ]
        return f"{self.model_version}: " + ", ".join(parts)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def type_weight(incident_type: str) -> float:
    """The weight for an incident type, or the mid-table default."""
    return INCIDENT_TYPE_WEIGHTS.get(incident_type.upper(), UNKNOWN_TYPE_WEIGHT)


def score(candidate: TriageInput) -> TriageResult:
    """Rank one incident.

    Higher is more urgent. The result is in [0, 1] so two queues scored at different times
    remain comparable.
    """
    people = _clamp(candidate.people_at_risk / PEOPLE_SATURATION)

    # Vulnerability is a maximum rather than a sum: a household with an infant and a
    # grandparent is not twice as urgent as one with either, and adding them would let
    # household composition outweigh how many people are actually in danger.
    vulnerability = _clamp(
        max(
            0.9 if candidate.has_over_70 else 0.0,
            0.9 if candidate.has_under_5 else 0.0,
            1.0 if candidate.has_mobility_impairment else 0.0,
        )
    )

    type_factor = _clamp(type_weight(candidate.incident_type))
    age = _clamp(candidate.minutes_since_reported / AGE_SATURATION_MINUTES)

    total = (
        WEIGHT_PEOPLE_AT_RISK * people
        + WEIGHT_VULNERABILITY * vulnerability
        + WEIGHT_INCIDENT_TYPE * type_factor
        + WEIGHT_AGE * age
    )

    return TriageResult(
        score=round(_clamp(total), 4),
        factors={
            "people_at_risk": round(people, 4),
            "vulnerability": round(vulnerability, 4),
            "incident_type": round(type_factor, 4),
            "age": round(age, 4),
            "weights": {
                "people_at_risk": WEIGHT_PEOPLE_AT_RISK,
                "vulnerability": WEIGHT_VULNERABILITY,
                "incident_type": WEIGHT_INCIDENT_TYPE,
                "age": WEIGHT_AGE,
            },
            "raw": {
                "people_at_risk": candidate.people_at_risk,
                "minutes_since_reported": round(candidate.minutes_since_reported, 1),
                "incident_type": candidate.incident_type,
            },
        },
    )


def score_row(row: dict[str, Any]) -> TriageResult:
    """Score an incident row straight from the database."""
    first_reported = row.get("first_reported_at")
    minutes = 0.0
    if first_reported is not None:
        minutes = max(0.0, (utc_now() - first_reported).total_seconds() / 60.0)

    return score(
        TriageInput(
            incident_type=str(row.get("type") or "OTHER"),
            people_at_risk=int(row.get("people_at_risk") or 0),
            minutes_since_reported=minutes,
            has_over_70=bool(row.get("has_over_70")),
            has_under_5=bool(row.get("has_under_5")),
            has_mobility_impairment=bool(row.get("has_mobility_impairment")),
        )
    )
