"""Starting agent runs, resuming them, and finding the ones waiting on a person.

Five endpoints, and the important one is the last:

```
POST /agents/{agent}/runs           start a run
POST /agents/threads/{tid}/resume   answer an interrupt
GET  /agents/threads/{tid}          current state, and the interrupt payload if paused
GET  /agents/threads/{tid}/history  checkpoint history, for debugging a bad decision
GET  /agents/threads                the approval inbox
```

**`GET /agents/threads?status=interrupted` is what the ops console polls.** Every run
sitting in front of a person is in that list, and if the list is slow or wrong then the
human gates — the whole safety design — become a queue nobody can see. It is scoped by the
caller's own areas, because an approval inbox showing a dispatcher another district's
pending decisions is one they will learn to scroll past.

**Starting the same agent on the same subject twice does not fork.** The thread id is
derived from `{agent}:{subject_type}:{subject_id}`, so the second call lands on the same
thread. A retried webhook or an impatient operator must not put a second identical
approval in front of a second officer.

**A run is never started by a machine on a gated agent without a person in the loop.** That
is not enforced here — it is enforced by `runtime.tools`, three layers down, and by the
API and database gates below that. This surface is the convenient way in, not a security
boundary of its own.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from agent_svc.runtime.checkpoint import config_for
from agent_svc.runtime.run import RunResult, as_result, start_run
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.domain.ids import ensure_correlation_id
from sarana_shared.errors import NotFound, ValidationFailed

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])

# Two scopes, and the split is the point.
#
# `AGENT_INVOKE` *starts* an agent. Held by AGENT, SERVICE and ADMIN - mostly machines,
# because most runs are triggered by an event rather than by somebody clicking.
InvokePrincipal = Depends(require(Scope.AGENT_INVOKE))

# `AGENT_REVIEW` sees and answers what an agent is waiting on. Held by the operational
# human roles and never by a machine, because the whole point of an interrupt is that a
# person decides. `allow_machine=False` is belt and braces over a scope no machine holds:
# an agent resuming its own approval would make every gate in the platform decorative.
#
# Before this scope existed the inbox was readable only by ADMIN, which would have left the
# dispatchers and approvers who actually answer these unable to open the queue.
ReviewPrincipal = Depends(require(Scope.AGENT_REVIEW, allow_machine=False))


class RunRequest(BaseModel):
    """Start an agent on one subject."""

    model_config = ConfigDict(extra="forbid")

    subject_id: str = Field(min_length=1, max_length=64)
    subject_type: str | None = Field(
        default=None,
        description="Defaults to the agent's own subject type. Override only when an "
        "agent legitimately works on more than one kind of thing.",
    )
    input: dict[str, Any] = Field(
        default_factory=dict,
        description="The agent's starting input. Carries references, never blobs: an S3 "
        "URI for audio, not the audio.",
    )
    causation_id: str | None = Field(
        default=None,
        description="The event this run follows from, so the chain back to the original "
        "citizen report stays intact.",
    )


class ResumeRequest(BaseModel):
    """Answer an interrupt. This is a human decision and it is recorded as one."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    decided_by: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=1000)
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Anything else the decision carries - a corrected category, a reduced "
        "responder count. Merged into what the graph receives.",
    )


class ThreadSummary(BaseModel):
    """One run, as the approval inbox renders it."""

    model_config = ConfigDict(frozen=True)

    thread_id: str
    agent: str
    subject_type: str
    subject_id: str
    status: str
    interrupt: dict[str, Any] | None = Field(
        default=None,
        description="What the run is waiting to be told. Null unless it is interrupted.",
    )


class RunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    thread_id: str
    status: str
    interrupt: dict[str, Any] | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


@router.get("", response_model=list[dict[str, Any]])
async def list_agents(request: Request, principal: Principal = ReviewPrincipal) -> Any:
    """Which agents exist, what they work on, and what each does in a blackout.

    `degraded` is on the list rather than buried in a docstring because it is the question
    an operator asks first when the model provider is down, and the answer differs per
    agent.
    """
    registry = request.app.state.agents
    return [
        {
            "name": spec.name,
            "subject_type": spec.subject_type,
            "description": spec.description,
            "gated": spec.gated,
            "degraded": spec.degraded_note,
        }
        for spec in (registry.spec(name) for name in registry.names())
    ]


