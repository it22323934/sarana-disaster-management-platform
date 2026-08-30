"""The reusable nodes every agent builds from.

Four of them, and each exists because doing it per-agent produced six slightly different
versions of the same thing.

**`audit_write`** — every agent node that changes anything calls it. Non-negotiable #4 in
the master context: an agent action nobody can trace is an agent action nobody can be
accountable for.

**`rg_append`** — agents append observations to the Resilience Graph. They never write
entities. An agent that could create a node in the graph could invent a village.

**`guard`** — a declarative precondition that routes on failure to a named node rather than
raising into the void. A graph that stops with a traceback leaves the run in limbo; one
that routes to `human_review` leaves it in a queue.

**`with_confidence`** — wraps a node so low-confidence output goes to review instead of
onward. This is where the calibration of `AgentOutput.confidence` stops being a number and
starts being a gate.

## The interrupt rule, which is the most common bug in HITL graphs

**A node re-executes from the top when resumed.** Everything before the `interrupt()` call
runs a second time. So:

  put side effects *after* the interrupt, or make them idempotent;
  call `interrupt()` at most once per node invocation;
  pass only JSON-serialisable values to it.

`request_approval` below is written that way and says so at the call site. Every other
`interrupt()` in this codebase carries the same comment, because the failure it prevents —
an audit entry written twice, an SMS sent twice, a payment instructed twice — is silent and
only shows up in the record afterwards.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Final

import structlog

from agent_svc.runtime.errors import GuardFailed
from agent_svc.runtime.state import AgentOutput, AgentState

_log = structlog.get_logger(__name__)

# A node function: takes state, returns the partial update it wants merged.
type Node = Callable[[AgentState], Awaitable[dict[str, Any]]]

# Below this, a node's answer goes to a person rather than onward. The same threshold the
# model router upgrades at, deliberately: a call that was not confident enough to trust is
# not confident enough to act on either.
DEFAULT_REVIEW_THRESHOLD: Final = 0.70


async def audit_write(
    state: AgentState,
    *,
    action: str,
    subject: str,
    detail: dict[str, Any] | None = None,
    writer: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Record that an agent did something.

    Called by every node that changes anything. The entry names the agent, the action, the
    subject and the correlation id that ties it back to the original citizen report — which
    is what makes "why did this household get flagged?" answerable months later.

    `writer` is injected so a test does not need core-api. In the service it is the
    internal audit client; absent, the entry is logged and the run continues. **Not
    raising is deliberate**: an audit backend being down must not stop a cyclone response,
    and the log line is the fallback record.
    """
    entry = {
        "actor_type": "AGENT",
        "actor_id": state.get("agent", "unknown"),
        "action": action,
        "subject_type": state.get("subject_type", ""),
        "subject_id": subject,
        "correlation_id": state.get("correlation_id", ""),
        "detail": detail or {},
    }

    if writer is None:
        _log.info("agent_audit_local_only", **entry)
        return {"notes": [f"audit(local): {action}"]}

    try:
        await writer(entry)
    except Exception as error:  # noqa: BLE001 - an audit backend being down must not stop a cyclone response; the log line is the fallback record
        _log.error(
            "agent_audit_write_failed",
            action=action,
            subject_id=subject,
            error=type(error).__name__,
            impact="this agent action is recorded only in the logs; the audit chain has "
            "a hole at this correlation id",
        )
        return {"notes": [f"audit(failed): {action}"]}

    return {"notes": [f"audit: {action}"]}


