"""Which event starts which agent, and what must have happened first.

**Routing is a table, not a model.** An LLM that picks agents is non-deterministic,
untestable and adds nothing here: the routing is genuinely simple, and it has to be
auditable. Somebody investigating why a household was never visited needs to be able to read
the rule that should have sent somebody, not re-run a model and hope it decides the same way
twice.

The model appears in exactly one place in this whole agent - `conflicts.adjudicate` - and
even there it proposes a resolution for a human rather than applying one.

## Sequencing constraints are declarative and enforced

The dangerous failure is not a missing route; it is a route that fires **early**. An incident
reaching triage before intake has verified it is a crew dispatched on an unverified report; an
entitlement reaching disbursement before both approvals exist is money released on one
signature.

So each route carries the facts that must already be true about its subject, and a violated
constraint **raises, audits, and routes to human review**. It never proceeds "just this once",
because the once is always during the event when everybody is busy and nobody is reading logs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

import structlog

from sarana_shared.events import catalogue

_log = structlog.get_logger(__name__)

# The facts a subject can have accumulated. A route names the ones it needs, and the
# supervisor refuses to fire until they are all present.
#
# Deliberately coarse. These are the milestones somebody would name out loud when explaining
# what happened to a report, and a precondition nobody can state in a sentence is one nobody
# can check during an incident review.
FACT_VERIFIED: Final = "intake_verified"
FACT_DEDUPLICATED: Final = "intake_deduplicated"
FACT_TRIAGED: Final = "triaged"
FACT_DISPATCH_SIGNED_OFF: Final = "dispatch_signed_off"
FACT_CAP_VALID: Final = "cap_validated"
FACT_TRILINGUAL: Final = "trilingual_complete"
FACT_ENTITLEMENT_CALCULATED: Final = "entitlement_calculated"
FACT_FIRST_APPROVAL: Final = "first_approval_recorded"
FACT_SECOND_APPROVAL: Final = "second_approval_recorded"


class SequencingViolation(Exception):
    """A route fired before its preconditions were met.

    Its own type because the supervisor routes on it: the run stops, an audit entry is
    written, and the subject goes to human review. It is never caught and ignored.
    """

    def __init__(self, agent: str, subject_id: str, missing: tuple[str, ...]) -> None:
        super().__init__(
            f"{agent} cannot run on {subject_id}: {', '.join(missing)} has not happened. "
            "The supervisor refuses rather than proceeding; a step skipped once during an "
            "event is a step nobody notices was skipped."
        )
        self.agent = agent
        self.subject_id = subject_id
        self.missing = missing


@dataclass(frozen=True, slots=True)
class Trigger:
    """One agent, started by one event, once its preconditions hold."""

    agent: str
    subject_from: str = "subject"
    carry: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    when: Callable[[dict[str, Any]], bool] | None = None
    resume: bool = False
    batch: bool = False
    window_minutes: int = 0

    def applies(self, payload: dict[str, Any]) -> bool:
        """Whether this trigger fires for this payload at all.

        A `when` that raises is treated as not applying, and logged. A predicate reading a
        field an event did not carry is a contract problem between two services, and
        letting it stop the whole consumer would turn one malformed event into a poison
        pill for every well-formed one queued behind it.
        """
        if self.when is None:
            return True
        try:
            return bool(self.when(payload))
        except Exception as error:  # noqa: BLE001 - a bad predicate is not a poison pill
            _log.warning(
                "supervisor_route_predicate_failed",
                agent=self.agent,
                error=type(error).__name__,
                impact="this trigger did not fire for this event; the event was acknowledged",
            )
            return False

    def missing_facts(self, known: set[str]) -> tuple[str, ...]:
        """Which preconditions are not yet satisfied."""
        return tuple(fact for fact in self.requires if fact not in known)

    def subject_id(self, envelope_subject: str | None, payload: dict[str, Any]) -> str | None:
        """Where the subject id lives, in the envelope or at a dotted path in the payload."""
        if self.subject_from == "subject":
            return str(envelope_subject) if envelope_subject else None

        value: Any = payload
        for part in self.subject_from.split("."):
            if not isinstance(value, dict) or part not in value:
                return None
            value = value[part]
        return str(value) if value not in (None, "") else None

    def input_for(self, payload: dict[str, Any]) -> dict[str, Any]:
        """The starting input: only the named fields, only if present.

        Named rather than passing the whole payload, because a graph's state is checkpointed
        and read during debugging. An event payload copied wholesale into state is how a
        phone number ends up in a trace that leaves the country (ADR-011).
        """
        return {name: payload[name] for name in self.carry if name in payload}


def _impact_class_at_least(minimum: int) -> Callable[[dict[str, Any]], bool]:
    """A predicate on the forecast's impact class.

    Class 2 is NBRO's watch level and the threshold below which no public alert is issued -
    an alert at class 1 is the one people learn to ignore before the one that mattered.
    """

    def predicate(payload: dict[str, Any]) -> bool:
        classes = payload.get("by_impact_class") or {}
        if isinstance(classes, dict) and classes:
            return any(int(level) >= minimum for level in classes if str(level).isdigit())
        return int(payload.get("impact_class", 0)) >= minimum

    return predicate


# The routing table. One place, declarative, readable by somebody who is not a programmer.
#
# An agent added to `agents/` but not to this table is one that exists in the tree and
# nowhere else - a failure mode with no symptom until somebody asks why it never ran.
ROUTES: Final[dict[str, tuple[Trigger, ...]]] = {
    catalogue.HAZARD_EVENT_DECLARED: (
        Trigger(agent="forecast", carry=("hazard_type", "landfall_at")),
    ),
    catalogue.FORECAST_IMPACT_GENERATED: (
        Trigger(
            agent="warning",
            carry=("hazard_event_id", "hazard_type", "by_impact_class"),
            when=_impact_class_at_least(2),
            requires=(FACT_CAP_VALID, FACT_TRILINGUAL),
        ),
    ),
    catalogue.INCIDENT_REPORT_RECEIVED: (
        Trigger(agent="intake", carry=("channel", "raw_text", "raw_audio_uri")),
    ),
    catalogue.INCIDENT_VERIFIED: (
        Trigger(
            agent="triage",
            carry=("district_code",),
            # The constraint that matters most in this table. A crew sent on an unverified,
            # undeduplicated report is a crew sent to an address that may not exist while a
            # real one waits.
            requires=(FACT_VERIFIED, FACT_DEDUPLICATED),
        ),
    ),
    catalogue.AID_ASSESSMENT_SUBMITTED: (
        Trigger(
            agent="ledger_anomaly",
            carry=("district_code",),
            batch=True,
            # Batched, because a detector over one assessment is a detector over noise -
            # every ratio it computes has a denominator of one.
            window_minutes=15,
        ),
    ),
    catalogue.DISPATCH_SIGNOFF_GRANTED: (
        Trigger(
            agent="triage",
            resume=True,
            requires=(FACT_DISPATCH_SIGNED_OFF,),
        ),
    ),
}

# What each gate protects, and what must be true before it may be committed. Read by
# `gates.assert_sequenced` as well as by the routes, so the two cannot disagree about what
# "ready to release" means.
GATE_PRECONDITIONS: Final[dict[str, tuple[str, ...]]] = {
    "dispatch_signoff": (FACT_VERIFIED, FACT_DEDUPLICATED, FACT_TRIAGED),
    "disbursement_release": (
        FACT_ENTITLEMENT_CALCULATED,
        FACT_FIRST_APPROVAL,
        FACT_SECOND_APPROVAL,
    ),
    "alert_signoff": (FACT_CAP_VALID, FACT_TRILINGUAL),
}


@dataclass(frozen=True, slots=True)
class Routing:
    """What one event should start, and what it could not."""

    fired: list[Trigger] = field(default_factory=list)
    refused: list[tuple[Trigger, tuple[str, ...]]] = field(default_factory=list)
    skipped: list[Trigger] = field(default_factory=list)

    @property
    def has_violation(self) -> bool:
        return bool(self.refused)


def route(
    event_type: str,
    payload: dict[str, Any],
    *,
    known_facts: set[str] | None = None,
    table: dict[str, tuple[Trigger, ...]] | None = None,
) -> Routing:
    """Decide what this event starts.

    Three outcomes per trigger, and they are deliberately distinct:

      **fired** - the predicate held and every precondition was satisfied;
      **skipped** - the predicate did not hold, which is ordinary and not a problem;
      **refused** - the predicate held but a precondition was missing, which is a
        sequencing violation and goes to a human.

    Collapsing `skipped` and `refused` would hide the difference between "this event was not
    for that agent" and "that agent should have run and could not", which is exactly the
    distinction somebody needs during an incident review.
    """
    facts = known_facts or set()
    triggers = (table or ROUTES).get(event_type, ())

    fired: list[Trigger] = []
    refused: list[tuple[Trigger, tuple[str, ...]]] = []
    skipped: list[Trigger] = []

    for trigger in triggers:
        if not trigger.applies(payload):
            skipped.append(trigger)
            continue
        missing = trigger.missing_facts(facts)
        if missing:
            _log.error(
                "supervisor_sequencing_violation",
                event_type=event_type,
                agent=trigger.agent,
                missing=list(missing),
                impact="the agent was not started; the subject goes to human review",
            )
            refused.append((trigger, missing))
            continue
        fired.append(trigger)

    return Routing(fired=fired, refused=refused, skipped=skipped)


def subscribed_event_types(table: dict[str, tuple[Trigger, ...]] | None = None) -> tuple[str, ...]:
    """Every event type the table wants, ordered.

    Ordered so the subscription is stable across restarts: a consumer group whose declared
    types shuffle between deployments is one whose Redis Streams reads move around.
    """
    return tuple(sorted(table or ROUTES))


def agents_routed(table: dict[str, tuple[Trigger, ...]] | None = None) -> tuple[str, ...]:
    """Every agent this table can start. Used by a test to catch one that is unreachable."""
    return tuple(
        sorted({trigger.agent for triggers in (table or ROUTES).values() for trigger in triggers})
    )