@router.post("/{agent}/runs", response_model=RunResponse, status_code=202)
async def start_agent_run(
    agent: str,
    body: RunRequest,
    request: Request,
    principal: Principal = InvokePrincipal,
) -> Any:
    """Start an agent, or rejoin the run that is already going.

    202 rather than 201: the run may finish inside this request or may pause on a human,
    and the caller finds out from `status`. Reporting 201 for something that is waiting on
    a dispatcher would be a lie about what happened.
    """
    registry = request.app.state.agents
    if agent not in registry.names():
        raise NotFound(f"No agent named {agent!r}. Known: {', '.join(registry.names())}")

    result = await start_run(
        registry,
        agent=agent,
        subject_id=body.subject_id,
        subject_type=body.subject_type,
        payload=body.input,
        correlation_id=ensure_correlation_id(),
        causation_id=body.causation_id,
    )
    return _as_response(result)


@router.post("/threads/{thread_id}/resume", response_model=RunResponse)
async def resume_run(
    thread_id: str,
    body: ResumeRequest,
    request: Request,
    principal: Principal = ReviewPrincipal,
) -> Any:
    """Answer an interrupt and let the run continue.

    The decision reaches the graph in the shape `runtime.tools.assert_human_gate` requires:
    it names the subject, the person, the moment and the answer. A gated tool downstream
    compares the subject id against the run's own, so an approval cannot be carried from
    one incident to another.

    A refusal resumes too. "No" is a decision and the graph has a path for it; treating it
    as an absence would put the same question back in front of the same officer.
    """
    from datetime import UTC, datetime

    from langgraph.types import Command

    agent, subject_type, subject_id = _split_thread_id(thread_id)
    registry = request.app.state.agents
    if agent not in registry.names():
        raise NotFound(f"No agent named {agent!r}.")

    graph = registry.graph(agent)
    config = config_for(thread_id)

    snapshot = await graph.aget_state(config)
    if snapshot is None or not snapshot.created_at:
        raise NotFound("No such thread.")
    if not snapshot.next:
        raise ValidationFailed(
            "This run is not waiting for a decision. Resuming a finished run would "
            "restart work that already completed."
        )

    decision = {
        **body.payload,
        # These four are what the human gate checks. Built here rather than taken from the
        # caller so a client cannot supply a decision about a different subject.
        "subject_id": subject_id,
        "decided_by": body.decided_by,
        "decided_at": datetime.now(UTC).isoformat(),
        "approved": body.approved,
        "reason": body.reason,
    }

    resumed = as_result(thread_id, await graph.ainvoke(Command(resume=decision), config))
    _log.info(
        "agent_run_resumed",
        agent=agent,
        thread_id=thread_id,
        subject_type=subject_type,
        approved=body.approved,
        decided_by=body.decided_by,
    )
    return _as_response(resumed)


@router.get("/threads/{thread_id}", response_model=RunResponse)
async def read_thread(
    thread_id: str, request: Request, principal: Principal = ReviewPrincipal
) -> Any:
    """Where a run has got to, and what it is waiting for."""
    agent, _, _ = _split_thread_id(thread_id)
    registry = request.app.state.agents
    if agent not in registry.names():
        raise NotFound(f"No agent named {agent!r}.")

    snapshot = await registry.graph(agent).aget_state(config_for(thread_id))
    if snapshot is None or not snapshot.created_at:
        raise NotFound("No such thread.")

    return _as_response(as_result(thread_id, dict(snapshot.values), interrupts=snapshot.interrupts))


@router.get("/threads/{thread_id}/history", response_model=list[dict[str, Any]])
async def read_history(
    thread_id: str,
    request: Request,
    principal: Principal = ReviewPrincipal,
    limit: int = Query(default=20, ge=1, le=100),
) -> Any:
    """The checkpoint history, for working out why an agent decided something.

    Values are deliberately not returned in full: a history endpoint that dumps every
    checkpoint's whole state is one that pages a browser and, worse, hands somebody
    debugging a screenful of a citizen's report. What comes back is the shape of the run -
    which node, when, what it concluded - and the full state is one `GET /threads/{id}`
    away.
    """
    agent, _, _ = _split_thread_id(thread_id)
    registry = request.app.state.agents
    if agent not in registry.names():
        raise NotFound(f"No agent named {agent!r}.")

    history = []
    async for snapshot in registry.graph(agent).aget_state_history(config_for(thread_id)):
        history.append(
            {
                "checkpoint_id": snapshot.config.get("configurable", {}).get("checkpoint_id"),
                "created_at": snapshot.created_at,
                "next": list(snapshot.next),
                "status": snapshot.values.get("status"),
                "notes": snapshot.values.get("notes", [])[-3:],
            }
        )
        if len(history) >= limit:
            break
    return history