async def rg_append(
    state: AgentState,
    *,
    observations: list[dict[str, Any]],
    writer: Callable[[list[dict[str, Any]]], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Append observations to the Resilience Graph.

    Observations only. An agent never writes an entity: a graph where an agent can create
    a node is a graph where an agent can invent a village, and every count computed over it
    afterwards is wrong in a way nobody can see.
    """
    if not observations:
        return {}

    if writer is None:
        _log.info("rg_append_local_only", count=len(observations))
        return {"notes": [f"rg: {len(observations)} observations (local)"]}

    await writer(observations)
    return {"notes": [f"rg: {len(observations)} observations"]}


def guard(
    predicate: Callable[[AgentState], bool],
    *,
    on_fail: str,
    reason: str,
) -> Callable[[AgentState], str]:
    """A declarative precondition that routes rather than raises.

    Returns a router function for `add_conditional_edges`. The failure goes to a named
    node — usually `human_review` — so the run lands somewhere a person can pick it up
    rather than stopping with a traceback in a log nobody is reading.
    """

    def route(state: AgentState) -> str:
        if predicate(state):
            return "ok"
        _log.info(
            "agent_guard_failed",
            agent=state.get("agent"),
            subject_id=state.get("subject_id"),
            reason=reason,
            routing_to=on_fail,
        )
        return on_fail

    return route


def assert_guard(state: AgentState, predicate: Callable[[AgentState], bool], reason: str) -> None:
    """The raising form, for a precondition with no sensible alternative path.

    Rare on purpose. Most guards should route; this is for the cases where continuing
    would be incoherent rather than merely wrong.

    Raises:
        GuardFailed: naming the precondition, so the review item says what did not hold.
    """
    if not predicate(state):
        raise GuardFailed(f"{state.get('agent', 'agent')}: {reason}")


def with_confidence(
    node: Node,
    *,
    threshold: float = DEFAULT_REVIEW_THRESHOLD,
    on_low: str = "human_review",
) -> Node:
    """Wrap a node so an unconfident answer goes to a person instead of onward.

    This is where `AgentOutput.confidence` stops being a number in a payload and becomes a
    gate. It only means something because the value is calibrated against labelled
    fixtures — an uncalibrated threshold looks like a safety property and is not one.

    The wrapped node's own `needs_human_review` is honoured too. A model saying "I am
    confident and you should check this anyway" is a signal worth more than the number.
    """

    async def wrapped(state: AgentState) -> dict[str, Any]:
        update = await node(state)
        output = update.get("output") or {}

        confidence = float(output.get("confidence", 0.0))
        flagged = bool(output.get("needs_human_review", False))

        if confidence >= threshold and not flagged:
            return update

        reason = (
            output.get("review_reason")
            or f"confidence {confidence:.2f} is below the {threshold:.2f} threshold"
        )
        _log.info(
            "agent_routed_to_review",
            agent=state.get("agent"),
            subject_id=state.get("subject_id"),
            confidence=confidence,
            flagged_by_model=flagged,
            reason=reason,
        )
        return {
            **update,
            "output": {**output, "needs_human_review": True, "review_reason": reason},
            "notes": [*update.get("notes", []), f"review: {reason}"],
            "_route": on_low,
        }

    return wrapped


def request_approval(state: AgentState, *, question: str, detail: dict[str, Any]) -> Any:
    """Pause for a human decision.

    **This node re-executes from the top when the run resumes.** Everything above the
    `interrupt()` call runs a second time, so nothing above it may have a side effect that
    is not idempotent — no audit write, no SMS, no payment. Put those after.

    The payload must be JSON-serialisable and must carry no personal data: it is stored in
    the checkpoint, rendered in the ops console's approval inbox, and read by whoever is
    debugging later.

    Returns whatever the resume passed in — the human's decision.
    """
    from langgraph.types import interrupt

    payload = {
        "question": question,
        "agent": state.get("agent"),
        "subject_type": state.get("subject_type"),
        "subject_id": state.get("subject_id"),
        "detail": detail,
    }
    # One interrupt per node invocation. Two would make the resume ambiguous about which
    # question it is answering.
    return interrupt(payload)


def record_output(output: AgentOutput, *, note: str | None = None) -> dict[str, Any]:
    """Turn a validated model output into a state update.

    One place, so `provenance` and `needs_human_review` reach the state the same way from
    every agent. A node that builds the dict by hand is one that eventually forgets a field
    the review queue reads.
    """
    update: dict[str, Any] = {"output": output.model_dump(mode="json")}
    if note:
        update["notes"] = [note]
    return update
