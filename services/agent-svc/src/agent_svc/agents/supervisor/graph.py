r"""The supervisor: the agent that coordinates the other five and owns every gate.

```
START -> receive_event -> check_sequencing -> detect_conflict
      -> [conflict]  -> escalate_conflict -> human_review -> record -> END
      -> [gate]      -> present_gate -> verify -> commit -> record -> END
      -> [ordinary]  -> dispatch_agents -> record -> END
```

**This is where the platform's safety story is either real or theatre.**

## Routing is a table, not a model

An LLM that picks agents is non-deterministic, untestable, and adds nothing: the routing is
genuinely simple and it has to be auditable. Somebody investigating why a household was never
visited needs to read the rule that should have sent somebody.

The model appears in exactly one node - `escalate_conflict` calls `conflicts.adjudicate` -
and there it proposes a resolution for a human rather than applying one.

## The resume payload is client input

`verify` re-reads the approval from the **database** and checks it names this subject, this
approver, and a second factor verified inside the window. A graph that read
`decision["approved"]` and committed would have authenticated a JSON field.

That is the single most important line in this agent, and `gates.verify_approval_record` is
where it lives.

## A sequencing violation refuses; it never proceeds once

An incident reaching triage before intake verified it is a crew dispatched on an unverified
report. The supervisor raises, audits, and routes to human review - because the "just this
once" is always during the event when everybody is busy and nobody is reading logs.

## The interrupt rule

`present_gate` and `human_review` **re-execute from the top on resume**. Nothing above their
`interrupt()` has a side effect, and `commit` is a separate node downstream so it runs once
however many times the gate node re-ran. A payment instructed twice is not recoverable by
apologising.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final

import structlog
from langgraph.graph import END, START, StateGraph

from agent_svc.agents.supervisor import conflicts as conflict_rules
from agent_svc.agents.supervisor import gates, routes
from agent_svc.agents.supervisor.gates import ApprovalStore, GateKind
from agent_svc.runtime.nodes import audit_write, request_approval
from agent_svc.runtime.registry import AgentSpec
from agent_svc.runtime.state import AgentState
from agent_svc.runtime.tools import REGISTRY as TOOLS
from sarana_shared.domain.time import utc_now

_log = structlog.get_logger(__name__)

AGENT: Final = "supervisor"
SUBJECT_TYPE: Final = "event"

# Threads that may never be rewound. Build file 18: you cannot rewind released money; you
# issue a compensating entry. The check is on the *fact*, not on the thread's agent, because
# a rewind is dangerous exactly when somebody is not thinking about which agent ran.
UNREWINDABLE_FACTS: Final[frozenset[str]] = frozenset(
    {"disbursement_released", "dispatch_released"}
)


class SupervisorState(AgentState, total=False):
    """What one supervised event carries.

    No payload copied wholesale: only the fields a route named. A checkpoint is read during
    debugging and exported to a tracing backend that leaves the country (ADR-011), and an
    event payload copied in full is how a phone number gets there.
    """

    event_type: str
    subject_id: str
    payload: dict[str, Any]
    known_facts: list[str]

    routed: list[dict[str, Any]]
    violations: list[dict[str, Any]]
    conflict: dict[str, Any]
    escalation: dict[str, Any]

    gate: str | None
    approval: dict[str, Any]
    committed: bool
    started: Annotated[list[str], list.__add__]


# ---------------------------------------------------------------------------------------
# The gated commit tool. The runtime layer of the three.
# ---------------------------------------------------------------------------------------


async def _commit_gated_subject(*, gate: str, subject_id: str, approval: dict[str, Any]) -> str:
    """Record that a verified human decision has been committed.

    Gated: `runtime.tools.assert_human_gate` refuses without a decision naming this subject,
    so this is never entered on the supervisor's own authority. It writes no status of its
    own - the release itself is performed by incident-svc or ledger-svc behind scopes no
    machine principal holds.
    """
    _log.info(
        "supervisor_gate_committed",
        gate=gate,
        subject_id=subject_id,
        approver_id=str(approval.get("approver_id", "")),
        note="recorded by the supervisor; the release was performed by the owning service",
    )
    return subject_id


TOOLS.tool(side_effect=True, requires_human_gate=True, name="commit_gated_subject")(
    _commit_gated_subject
)


def build_nodes(
    *,
    approvals: ApprovalStore,
    start_agent: Any = None,
    call: conflict_rules.ModelCall | None = None,
    now: datetime | None = None,
    table: dict[str, tuple[routes.Trigger, ...]] | None = None,
    audit: Any = None,
) -> dict[str, Any]:
    """Build the nodes.

    `start_agent` is how the supervisor actually starts another agent - injected so a test
    can watch what it would have started without compiling six graphs.
    """

    def clock() -> datetime:
        return now if now is not None else utc_now()

    async def receive_event(state: SupervisorState) -> dict[str, Any]:
        """Take the event, and read what is already true about its subject."""
        raw = dict(state.get("output", {}))
        event_type = str(raw.get("event_type", ""))
        subject_id = str(raw.get("subject_id") or state.get("subject_id", ""))
        payload = dict(raw.get("payload", {}))

        facts = sorted(await approvals.facts_for(subject_id)) if subject_id else []
        _log.info(
            "supervisor_event_received",
            event_type=event_type,
            subject_id=subject_id,
            known_facts=facts,
        )
        return {
            "event_type": event_type,
            "subject_id": subject_id,
            "payload": payload,
            "known_facts": facts,
            "gate": raw.get("gate"),
            "notes": [f"received {event_type}"],
        }

    async def check_sequencing(state: SupervisorState) -> dict[str, Any]:
        """Decide what this event starts, and refuse anything out of order."""
        routing = routes.route(
            str(state.get("event_type", "")),
            dict(state.get("payload", {})),
            known_facts=set(state.get("known_facts", [])),
            table=table,
        )

        violations = [
            {
                "agent": trigger.agent,
                "missing": list(missing),
                "reason": str(
                    routes.SequencingViolation(
                        trigger.agent, str(state.get("subject_id", "")), missing
                    )
                ),
            }
            for trigger, missing in routing.refused
        ]
        return {
            "routed": [
                {
                    "agent": trigger.agent,
                    "resume": trigger.resume,
                    "batch": trigger.batch,
                    "input": trigger.input_for(dict(state.get("payload", {}))),
                }
                for trigger in routing.fired
            ],
            "violations": violations,
            "notes": [
                f"{len(routing.fired)} agent(s) to start, {len(violations)} refused, "
                f"{len(routing.skipped)} not applicable"
            ],
        }

    async def detect_conflict(state: SupervisorState) -> dict[str, Any]:
        """Notice a disagreement the event carries. Never resolve one."""
        raw = dict(state.get("output", {})).get("conflict")
        if not raw:
            return {}
        return {"conflict": dict(raw), "notes": ["a conflict was reported with this event"]}

    async def escalate_conflict(state: SupervisorState) -> dict[str, Any]:
        """Pause the subject, assemble both positions, attach a proposal if one can be had."""
        raw = dict(state.get("conflict", {}))
        conflict = conflict_rules.Conflict(
            kind=str(raw.get("kind", "unknown")),
            subject_type=str(raw.get("subject_type", "")),
            subject_id=str(raw.get("subject_id", state.get("subject_id", ""))),
            position_a=_position(raw.get("position_a", {})),
            position_b=_position(raw.get("position_b", {})),
            detected_at=clock(),
        )
        escalation = await conflict_rules.escalate(conflict, call=call)
        return {
            "escalation": escalation.as_interrupt_payload(),
            "notes": [f"conflict {conflict.kind} escalated; the subject is paused"],
        }

    async def human_review(state: SupervisorState) -> dict[str, Any]:
        """Put a conflict or a violation in front of a person.

        **Re-executes from the top on resume.** Nothing above the interrupt has a side
        effect; `record` is downstream.
        """
        detail = dict(state.get("escalation", {})) or {
            "kind": "sequencing_violation",
            "violations": state.get("violations", []),
            "event_type": state.get("event_type"),
            "note": (
                "an agent was not started because a step it depends on has not happened. "
                "Nothing proceeded."
            ),
        }

        decision = request_approval(
            state,
            question="This subject is paused and needs a decision.",
            detail=detail,
        )
        return {
            "human_decision": decision,
            "notes": [f"{decision.get('decided_by', 'a person')} decided"],
        }

    async def present_gate(state: SupervisorState) -> dict[str, Any]:
        """Present one of the two gates.

        **Re-executes from the top on resume.** `assert_sequenced` runs above the interrupt
        and is a read; the commit is two nodes downstream.
        """
        gate = GateKind(str(state.get("gate")))
        subject_id = str(state.get("subject_id", ""))

        await gates.assert_sequenced(gate, subject_id, store=approvals)

        decision = request_approval(
            state,
            question=f"{gate.value}: this needs a named person with a fresh second factor.",
            detail=gates.payload_for(
                gate,
                subject_id,
                dict(state.get("payload", {})),
                waiting_since=clock(),
            ),
        )
        return {"human_decision": decision, "notes": [f"{gate.value} answered"]}

    async def verify(state: SupervisorState) -> dict[str, Any]:
        """Re-read the approval from the database. The line that makes the gate real.

        The resume payload is client input and is used only to find the record. Every fact
        acted on comes from what the database says.
        """
        gate = GateKind(str(state.get("gate")))
        subject_id = str(state.get("subject_id", ""))
        decision = dict(state.get("human_decision") or {})

        record = await gates.verify_approval_record(
            gate, subject_id, decision, store=approvals, now=clock()
        )
        return {
            "approval": {
                "gate": record.gate,
                "subject_id": record.subject_id,
                "approver_id": record.approver_id,
                "decided_at": record.decided_at.isoformat(),
                "verified_against": "database record",
            },
            "notes": ["approval verified against the database, not the resume payload"],
        }

    async def commit(state: SupervisorState) -> dict[str, Any]:
        """Record the committed decision. Downstream of the interrupt, so it runs once."""
        gate = str(state.get("gate"))
        subject_id = str(state.get("subject_id", ""))

        await TOOLS.invoke(
            "commit_gated_subject",
            state,
            gate=gate,
            subject_id=subject_id,
            approval=dict(state.get("approval", {})),
        )
        return {"committed": True, "notes": [f"{gate} committed for {subject_id}"]}

    async def dispatch_agents(state: SupervisorState) -> dict[str, Any]:
        """Start what the table said to start."""
        started: list[str] = []
        for entry in state.get("routed", []):
            if start_agent is None:
                started.append(entry["agent"])
                continue
            await start_agent(
                agent=entry["agent"],
                subject_id=str(state.get("subject_id", "")),
                payload=entry.get("input", {}),
                resume=bool(entry.get("resume")),
                correlation_id=str(state.get("correlation_id", "")),
            )
            started.append(entry["agent"])

        if started:
            _log.info(
                "supervisor_agents_started",
                agents=started,
                event_type=state.get("event_type"),
                correlation_id=state.get("correlation_id"),
            )
        return {"started": started, "notes": [f"started {', '.join(started) or 'nothing'}"]}

    async def record(state: SupervisorState) -> dict[str, Any]:
        """Write the audit entry. Every routing decision, gate and conflict lands here.

        Build file 18 requires an unbroken audit chain from the first report to the released
        disbursement, and this is the link for every supervised step in it.
        """
        violations = state.get("violations", [])
        audited = await audit_write(
            state,
            action=f"supervisor.{_outcome(state)}",
            subject=str(state.get("subject_id", "")),
            detail={
                "event_type": state.get("event_type"),
                "agents_started": state.get("started", []),
                "sequencing_violations": violations,
                "gate": state.get("gate"),
                "committed": bool(state.get("committed")),
                "conflict": state.get("conflict", {}).get("kind"),
                "approver_id": state.get("approval", {}).get("approver_id"),
                "decided_by": (state.get("human_decision") or {}).get("decided_by"),
            },
            writer=audit,
        )

        return {
            **audited,
            "status": "COMPLETED",
            "output": {
                "event_type": state.get("event_type"),
                "subject_id": state.get("subject_id"),
                "outcome": _outcome(state),
                "agents_started": state.get("started", []),
                "sequencing_violations": violations,
                "gate": state.get("gate"),
                "committed": bool(state.get("committed")),
                "conflict_escalated": bool(state.get("escalation")),
                "confidence": 1.0,
                "reasoning": _reasoning(state),
                "needs_human_review": False,
                # Routing is a table and the gates are database reads. Where a person
                # decided, that is recorded per subject rather than claimed here.
                "provenance": "HUMAN" if state.get("committed") else "DETERMINISTIC",
            },
        }

    return {
        "receive_event": receive_event,
        "check_sequencing": check_sequencing,
        "detect_conflict": detect_conflict,
        "escalate_conflict": escalate_conflict,
        "human_review": human_review,
        "present_gate": present_gate,
        "verify": verify,
        "commit": commit,
        "dispatch_agents": dispatch_agents,
        "record": record,
    }


# ---------------------------------------------------------------------------------------
# Helpers and routing
# ---------------------------------------------------------------------------------------


def _position(raw: dict[str, Any]) -> conflict_rules.Position:
    return conflict_rules.Position(
        source=str(raw.get("source", "unknown")),
        claim=str(raw.get("claim", "")),
        confidence=float(raw.get("confidence", 0.0)),
        evidence=dict(raw.get("evidence", {})),
    )


def _outcome(state: SupervisorState) -> str:
    if state.get("committed"):
        return "gate.committed"
    if state.get("escalation"):
        return "conflict.escalated"
    if state.get("violations"):
        return "sequencing.refused"
    if state.get("gate"):
        return "gate.presented"
    return "event.routed"


def _reasoning(state: SupervisorState) -> str:
    outcome = _outcome(state)
    if outcome == "gate.committed":
        return f"{state.get('gate')} was verified against the database record and committed"
    if outcome == "conflict.escalated":
        return "a conflict was escalated to a person; the subject is paused and nothing applied"
    if outcome == "sequencing.refused":
        missing = [item["agent"] for item in state.get("violations", [])]
        return f"refused to start {', '.join(missing)}: a step they depend on has not happened"
    started = state.get("started", [])
    return f"routed to {', '.join(started)}" if started else "no agent was routed by this event"


def _after_sequencing(state: SupervisorState) -> str:
    if state.get("violations"):
        return "human_review"
    return "detect_conflict"


def _after_conflict(state: SupervisorState) -> str:
    if state.get("conflict"):
        return "escalate_conflict"
    if state.get("gate"):
        return "present_gate"
    return "dispatch_agents"


def _after_gate(state: SupervisorState) -> str:
    """A refusal never reaches `verify`.

    `verify` re-reads the record and would refuse a rejection anyway, but routing a "no"
    into a function whose job is to confirm a "yes" is how an error message ends up saying
    the wrong thing.
    """
    decision = state.get("human_decision") or {}
    return "verify" if decision.get("approved") else "record"


def build(
    checkpointer: Any,
    *,
    approvals: ApprovalStore | None = None,
    start_agent: Any = None,
    call: conflict_rules.ModelCall | None = None,
    now: datetime | None = None,
    table: dict[str, tuple[routes.Trigger, ...]] | None = None,
    audit: Any = None,
) -> Any:
    """Compile the graph.

    Without an approval store the supervisor refuses at the first node that needs one. A
    supervisor that could not verify an approval and proceeded anyway would be the theatre
    version of this agent.
    """
    nodes = build_nodes(
        approvals=approvals or _RefusingApprovals(),
        start_agent=start_agent,
        call=call,
        now=now,
        table=table,
        audit=audit,
    )

    builder = StateGraph(SupervisorState)
    for name, node in nodes.items():
        builder.add_node(name, node)

    builder.add_edge(START, "receive_event")
    builder.add_edge("receive_event", "check_sequencing")
    builder.add_conditional_edges(
        "check_sequencing",
        _after_sequencing,
        {"human_review": "human_review", "detect_conflict": "detect_conflict"},
    )
    builder.add_conditional_edges(
        "detect_conflict",
        _after_conflict,
        {
            "escalate_conflict": "escalate_conflict",
            "present_gate": "present_gate",
            "dispatch_agents": "dispatch_agents",
        },
    )
    builder.add_edge("escalate_conflict", "human_review")
    builder.add_edge("human_review", "record")
    builder.add_conditional_edges(
        "present_gate", _after_gate, {"verify": "verify", "record": "record"}
    )
    builder.add_edge("verify", "commit")
    builder.add_edge("commit", "record")
    builder.add_edge("dispatch_agents", "record")
    builder.add_edge("record", END)

    return builder.compile(checkpointer=checkpointer)


class _RefusingApprovals:
    """Stands in when there is no approval store.

    Refuses rather than returning None, which `verify_approval_record` would correctly treat
    as "nobody approved this" - a refusal for the wrong reason, with a message pointing at
    the approver rather than at the missing configuration.
    """

    async def approval_for(self, gate: str, subject_id: str) -> Any:
        raise RuntimeError(
            "The supervisor has no approval store configured, so it cannot verify that an "
            "approval exists. It refuses rather than trusting the resume payload, which is "
            "client input."
        )

    async def facts_for(self, subject_id: str) -> Any:
        raise RuntimeError(
            "The supervisor has no approval store configured, so it cannot tell what has "
            "already happened to this subject and cannot enforce sequencing."
        )


def can_rewind(facts: set[str]) -> tuple[bool, str]:
    """Whether a thread may be rewound, and why not if it may not.

    Build file 18: you cannot rewind released money; you issue a compensating entry. The
    check is on the facts rather than the thread's agent, because a rewind is dangerous
    exactly when somebody is not thinking about which agent ran.
    """
    blocking = sorted(facts & UNREWINDABLE_FACTS)
    if blocking:
        return False, (
            f"this thread has already committed: {', '.join(blocking)}. A rewind would "
            "reopen a decision that has already moved money or people. Issue a compensating "
            "entry instead - the ledger is append-only and a reversal is a first-class "
            "record."
        )
    return True, ""


def _eval_build(checkpointer: Any) -> Any:
    from agent_svc.agents.supervisor.evaluation import build as build_eval

    return build_eval(checkpointer)


SPEC: Final = AgentSpec(
    name=AGENT,
    subject_type=SUBJECT_TYPE,
    build=build,
    description=(
        "Routes events to the other agents through a deterministic table, enforces the two "
        "human gates by re-reading the approval from the database, and escalates every "
        "conflict to a person rather than resolving one."
    ),
    degraded_note=(
        "Routing is a table and the gates are database reads, so neither touches a model at "
        "all - with the provider down the supervisor routes identically and every gate is "
        "enforced identically. The only model call is the conflict adjudicator, which "
        "proposes a resolution for a human; without it a conflict is still paused and still "
        "escalated, with both positions shown and no proposal attached."
    ),
    gated=True,
    eval_build=_eval_build,
)