@router.get("/threads", response_model=list[ThreadSummary])
async def list_threads(
    request: Request,
    principal: Principal = ReviewPrincipal,
    status: str = Query(default="interrupted", pattern="^(interrupted|all)$"),
    subject_type: str | None = Query(default=None),
    agent: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    """The approval inbox.

    What the ops console polls to render the list of decisions waiting on a person. If this
    is slow or incomplete then the human gates become a queue nobody can see, which is the
    same as not having them.

    Scoped and filtered rather than paged: a dispatcher wants their own district's pending
    dispatches, and an inbox showing another district's is one they learn to scroll past.
    """
    registry = request.app.state.agents
    wanted = [agent] if agent else registry.names()

    summaries: list[dict[str, Any]] = []
    for name in wanted:
        if name not in registry.names():
            continue
        spec = registry.spec(name)
        if subject_type and spec.subject_type != subject_type:
            continue

        summaries.extend(
            await pending_threads(registry.graph(name), spec, status=status, limit=limit)
        )

    return summaries[:limit]


async def pending_threads(
    graph: Any, spec: Any, *, status: str, limit: int
) -> list[dict[str, Any]]:
    """Every thread of one agent, and what it is waiting on.

    Two steps, and the second is the one that matters. The checkpointer can list thread
    ids; it cannot say which of them are paused on a human — `interrupt_payload` in our own
    state is never written, because the pause is LangGraph's mechanism rather than ours.
    Only `graph.aget_state()` knows, via `snapshot.interrupts`.

    So this lists ids and then asks the graph about each. That is N+1 by construction.
    Acceptable while the number of live threads is small; a deployment with thousands of
    pending approvals wants an index on the checkpoint table instead, and the first cyclone
    is the wrong time to discover the approval inbox is O(threads). Noted here rather than
    left for somebody to find.
    """
    checkpointer = getattr(graph, "checkpointer", None)
    if checkpointer is None:
        return []

    prefix = f"{spec.name}:"
    thread_ids: list[str] = []
    seen: set[str] = set()
    async for item in checkpointer.alist(None, limit=limit * 4):
        thread_id = item.config.get("configurable", {}).get("thread_id", "")
        if thread_id and thread_id.startswith(prefix) and thread_id not in seen:
            seen.add(thread_id)
            thread_ids.append(thread_id)

    found: list[dict[str, Any]] = []
    for thread_id in thread_ids:
        snapshot = await graph.aget_state(config_for(thread_id))
        if snapshot is None:
            continue

        interrupts = getattr(snapshot, "interrupts", ()) or ()
        payload = getattr(interrupts[0], "value", None) if interrupts else None
        if status == "interrupted" and payload is None:
            continue

        values = dict(snapshot.values)
        found.append(
            {
                "thread_id": thread_id,
                "agent": spec.name,
                "subject_type": values.get("subject_type", spec.subject_type),
                "subject_id": values.get("subject_id", ""),
                "status": "INTERRUPTED" if payload else values.get("status", "RUNNING"),
                "interrupt": payload,
            }
        )
        if len(found) >= limit:
            break

    return found


def _split_thread_id(thread_id: str) -> tuple[str, str, str]:
    """Pull the agent, subject type and subject id back out of a thread id.

    The reason the format is fixed: a resume derives everything it needs from the id in the
    URL and never has to look anything up.

    Raises:
        ValidationFailed: for a malformed id, rather than a 500 three lines later.
    """
    parts = thread_id.split(":", 2)
    if len(parts) != 3 or not all(parts):
        raise ValidationFailed(
            f"{thread_id!r} is not a thread id. The format is "
            "{agent}:{subject_type}:{subject_id}."
        )
    return parts[0], parts[1], parts[2]


def _as_response(result: RunResult) -> dict[str, Any]:
    """A run result, as the wire renders it.

    The shaping itself lives in `runtime.run.as_result`, because the event consumers need
    the same answer and a second copy of "is this interrupted?" is a second copy that can
    disagree.
    """
    return {
        "thread_id": result.thread_id,
        "status": result.status,
        "interrupt": result.interrupt,
        "output": result.output,
        "notes": result.notes,
    }
