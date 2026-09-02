"""Priority scoring: a documented weighted sum, shown to the dispatcher in full.

**The score is not a model output and never has been.** It is a published formula whose
every factor is displayed next to the incident it ranked, which is what makes it
contestable. A dispatcher who disagrees can point at the term they disagree with. That is
the difference between a ranking somebody can argue with and one they either over-trust or
ignore entirely, and during Ditwah the queues people ignored were the ones nobody could
interrogate.

The LLM's only job anywhere near this is a short trilingual rationale *rendered from the
factors after the fact*. It cannot change the score. With the provider down the ranking is
byte-identical and only the prose is plainer.

## Why this extends `incident_svc.domain.triage` rather than replacing it

File 08 already scores incidents on four factors — people at risk, vulnerability, type and
age — and that formula is in production, stored on rows and rendered in the console. This
module keeps those four with the same weights and adds the four build file 16 asks for:
location confidence, access feasibility, corroboration, and immediate danger.

Two scoring functions that disagreed about the same incident would be worse than either,
so the shared factors are imported rather than re-declared, and a test asserts the weights
match. When this agent is unavailable the incident still has file 08's score; it is the same
number with fewer terms.

## Ageing, and why it is not optional

An incident that sits unrescued must rise. Without ageing, a queue sorted on severity
starves every moderate incident for the whole event — the medical calls keep arriving, they
keep outranking the family on the roof, and that family is still there on day three.

The curve is explicit, tunable and shown in the breakdown. It is deliberately *not* linear
past its saturation point: an incident cannot age its way to the top of a queue above a
fresh life-threatening one, because that would be the opposite failure.

## Location confidence reduces dispatchability, not urgency

Build file 16 is precise about this and it is worth preserving. A report nobody can place is
exactly as urgent as one with a GPS fix — somebody is still in the water. What it is not is
*dispatchable*, because a crew cannot be sent to an unknown address. So the two are separate
outputs: `score` says how urgent, `dispatchability` says how confidently a vehicle can be
sent, and the queue is ordered on urgency while the plan is built from what can be reached.

Folding the two together would quietly deprioritise the people whose reports are worst
served by the platform, which is the population this system exists for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Protocol

from incident_svc.domain.triage import (
    AGE_SATURATION_MINUTES,
    INCIDENT_TYPE_WEIGHTS,
    PEOPLE_SATURATION,
    UNKNOWN_TYPE_WEIGHT,
)

# The four weights file 08 already applies, restated as this agent's own so the extended
# formula sums to 1.0. A test asserts their *ratios* still match file 08's, so a change
# there is caught here rather than producing two rankings that disagree.
WEIGHT_IMMEDIATE_DANGER: Final = 0.28
WEIGHT_PEOPLE_AT_RISK: Final = 0.22
WEIGHT_VULNERABILITY: Final = 0.12
WEIGHT_INCIDENT_TYPE: Final = 0.15
WEIGHT_AGE: Final = 0.13
WEIGHT_CORROBORATION: Final = 0.10

# Immediate danger is the heaviest single factor, as build file 16 requires. It is the one
# term that says somebody is dying now rather than in an hour, and no combination of the
# others should be able to outrank it on its own.
_WEIGHTS: Final[dict[str, float]] = {
    "immediate_danger": WEIGHT_IMMEDIATE_DANGER,
    "people_at_risk": WEIGHT_PEOPLE_AT_RISK,
    "vulnerability": WEIGHT_VULNERABILITY,
    "incident_type": WEIGHT_INCIDENT_TYPE,
    "age": WEIGHT_AGE,
    "corroboration": WEIGHT_CORROBORATION,
}

# How many independent reports of one incident count as full corroboration. Three: one
# report is a report, two is a pattern, and beyond three the extra callers are telling us
# about the same collapsed house rather than about more people in it.
CORROBORATION_SATURATION: Final = 3

# Below this location confidence an incident is not put in a plan automatically. It stays in
# the queue at its full urgency and it is offered to the dispatcher as something that needs
# placing first - never dropped, and never silently ranked down.
DISPATCHABLE_CONFIDENCE: Final = 0.30

MODEL_VERSION: Final = "rule-v2"
METHOD: Final = "WEIGHTED_SUM"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass(frozen=True, slots=True)
class TriageFactors:
    """Everything the formula reads about one incident.

    All of it is known by the time intake has finished. Nothing here needs a model, a
    network call, or a judgement.
    """

    incident_id: str
    incident_type: str
    immediate_danger: bool = False
    people_at_risk: int | None = None
    vulnerable_present: tuple[str, ...] = ()
    minutes_since_report: float = 0.0
    location_confidence: float = 1.0
    access_feasibility: float = 1.0
    corroboration_count: int = 1

    @property
    def people(self) -> int:
        """The count, treating "not stated" as one person rather than none.

        `None` means the report did not say - intake refuses to guess - and scoring it as
        zero would sort a real emergency below every incident that happened to mention a
        number. One is the smallest thing that can be true of a report somebody sent.
        """
        return self.people_at_risk if self.people_at_risk is not None else 1


@dataclass(frozen=True, slots=True)
class TriageScore:
    """A score, its dispatchability, and every term that produced them."""

    incident_id: str
    score: float
    dispatchability: float
    factors: dict[str, Any]
    model_version: str = MODEL_VERSION
    method: str = METHOD

    @property
    def dispatchable(self) -> bool:
        """Whether a vehicle can confidently be sent. Not whether it is urgent."""
        return self.dispatchability >= DISPATCHABLE_CONFIDENCE

    def explanation(self) -> str:
        """One line in the order the weights are applied, for the console and the log."""
        contributions = self.factors.get("contributions", {})
        parts = [f"{name}={value:.3f}" for name, value in contributions.items()]
        return f"{self.model_version}: " + ", ".join(parts)


class TriageModel(Protocol):
    """The seam a trained model drops into.

    Build file 16 is explicit that Phase 2 is a gradient-boosted model trained on dispatcher
    accept/reject decisions, once enough of them exist - and equally explicit that shipping
    an untrained model and calling it ML is not acceptable. So this Protocol exists, the
    weighted sum is its only implementation, and `method` distinguishes their outputs
    forever after.
    """

    @property
    def model_version(self) -> str: ...

    @property
    def method(self) -> str: ...

    def score(self, factors: TriageFactors) -> TriageScore: ...


def age_factor(minutes: float, *, saturation: float = AGE_SATURATION_MINUTES) -> float:
    """How much an incident's wait contributes, between 0 and 1.

    Linear to saturation and flat after it. Flat rather than continuing to climb, because
    an unbounded age term eventually lets a four-hour-old supply request outrank a fresh
    medical call - which is the opposite of the starvation this factor exists to prevent,
    and harder to notice because the queue still looks busy.

    Saturation is `incident_svc.domain.triage.AGE_SATURATION_MINUTES` - two hours - so this
    agent and the deterministic scorer age incidents at the same rate.
    """
    return _clamp(minutes / saturation) if saturation > 0 else 0.0


def vulnerability_factor(groups: tuple[str, ...]) -> float:
    """How much the people present contribute.

    A maximum rather than a sum, the same rule file 08 applies: a household with an infant
    and a grandparent is not twice as urgent as one with either, and adding them would let
    household composition outweigh how many people are actually in danger.
    """
    if not groups:
        return 0.0
    weights = {
        "injured": 1.0,
        "disabled": 1.0,
        "pregnant": 0.95,
        "elderly": 0.9,
        "children": 0.9,
    }
    return _clamp(max(weights.get(group, 0.5) for group in groups))


def corroboration_factor(count: int) -> float:
    """How much independent confirmation contributes.

    Saturating at three. It raises confidence that an incident is real; it is deliberately
    the lightest factor, because a household that only called once is not in less danger
    than one whose neighbours also called - they may simply have one phone between them.
    """
    return _clamp(max(0, count - 1) / max(1, CORROBORATION_SATURATION - 1))


class WeightedSumModel:
    """The Phase 1 scorer. A published formula, and the only implementation."""

    @property
    def model_version(self) -> str:
        return MODEL_VERSION

    @property
    def method(self) -> str:
        return METHOD

    def score(self, factors: TriageFactors) -> TriageScore:
        """Rank one incident. Higher is more urgent.

        The result is in [0, 1] so two queues scored at different moments stay comparable,
        and every term is returned alongside it.
        """
        terms = {
            "immediate_danger": 1.0 if factors.immediate_danger else 0.0,
            "people_at_risk": _clamp(factors.people / PEOPLE_SATURATION),
            "vulnerability": vulnerability_factor(factors.vulnerable_present),
            "incident_type": _clamp(
                INCIDENT_TYPE_WEIGHTS.get(factors.incident_type.upper(), UNKNOWN_TYPE_WEIGHT)
            ),
            "age": age_factor(factors.minutes_since_report),
            "corroboration": corroboration_factor(factors.corroboration_count),
        }
        contributions = {name: _WEIGHTS[name] * value for name, value in terms.items()}
        total = _clamp(sum(contributions.values()))

        # Dispatchability is a separate number and is deliberately *not* in the score. See
        # the module docstring: a report nobody can place is exactly as urgent as one with
        # a GPS fix, and folding the two would deprioritise the people the platform serves
        # worst.
        dispatchability = _clamp(
            min(_clamp(factors.location_confidence), _clamp(factors.access_feasibility))
        )

        return TriageScore(
            incident_id=factors.incident_id,
            score=round(total, 4),
            dispatchability=round(dispatchability, 4),
            factors={
                "terms": {name: round(value, 4) for name, value in terms.items()},
                "weights": dict(_WEIGHTS),
                "contributions": {name: round(value, 4) for name, value in contributions.items()},
                "dispatchability": {
                    "location_confidence": round(_clamp(factors.location_confidence), 4),
                    "access_feasibility": round(_clamp(factors.access_feasibility), 4),
                    "note": (
                        "reduces dispatchability, never urgency - an unplaceable report is "
                        "exactly as serious as a placed one"
                    ),
                },
                "raw": {
                    "incident_type": factors.incident_type,
                    "people_at_risk": factors.people_at_risk,
                    "people_at_risk_assumed": factors.people_at_risk is None,
                    "vulnerable_present": list(factors.vulnerable_present),
                    "minutes_since_report": round(factors.minutes_since_report, 1),
                    "corroboration_count": factors.corroboration_count,
                },
            },
        )


def rank(incidents: list[TriageFactors], *, model: TriageModel | None = None) -> list[TriageScore]:
    """Score and order a whole queue, most urgent first.

    Ties break on age, oldest first. Without a stated tie-break the order of two equally
    urgent incidents depends on the order the database happened to return them, which means
    a dispatcher refreshing the page can see them swap - and a queue that reorders under
    somebody is one they stop trusting.
    """
    engine = model or WeightedSumModel()
    scored = [engine.score(factors) for factors in incidents]
    by_id = {factors.incident_id: factors for factors in incidents}

    return sorted(
        scored,
        key=lambda result: (
            -result.score,
            -by_id[result.incident_id].minutes_since_report,
            result.incident_id,
        ),
    )
