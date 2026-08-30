"""Starting a run, in the one place both callers reach it.

Two things start agents: an HTTP request from the ops console, and an event arriving on the
bus. They must behave identically, because the second one is how nearly every real run
begins and the first one is how every run gets debugged. Two copies of this logic would
drift, and the drift would show up as "it works when I click it".

**Starting a run that is already waiting on a person does not restart it.** This is the
whole reason the function exists rather than three lines inlined in each caller. LangGraph
takes fresh input on an interrupted thread as a new update from `START`: the graph re-enters
at the top, every pre-interrupt node runs again, and the approval an officer is halfway
through answering is rebuilt underneath them. A retried webhook, a redelivered event or an
impatient second click must all land on the pending run and leave it exactly as it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from agent_svc.runtime.checkpoint import config_for
from agent_svc.runtime.state import initial_state, thread_id_for
from sarana_shared.domain.ids import ensure_correlation_id

_log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RunResult:
    """Where a run got to, for whichever caller started it."""

    thread_id: str
    status: str
    interrupt: dict[str, Any] | None = None
    output: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    # True when the run was already in flight and this call left it alone. The consumer
    # logs it; the HTTP surface reports the same 202 either way, because from the caller's
    # side "your run is going" is the same answer however many times they asked.
    rejoined: bool = False

    @property
    def waiting_on_a_person(self) -> bool:
        return self.interrupt is not None


async def start_run(
    registry: Any,
    *,
    agent: str,
    subject_id: str,
    subject_type: str | None = None,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> RunResult:
    """Start `agent` on one subject, or rejoin the run already going for it.

    Raises:
        KeyError: for an unregistered agent. Callers turn that into whatever their surface
            owes the requester - a 404 naming the known agents, or a logged configuration
            error for a consumer whose trigger table has fallen out of step with the
            agents this process actually hosts.
    """
    spec = registry.spec(agent)
    resolved_type = subject_type or spec.subject_type
    thread_id = thread_id_for(agent, resolved_type, subject_id)
    config = config_for(thread_id)
    graph = registry.graph(agent)

    existing = await _pending(graph, config)
    if existing is not None:
        _log.info("agent_run_rejoined", agent=agent, thread_id=thread_id)
        return existing

    state = initial_state(
        agent=agent,
        subject_type=resolved_type,
        subject_id=subject_id,
        correlation_id=correlation_id or ensure_correlation_id(),
        causation_id=causation_id,
    )
    # The caller's input lands in `output` because that is the key nodes read and write.
    # Naming it `input` on the wire and `output` in state is the one place those differ; a
    # separate state key would mean every node checking two places for its data.
    state["output"] = dict(payload or {})

    result = await graph.ainvoke(state, config)
    _log.info(
        "agent_run_started",
        agent=agent,
        thread_id=thread_id,
        interrupted="__interrupt__" in result,
    )
    return as_result(thread_id, result)


async def _pending(graph: Any, config: dict[str, Any]) -> RunResult | None:
    """The run already in flight on this thread, if there is one.

    "In flight" means the graph has somewhere left to go — `snapshot.next` is non-empty.
    A finished run leaves nothing pending, so starting the same agent on the same subject
    after it completed genuinely re-runs it, which is what an operator asking again means.
    """
    snapshot = await graph.aget_state(config)
    if snapshot is None or not snapshot.created_at or not snapshot.next:
        return None

    thread_id = config.get("configurable", {}).get("thread_id", "")
    return as_result(
        thread_id, dict(snapshot.values), interrupts=snapshot.interrupts, rejoined=True
    )


def as_result(
    thread_id: str,
    values: dict[str, Any],
    *,
    interrupts: Any = None,
    rejoined: bool = False,
) -> RunResult:
    """Shape a graph result.

    An interrupted run reports `INTERRUPTED` and carries what it is asking, because a
    caller that has to infer "waiting on a human" from the absence of an output will
    eventually infer it wrong.
    """
    pending = values.get("__interrupt__") or interrupts or []
    interrupt = None
    if pending:
        first = pending[0]
        interrupt = getattr(first, "value", first)

    return RunResult(
        thread_id=thread_id,
        status="INTERRUPTED" if interrupt else values.get("status", "RUNNING"),
        interrupt=interrupt,
        output=values.get("output", {}),
        notes=values.get("notes", []),
        rejoined=rejoined,
    )
