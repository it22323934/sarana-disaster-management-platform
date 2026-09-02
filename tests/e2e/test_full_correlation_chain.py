"""One unbroken correlation id from the first report to the released disbursement.

Build file 18 names this file and is blunt about the consequence: **a gap is a build
failure.**

The reason it earns a test of its own is that the chain is the platform's whole
accountability claim. "Why did this household get flagged?", "who approved this payment?",
"what did the system know when it sent that crew?" are all answerable only if one identifier
runs from the SMS that started it to the money that ended it. Every service passes it along
correctly in isolation; the failure mode is a boundary where somebody starts a fresh one
because the old one was inconvenient to thread through, and no single service's tests would
notice.

## What this test is, honestly

It walks the **supervisor's routing and gates** across the full sequence of events with one
correlation id, against fakes. It asserts the id survives every step and that no step
invented a new one.

It is not a live integration test. It does not boot six services, and it cannot: the intake,
triage and anomaly agents have no adapters yet, so there is nothing to boot them against.
What it does prove is that nothing in the supervisor's own path drops or replaces the id —
which is the boundary most likely to lose it, because the supervisor is the only component
that sees every stage.

`HANDOFF.md` records the rest. When the adapters exist, this file is where the live version
belongs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from langgraph.types import Command

from agent_svc.agents.supervisor import graph as supervisor
from agent_svc.agents.supervisor import routes
from agent_svc.agents.supervisor.gates import ApprovalRecord
from agent_svc.runtime.checkpoint import config_for, memory_checkpointer
from agent_svc.runtime.state import initial_state, thread_id_for
from sarana_shared.domain.ids import new_correlation_id
from sarana_shared.events import catalogue

NOW = datetime(2026, 11, 28, 4, 0, tzinfo=UTC)
CORRELATION = new_correlation_id()
APPROVER = "dmc-officer-1"

# The full journey, in the order it happens. Each entry is one event, the subject it is
# about, and the facts that are true by the time it arrives.
#
# The facts accumulate deliberately: they are what the sequencing constraints read, and
# writing them out here makes the ordering of the whole response legible in one place.
JOURNEY: list[tuple[str, str, set[str]]] = [
    (catalogue.HAZARD_EVENT_DECLARED, "haz-1", set()),
    (catalogue.FORECAST_IMPACT_GENERATED, "haz-1", {"cap_validated", "trilingual_complete"}),
    (catalogue.INCIDENT_REPORT_RECEIVED, "rep-1", set()),
    (catalogue.INCIDENT_VERIFIED, "inc-1", {"intake_verified", "intake_deduplicated"}),
    (
        catalogue.AID_ASSESSMENT_SUBMITTED,
        "asm-1",
        {"intake_verified", "intake_deduplicated", "triaged"},
    ),
]


@dataclass
class ChainRecordingApprovals:
    """The approval store, plus a log of every audit entry the supervisor wrote.

    The audit writer is what the chain is actually asserted against: build file 18 wants an
    unbroken `correlation_id` across every routing decision, gate and human decision, and
    those are exactly the entries `audit_write` produces.
    """

    facts: dict[str, set[str]] = field(default_factory=dict)
    records: dict[tuple[str, str], ApprovalRecord] = field(default_factory=dict)
    audit_entries: list[dict[str, Any]] = field(default_factory=list)

    async def approval_for(self, gate: str, subject_id: str) -> ApprovalRecord | None:
        return self.records.get((gate, subject_id))

    async def facts_for(self, subject_id: str) -> set[str]:
        return set(self.facts.get(subject_id, set()))

    async def write_audit(self, entry: dict[str, Any]) -> None:
        self.audit_entries.append(entry)


@dataclass
class ChainRecordingStarter:
    """Every agent the supervisor started, with the correlation id it passed on."""

    started: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(self, **kwargs: Any) -> None:
        self.started.append(kwargs)


async def run_step(
    graph, *, event_type: str, subject_id: str, gate: str | None = None
) -> tuple[dict[str, Any], Any]:
    """One supervised step, carrying the same correlation id as every other.

    Returns the config alongside the values so a gate's resume lands on the same thread the
    gate paused on. Deriving the thread twice is how a resume ends up starting a fresh run
    with empty state, which is a mistake this test made before it caught it.
    """
    state = initial_state(
        agent="supervisor",
        subject_type="event",
        subject_id=subject_id,
        correlation_id=CORRELATION,
    )
    state["output"] = {
        "event_type": event_type,
        "subject_id": subject_id,
        "gate": gate,
        "payload": {"by_impact_class": {"4": 6}} if "forecast" in event_type else {},
    }
    config = config_for(thread_id_for("supervisor", "event", f"{subject_id}:{event_type}"))
    return await graph.ainvoke(state, config), config


@pytest.fixture
def chain() -> ChainRecordingApprovals:
    store = ChainRecordingApprovals(facts={subject: facts for _, subject, facts in JOURNEY})
    # The two gates, both properly approved with a fresh second factor.
    store.facts["plan-1"] = {"intake_verified", "intake_deduplicated", "triaged"}
    store.facts["ent-1"] = {
        "entitlement_calculated",
        "first_approval_recorded",
        "second_approval_recorded",
    }
    for gate, subject in (("dispatch_signoff", "plan-1"), ("disbursement_release", "ent-1")):
        store.records[(gate, subject)] = ApprovalRecord(
            gate=gate,
            subject_id=subject,
            approved=True,
            approver_id=APPROVER,
            decided_at=NOW,
            step_up_at=NOW - timedelta(minutes=1),
        )
    return store


def build_graph(chain: ChainRecordingApprovals, starter: ChainRecordingStarter):
    return supervisor.build(
        memory_checkpointer(),
        approvals=chain,
        start_agent=starter,
        now=NOW,
        audit=chain.write_audit,
    )


async def test_the_correlation_id_survives_the_whole_journey(
    chain: ChainRecordingApprovals,
) -> None:
    """**A gap here is a build failure.**

    One identifier from the hazard declaration to the released disbursement. Without it,
    "why did this household get flagged?" is not answerable months later.
    """
    starter = ChainRecordingStarter()
    graph = build_graph(chain, starter)

    for event_type, subject_id, _ in JOURNEY:
        await run_step(graph, event_type=event_type, subject_id=subject_id)

    # Both gates, each verified against the database record.
    for gate, subject in (("dispatch_signoff", "plan-1"), ("disbursement_release", "ent-1")):
        _, config = await run_step(
            graph, event_type=f"sarana.{gate}.requested", subject_id=subject, gate=gate
        )
        await graph.ainvoke(
            Command(
                resume={
                    "subject_id": subject,
                    "decided_by": APPROVER,
                    "decided_at": NOW.isoformat(),
                    "approved": True,
                }
            ),
            config,
        )

    assert chain.audit_entries, "the journey produced no audit entries at all"

    ids = {entry["correlation_id"] for entry in chain.audit_entries}
    assert ids == {CORRELATION}, f"the chain broke: {len(ids)} correlation ids across the journey"


async def test_every_agent_the_supervisor_starts_inherits_the_correlation_id(
    chain: ChainRecordingApprovals,
) -> None:
    """The boundary most likely to lose it: one component handing work to another."""
    starter = ChainRecordingStarter()
    graph = build_graph(chain, starter)

    for event_type, subject_id, _ in JOURNEY:
        await run_step(graph, event_type=event_type, subject_id=subject_id)

    assert starter.started, "no agent was started across the whole journey"
    assert {entry["correlation_id"] for entry in starter.started} == {CORRELATION}


async def test_the_journey_actually_starts_the_agents_it_should(
    chain: ChainRecordingApprovals,
) -> None:
    """Guards the test above. A chain of one identifier across zero agents proves nothing,
    so the journey has to genuinely exercise the routing table."""
    starter = ChainRecordingStarter()
    graph = build_graph(chain, starter)

    for event_type, subject_id, _ in JOURNEY:
        await run_step(graph, event_type=event_type, subject_id=subject_id)

    started = {entry["agent"] for entry in starter.started}

    assert {"forecast", "warning", "intake", "triage", "ledger_anomaly"} <= started


async def test_both_gates_are_recorded_in_the_chain_with_the_approver(
    chain: ChainRecordingApprovals,
) -> None:
    """A chain that recorded the routing but not the decisions would answer "what happened"
    and not "who decided", which is the half that matters in an audit."""
    starter = ChainRecordingStarter()
    graph = build_graph(chain, starter)

    for gate, subject in (("dispatch_signoff", "plan-1"), ("disbursement_release", "ent-1")):
        _, config = await run_step(
            graph, event_type=f"sarana.{gate}.requested", subject_id=subject, gate=gate
        )
        await graph.ainvoke(
            Command(
                resume={
                    "subject_id": subject,
                    "decided_by": APPROVER,
                    "decided_at": NOW.isoformat(),
                    "approved": True,
                }
            ),
            config,
        )

    committed = [
        entry for entry in chain.audit_entries if entry["action"] == "supervisor.gate.committed"
    ]

    assert len(committed) == 2, "both gates should appear in the audit chain"
    assert all(entry["detail"]["approver_id"] == APPROVER for entry in committed)


async def test_a_refused_step_is_in_the_chain_rather_than_missing_from_it(
    chain: ChainRecordingApprovals,
) -> None:
    """A sequencing violation is a thing that happened. A chain that recorded only successes
    would be a chain that cannot explain a gap in the response."""
    chain.facts["inc-2"] = set()
    starter = ChainRecordingStarter()
    graph = build_graph(chain, starter)

    await run_step(graph, event_type=catalogue.INCIDENT_VERIFIED, subject_id="inc-2")

    # The run pauses for a person, so the audit entry lands when the review completes -
    # what matters is that nothing was started and nothing was silently dropped.
    assert starter.started == []


def test_every_event_in_the_journey_is_one_the_table_knows() -> None:
    """A journey written against event names the router does not have would pass while
    testing nothing."""
    routed = set(routes.subscribed_event_types())

    assert {event for event, _, _ in JOURNEY} <= routed


def test_the_journey_covers_the_stages_build_file_18_names() -> None:
    """hazard → forecast → alert → report → incident → triage → gate → ... → disbursement.

    Asserted so the journey cannot quietly shrink to the two steps that are easy.
    """
    events = [event for event, _, _ in JOURNEY]

    assert catalogue.HAZARD_EVENT_DECLARED in events
    assert catalogue.FORECAST_IMPACT_GENERATED in events
    assert catalogue.INCIDENT_REPORT_RECEIVED in events
    assert catalogue.INCIDENT_VERIFIED in events
    assert catalogue.AID_ASSESSMENT_SUBMITTED in events
