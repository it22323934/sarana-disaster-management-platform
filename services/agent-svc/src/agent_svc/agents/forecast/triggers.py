"""Anticipatory triggers: conditions agreed before the disaster, evaluated during it.

Anticipatory action only works if the condition was agreed in advance. During an event
there is no time to argue about whether 140 mm on a zone 3 slope justifies prepositioning,
and the argument is not improved by having it at 2 a.m. with a district secretary on the
phone. So the rule is written down in the quiet years, published, and the platform's job is
to notice when it is met.

## Triggers notify. They do not dispatch and they do not spend.

The strongest thing a trigger can do is put a message in front of a person. Nothing here
moves a crew, releases money, or sends a public alert - those all have their own human gates
and their own agents, and a forecast that could reach through to them would be a forecast
that could evacuate a district on a bad rainfall estimate.

`PREPOSITION_REQUESTED` is a *request*. Somebody still says yes.

## Every firing records the forecast that caused it

`anticipatory_trigger.forecast_id` points at the exact row. Without it an after-action
review can establish that a trigger fired and cannot establish whether it should have -
which is the only question worth asking about a pre-agreed rule, and the reason for
pre-agreeing it.

## The vocabulary the schema allows

Build file 13's example action is `NOTIFY_DS_PREPOSITION`. `agent_svc.repo.base
.TRIGGER_ACTIONS` allows `ALERT_DRAFTED`, `PREPOSITION_REQUESTED`, `SHELTER_OPENED`,
`EVACUATION_ADVISED` and `NO_ACTION`, and the database CHECK enforces it. The schema wins;
the equivalent action is `PREPOSITION_REQUESTED`.

Its example condition reads `landslide_zone <= 2` for a high-hazard rule, which is
backwards: NBRO zone 4 is the very-high-hazard zone. See `exposure.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

import structlog

from agent_svc.agents.forecast.exposure import DivisionExposure
from agent_svc.agents.forecast.scoring import CLASS_MAJOR, CLASS_SEVERE, ImpactScore

_log = structlog.get_logger(__name__)

# Every action a trigger may take. Mirrors the database CHECK, and a test asserts they
# match - a rule proposing an action the column rejects fails at the INSERT, after the
# notification has already gone out.
NOTIFY_ONLY: Final[frozenset[str]] = frozenset(
    {"ALERT_DRAFTED", "PREPOSITION_REQUESTED", "SHELTER_OPENED", "EVACUATION_ADVISED", "NO_ACTION"}
)


@dataclass(frozen=True, slots=True)
class TriggerRule:
    """One pre-agreed condition.

    Stored as data rather than expressed as code so it can be published, argued about in
    advance, and reviewed afterwards. The fields are deliberately a flat conjunction: a
    rule language with `or` and nesting is a rule language nobody outside the team can
    read, and the audience for these is a district secretary.
    """

    id: str
    action: str
    scope: str
    description: str

    min_impact_class: int = CLASS_MAJOR
    # Inclusive. `max_landslide_zone` is deliberately absent: a rule that stops applying on
    # *more* hazardous ground is not a rule anybody meant to write.
    min_landslide_zone: int | None = None
    min_lead_time_hours: int | None = None
    min_confidence: float | None = None
    requires_road_access_loss: bool = False

    def __post_init__(self) -> None:
        if self.action not in NOTIFY_ONLY:
            raise ValueError(
                f"{self.id}: {self.action!r} is not an action the schema allows. "
                f"Known: {sorted(NOTIFY_ONLY)}"
            )

    def applies_to(self, division: DivisionExposure) -> bool:
        """Whether this rule covers this division at all.

        Scope is `national`, `district:LK-21` or `ds:LK-21-01`. Checked before the
        condition so a Kandy rule never fires on a Jaffna division regardless of rainfall.
        """
        if self.scope == "national":
            return True
        kind, _, code = self.scope.partition(":")
        if kind == "district":
            return division.district_code == code
        if kind == "ds":
            return division.ds_division_code == code
        return False

    def matches(self, score: ImpactScore, division: DivisionExposure) -> bool:
        """Whether the condition is met."""
        if score.impact_class < self.min_impact_class:
            return False
        if self.min_landslide_zone is not None and (
            division.landslide_zone is None or division.landslide_zone < self.min_landslide_zone
        ):
            return False
        if (
            self.min_lead_time_hours is not None
            and score.lead_time_hours < self.min_lead_time_hours
        ):
            return False
        if self.min_confidence is not None and score.confidence < self.min_confidence:
            return False
        return not (self.requires_road_access_loss and not score.expected_road_access_loss)

    def as_condition(self) -> dict[str, Any]:
        """The condition as it is stored, for publication and after-action review.

        `hazard.anticipatory_trigger.condition` is a JSONB object with a non-empty CHECK.
        Written from the rule rather than hand-maintained alongside it, because two copies
        of a condition is one copy that is wrong during the review that matters.
        """
        condition: dict[str, Any] = {
            "rule_id": self.id,
            "scope": self.scope,
            "min_impact_class": self.min_impact_class,
        }
        if self.min_landslide_zone is not None:
            condition["min_landslide_zone"] = self.min_landslide_zone
        if self.min_lead_time_hours is not None:
            condition["min_lead_time_hours"] = self.min_lead_time_hours
        if self.min_confidence is not None:
            condition["min_confidence"] = self.min_confidence
        if self.requires_road_access_loss:
            condition["requires_road_access_loss"] = True
        return condition


@dataclass(frozen=True, slots=True)
class Firing:
    """A rule that matched, and the division and forecast it matched on."""

    rule: TriggerRule
    score: ImpactScore
    division: DivisionExposure
    notes: str = ""

    @property
    def action(self) -> str:
        return self.rule.action


# The rules in force. In Phase 1 they live here, versioned with the code, because there is
# no ministry to agree them with yet and a configuration file nobody has approved is not
# more legitimate than a constant somebody can read. File 26's admin surface moves them into
# the database with an approval trail; the shape is already the one that stores.
RULES: Final[tuple[TriggerRule, ...]] = (
    TriggerRule(
        id="kandy_landslide_preposition",
        action="PREPOSITION_REQUESTED",
        scope="district:LK-21",
        description=(
            "Kandy district, high-hazard slopes, major impact with a day or more of "
            "warning: ask the DS to preposition before the roads go."
        ),
        min_impact_class=CLASS_MAJOR,
        min_landslide_zone=3,
        min_lead_time_hours=24,
    ),
    TriggerRule(
        id="isolation_risk_preposition",
        action="PREPOSITION_REQUESTED",
        scope="national",
        description=(
            "Any division expected to lose road access at major impact or worse. Supplies "
            "have to arrive before the access does not."
        ),
        min_impact_class=CLASS_MAJOR,
        requires_road_access_loss=True,
        min_lead_time_hours=24,
    ),
    TriggerRule(
        id="severe_impact_shelter_readiness",
        action="SHELTER_OPENED",
        scope="national",
        description=(
            "Severe impact anywhere: open the designated safety locations for that "
            "division. Opening a shelter nobody needs costs a day of a caretaker's time."
        ),
        min_impact_class=CLASS_SEVERE,
        # Lower than the others on purpose. At severe, waiting for the forecast to firm up
        # is waiting for the event.
        min_confidence=0.4,
    ),
)


def evaluate(
    scores: list[ImpactScore],
    divisions: dict[str, DivisionExposure],
    *,
    rules: tuple[TriggerRule, ...] = RULES,
) -> list[Firing]:
    """Every rule that matched, across every division scored in this run.

    Returns firings rather than performing them. What a firing *does* - the event, the
    notification, the database row - belongs to the graph node that has a session and a
    bus, and keeping this function pure is what lets the whole rule set be tested against a
    replayed scenario without either.
    """
    firings: list[Firing] = []
    for score in scores:
        division = divisions.get(score.gn_division_id)
        if division is None:
            # A score for a division we have no exposure record for. Not fatal - the
            # forecast still stands - but a trigger cannot be evaluated without knowing
            # where the division is or what zone it is in.
            _log.error(
                "forecast_trigger_division_missing",
                gn_division_code=score.gn_division_code,
                impact="no anticipatory rule was evaluated for this division",
            )
            continue

        for rule in rules:
            if rule.applies_to(division) and rule.matches(score, division):
                firings.append(
                    Firing(
                        rule=rule,
                        score=score,
                        division=division,
                        notes=(
                            f"impact class {score.impact_class}, "
                            f"{score.lead_time_hours}h lead, "
                            f"confidence {score.confidence:.2f}"
                        ),
                    )
                )
    return firings


def summarise(firings: list[Firing]) -> dict[str, Any]:
    """What fired, for the audit entry and the run's notes."""
    by_rule: dict[str, list[str]] = {}
    for firing in firings:
        by_rule.setdefault(firing.rule.id, []).append(firing.score.gn_division_code)
    return {
        "fired": len(firings),
        "rules": {rule_id: sorted(codes) for rule_id, codes in sorted(by_rule.items())},
    }


@dataclass
class TriggerLedger:
    """Which rules have already fired this run, so a trigger notifies once.

    A rule that fires on every generation puts the same request in front of the same DS
    officer every fifteen minutes for three days, and the fourth one is ignored along with
    everything after it. Keyed on rule and division, because the same rule firing for a
    second division is genuinely new information.

    In-process and per-run: the durable version is the `anticipatory_trigger` row itself,
    which is what stops a restart re-notifying. This is the cheap guard in front of it.
    """

    seen: set[tuple[str, str]] = field(default_factory=set)

    def claim(self, firing: Firing) -> bool:
        """True the first time this rule fires for this division, False afterwards."""
        key = (firing.rule.id, firing.score.gn_division_code)
        if key in self.seen:
            return False
        self.seen.add(key)
        return True

    def new_firings(self, firings: list[Firing]) -> list[Firing]:
        return [firing for firing in firings if self.claim(firing)]
