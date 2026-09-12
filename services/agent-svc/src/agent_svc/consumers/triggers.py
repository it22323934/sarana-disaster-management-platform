"""Which events start which agents.

One table, declarative, in one file. The alternative — each agent subscribing to the bus
from inside its own package — means the answer to "what happens when a report arrives?" is
spread across six directories, and nobody discovers the second consumer of an event until
it fires twice.

Three things every row states, and none of them have defaults worth guessing:

**`subject_from`** — where in the event the subject id is. The thread id is derived from it,
so getting it wrong does not fail loudly: it starts a run on the wrong subject, or forks a
second thread for one that already has an approval pending. Rows say `"subject"` to use the
envelope's own subject, or a dotted path into the payload.

**`carry`** — which payload fields the run starts with. Named rather than passing the whole
payload, because a graph's state is checkpointed and read during debugging: an event payload
copied wholesale into state is how a phone number ends up in a trace that leaves the country
(ADR-011). A field not listed here does not reach the agent.

**`enabled`** — whether this row actually subscribes. The noop row is off, and that is not
an oversight: see its comment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from sarana_shared.events import catalogue
from sarana_shared.events.envelope import EventEnvelope

# The envelope's own subject, rather than a field inside the payload.
ENVELOPE_SUBJECT: Final = "subject"


@dataclass(frozen=True, slots=True)
class AgentTrigger:
    """One event type starting one agent."""

    event_type: str
    agent: str
    subject_from: str
    carry: tuple[str, ...]
    enabled: bool = True
    subject_type: str | None = None

    def subject_id(self, envelope: EventEnvelope) -> str | None:
        """Pull the subject id out of an event, or None if it is not there.

        None rather than raising: an event missing the field is a contract problem between
        two services, and the consumer's job is to say so once and acknowledge it. Raising
        would make the bus redeliver a message that will never succeed, which is a poison
        pill that stops every well-formed event queued behind it.
        """
        if self.subject_from == ENVELOPE_SUBJECT:
            return str(envelope.subject) if envelope.subject else None

        value: Any = envelope.payload
        for part in self.subject_from.split("."):
            if not isinstance(value, dict) or part not in value:
                return None
            value = value[part]
        return str(value) if value not in (None, "") else None

    def input_for(self, envelope: EventEnvelope) -> dict[str, Any]:
        """The starting input: only the named fields, only if present."""
        return {name: envelope.payload[name] for name in self.carry if name in envelope.payload}


TRIGGERS: Final[tuple[AgentTrigger, ...]] = (
    AgentTrigger(
        event_type=catalogue.INCIDENT_REPORT_RECEIVED,
        agent="noop",
        subject_from=ENVELOPE_SUBJECT,
        carry=("text", "hazard_type"),
        # Off deliberately. `noop` is the reference agent: it classifies with three keywords
        # and asks a person about everything else. Pointed at real citizen reports it would
        # fill the approval inbox with questions no officer can usefully answer, and an
        # inbox people learn to ignore is worse than no inbox. File 15 replaces this row
        # with the intake agent. Flipping it to True is how you watch the wiring work.
        enabled=False,
    ),
)


def enabled_triggers(triggers: tuple[AgentTrigger, ...] = TRIGGERS) -> tuple[AgentTrigger, ...]:
    return tuple(trigger for trigger in triggers if trigger.enabled)


def subscribed_event_types(triggers: tuple[AgentTrigger, ...] = TRIGGERS) -> tuple[str, ...]:
    """Every event type the enabled rows want, deduplicated and ordered.

    Ordered so the subscription is stable across restarts: a consumer group whose declared
    types shuffle between deployments is one whose Redis Streams reads move around.
    """
    return tuple(sorted({trigger.event_type for trigger in enabled_triggers(triggers)}))
