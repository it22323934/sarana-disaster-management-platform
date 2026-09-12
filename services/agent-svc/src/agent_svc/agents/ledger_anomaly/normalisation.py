"""The step that makes this agent defensible: compare a division against its own forecast.

**This is the critical module.** Build file 17 says so and ADR-009 explains why. Everything
else in the agent is arithmetic; this is the part that decides whether the arithmetic means
anything.

## The failure this exists to prevent

A GN division that was genuinely hit hardest will legitimately produce assessments that are
**higher in value, more numerous, and faster to approve** than its neighbours. Every one of
those is a signal the detectors look for. Compared against a national average, the worst-hit
division in the country is the most anomalous division in the country — and the flag that
comes out says, in effect, that somebody's paperwork looks suspicious because their village
was destroyed.

That flag can end a career on a statistical artifact. The officer who assessed the worst
damage is the officer most likely to be flagged, and they are also the one who did the most
work under the worst conditions.

So nothing here compares a division to its peers. Every detector is handed an **expected
profile derived from that division's own impact forecast**, and it scores the gap between
what was predicted and what arrived. A division at `impact_class 4` producing high-value
assessments is expected behaviour and produces no signal. A division at `impact_class 1`
producing the same profile is a question — not an accusation, a question.

## An unsurveyed division is suppressed, not compared

The forecast covers the districts a source warned about, not the whole country. A division
with no forecast has nothing to normalise against, and the tempting fallback — compare it
against the district mean instead — is exactly the peer comparison this module exists to
avoid. So it is suppressed: no expectation, no signal, and the reason is recorded.

That means this agent is blind in unwarned districts. That is the correct trade. A detector
that says nothing is recoverable; a detector that flags an officer for having been in the
wrong village is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import structlog

from agent_svc.agents.ledger_anomaly.ports import Assessment, DivisionContext

_log = structlog.get_logger(__name__)

# What share of a division's households is expected to have a claimable loss, per impact
# class. Read off the forecast's own class definitions: class 2 is NBRO's watch level,
# class 3 its warning level, class 4 its evacuate level.
#
# These are deliberately generous at the top. Over-estimating what a severe division should
# produce means it is not flagged for producing it, and the cost of that is a missed
# detection in the one place a missed detection matters least - somewhere a human is
# already looking, because the division is in the news.
EXPECTED_CLAIM_SHARE: Final[dict[int, float]] = {
    0: 0.02,
    1: 0.08,
    2: 0.25,
    3: 0.60,
    4: 0.95,
}

# The share of claims expected to be total losses rather than partial, per impact class.
# `value_distribution` reads this: assessments clustering at the cap are expected where the
# forecast said the houses would go.
EXPECTED_TOTAL_LOSS_SHARE: Final[dict[int, float]] = {
    0: 0.0,
    1: 0.02,
    2: 0.10,
    3: 0.35,
    4: 0.70,
}

# How far above expectation a division has to be before it is a question at all. Wide,
# because the forecast is a rule-threshold engine over rainfall and not a damage survey -
# it is right about the shape and approximate about the size, and a narrow band would flag
# the imprecision of the forecast rather than anything about the assessments.
TOLERANCE: Final = 2.0

# The floor on the denominator. A division with three assessments produces ratios that
# swing wildly on one row; below this, no detector fires and the reason is recorded.
MIN_ASSESSMENTS: Final = 8

# Categories that are a total loss of the dwelling. `value_distribution` compares their
# share against `EXPECTED_TOTAL_LOSS_SHARE`.
TOTAL_LOSS_CATEGORIES: Final[frozenset[str]] = frozenset({"HOUSE_FULL", "DEATH"})


@dataclass(frozen=True, slots=True)
class Expectation:
    """What this division's assessments should look like, from its own forecast.

    Every field is derived from the impact forecast and the division's household count.
    Nothing here comes from what other divisions did, which is the entire point.
    """

    gn_division_code: str
    impact_class: int
    expected_claims: float
    expected_total_loss_share: float
    normalisable: bool
    reason: str = ""

    def ratio(self, observed: float) -> float:
        """How many times the expectation the observed count is.

        A zero expectation returns the observed count itself rather than dividing by zero:
        at `impact_class 0` any claim at all is above expectation, and saying "3x" where
        the expectation is effectively nothing would understate it.
        """
        if self.expected_claims <= 0:
            return float(observed)
        return observed / self.expected_claims

    def exceeds(self, observed: float, *, tolerance: float = TOLERANCE) -> bool:
        """Whether the observed count is far enough above expectation to be a question."""
        return self.ratio(observed) > tolerance


def expectation_for(context: DivisionContext) -> Expectation:
    """What this division should produce, from its own forecast and nothing else.

    An unsurveyed division returns `normalisable=False` with the reason. See the module
    docstring on why falling back to a peer comparison would be worse than being blind.
    """
    if not context.surveyed:
        return Expectation(
            gn_division_code=context.gn_division_code,
            impact_class=context.impact_class,
            expected_claims=0.0,
            expected_total_loss_share=0.0,
            normalisable=False,
            reason=(
                "no impact forecast covers this division, so there is nothing to normalise "
                "against. Comparing it with its neighbours instead would flag whichever "
                "division was hit hardest, which is the failure this agent is arranged to "
                "avoid."
            ),
        )

    households = max(context.household_count, context.expected_households_affected)
    share = EXPECTED_CLAIM_SHARE.get(context.impact_class, EXPECTED_CLAIM_SHARE[0])

    return Expectation(
        gn_division_code=context.gn_division_code,
        impact_class=context.impact_class,
        # The forecast's own household estimate wins when it is larger: it already accounts
        # for the event, where the static household count only counts doors.
        expected_claims=max(float(context.expected_households_affected), households * share),
        expected_total_loss_share=EXPECTED_TOTAL_LOSS_SHARE.get(context.impact_class, 0.0),
        normalisable=True,
    )


@dataclass(frozen=True, slots=True)
class DivisionProfile:
    """What a division's assessments actually look like, beside what they should.

    The pair is the unit every detector works on. Neither half is meaningful alone: the
    observed profile without the expectation is a peer comparison waiting to happen, and
    the expectation without the observation is a forecast.
    """

    gn_division_code: str
    assessments: list[Assessment]
    context: DivisionContext
    expectation: Expectation

    @property
    def count(self) -> int:
        return len(self.assessments)

    @property
    def enough_data(self) -> bool:
        """Whether there are enough rows for a ratio to mean anything."""
        return self.count >= MIN_ASSESSMENTS

    @property
    def normalisable(self) -> bool:
        """Whether any detector may fire on this division at all."""
        return self.expectation.normalisable and self.enough_data

    @property
    def suppression_reason(self) -> str | None:
        """Why no detector will run here, or None if they will."""
        if not self.expectation.normalisable:
            return self.expectation.reason
        if not self.enough_data:
            return (
                f"only {self.count} assessments in this division, below the "
                f"{MIN_ASSESSMENTS} needed for a ratio to mean anything. A division with a "
                "handful of rows produces figures that swing on a single one."
            )
        return None

    @property
    def total_loss_share(self) -> float:
        if not self.assessments:
            return 0.0
        total = sum(1 for item in self.assessments if item.category in TOTAL_LOSS_CATEGORIES)
        return total / self.count

    @property
    def confirmation_rate(self) -> float | None:
        """Share of assessments a citizen confirmed, over those where it is known.

        `None` when nobody has been asked yet. Distinct from zero: a division where
        confirmation has not started and one where everybody said no look identical in a
        bare ratio and mean opposite things.
        """
        known = [item for item in self.assessments if item.citizen_confirmed is not None]
        if not known:
            return None
        return sum(1 for item in known if item.citizen_confirmed) / len(known)


def build_profiles(
    assessments: list[Assessment], context: dict[str, DivisionContext]
) -> list[DivisionProfile]:
    """Group assessments by division and pair each group with its expectation.

    **Grouped by division, never by person.** This function is where the unit of analysis
    is fixed, and it is fixed to the GN division because ADR-009 forbids officer identity
    as a feature - including as a proxy, which is what "assessments per assessor" would be.
    """
    grouped: dict[str, list[Assessment]] = {}
    for item in assessments:
        grouped.setdefault(item.gn_division_code, []).append(item)

    profiles: list[DivisionProfile] = []
    for code, rows in sorted(grouped.items()):
        division = context.get(code, DivisionContext(gn_division_code=code))
        profiles.append(
            DivisionProfile(
                gn_division_code=code,
                assessments=rows,
                context=division,
                expectation=expectation_for(division),
            )
        )

    suppressed = [profile for profile in profiles if not profile.normalisable]
    if suppressed:
        _log.info(
            "anomaly_divisions_not_normalisable",
            divisions=len(suppressed),
            of=len(profiles),
            impact="no detector runs on these; being blind is better than comparing a "
            "division against its neighbours",
        )
    return profiles
