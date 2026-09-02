"""Resuming a paused dispatch plan's reasoning thread in agent-svc.

This closes the seam file 08 left open and file 12 could not fill: `NullResumer` accepted
every resume and recorded `graph_resumed: false`, because there was no runtime to talk to.
There is one now, and file 16's triage agent is the graph that pauses.

## It forwards the dispatcher's token rather than using a service credential

agent-svc's resume endpoint is `require(Scope.AGENT_REVIEW, allow_machine=False)`. That
refusal is deliberate and it is the reason this adapter looks the way it does: answering an
agent's question is a human act, and no machine principal in the platform holds
`agent:review`.

So incident-svc does not resume on its own authority. It forwards the bearer token of the
person who just approved the plan — a `DISPATCHER` or `DMC_OPERATOR`, both of whom hold
`agent:review` — and agent-svc records the decision against them.

That is also the truthful attribution. The dispatcher decided; this service only carried
the decision across a network boundary. A service credential here would have produced an
audit trail saying incident-svc answered the question, which is false and is exactly the
kind of false record the two-gate design exists to prevent.

## Why a resume failure is fatal on approve and not on reject

`dispatch_gate.approve` turns any exception here into `GraphResumeFailed` and the plan is
not released. A plan whose graph never resumed has not completed the reasoning that produced
it, and releasing it anyway would mean dispatching on a partial decision while the audit
trail claims a complete one.

`reject` swallows the same failure. A rejection that cannot reach the graph is still a
rejection, and refusing it would leave a plan the dispatcher has declined sitting in the
queue looking live. The asymmetry is in the gate, not here — this adapter raises either way
and lets the gate decide what that means.
"""

from __future__ import annotations

from typing import Any, Final

import httpx
import structlog

from sarana_shared.errors import UpstreamUnavailable

_log = structlog.get_logger(__name__)

CONNECT_TIMEOUT: Final = 2.0

# Generous, because the resume runs the rest of the graph. The triage agent's post-gate
# path writes an audit entry and appends observations; a dispatcher watching a spinner is
# better than a dispatcher whose approval timed out halfway through releasing a plan.
READ_TIMEOUT: Final = 30.0


class AgentRuntimeUnavailable(UpstreamUnavailable):
    """agent-svc could not be reached to resume a thread.

    Its own type so the gate can tell it apart from a graph that resumed and refused.
    """

    slug = "agent-runtime-unavailable"
    title = "Agent runtime unavailable"


class AgentThreadResumer:
    """The real resumer: agent-svc's `POST /agents/threads/{id}/resume`."""

    def __init__(self, base_url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def resume(
        self, thread_id: str, payload: dict[str, Any], *, token: str | None = None
    ) -> dict[str, Any]:
        """Resume one thread past its interrupt.

        Raises:
            AgentRuntimeUnavailable: for a missing token, an unreachable service, or any
                refusal. The gate turns that into `GraphResumeFailed` on approve and
                swallows it on reject.
        """
        if not token:
            # Without the dispatcher's token there is nothing this service may present:
            # agent-svc refuses machines, and inventing a credential to get past that
            # would defeat the point of the refusal.
            raise AgentRuntimeUnavailable(
                "No caller token was available to resume the reasoning thread. The resume "
                "is performed as the dispatcher who approved the plan, because agent-svc "
                "refuses machine principals on agent:review."
            )

        body = _as_resume_request(payload)
        try:
            response = await self._client.post(
                f"{self._base_url}/api/v1/agents/threads/{thread_id}/resume",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            _log.warning(
                "agent_runtime_unreachable",
                thread_id=thread_id,
                error=type(error).__name__,
            )
            raise AgentRuntimeUnavailable(
                f"agent-svc is unreachable, so thread {thread_id} was not resumed."
            ) from error

        if response.status_code >= 400:
            # Includes 403, which is what a caller who does not hold `agent:review` gets.
            # Reported rather than swallowed: a dispatcher whose token cannot answer the
            # agent's question needs to know that, and so does whoever configured the role.
            _log.error(
                "agent_runtime_refused_resume",
                thread_id=thread_id,
                status=response.status_code,
                hint=(
                    "403 means the approving user does not hold agent:review; "
                    "404 means the thread is unknown or already finished"
                ),
            )
            raise AgentRuntimeUnavailable(
                f"agent-svc returned {response.status_code} resuming thread {thread_id}."
            )

        state: dict[str, Any] = response.json()
        _log.info(
            "agent_runtime_thread_resumed",
            thread_id=thread_id,
            status=state.get("status"),
            decision=payload.get("decision"),
        )
        # `graph_resumed` is this adapter's own assertion, not a field agent-svc returns.
        # The endpoint answering at all is what proves the graph moved.
        return {**state, "graph_resumed": True}


def _as_resume_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Translate the gate's decision into agent-svc's `ResumeRequest`.

    Two vocabularies meet here and neither should have to know the other. The gate speaks
    `decision: approve|reject` because that is what a dispatch plan's row records;
    agent-svc speaks `approved: bool` because that is what every agent's interrupt asks.
    Translating in the adapter is what keeps both of them readable in their own terms.

    `decided_by` is the approver's id rather than their name. agent-svc stores it on the
    decision and the decision goes into a checkpoint, and a checkpoint carries ids, never
    people.
    """
    approved = payload.get("decision") == "approve"
    extra = {
        key: value
        for key, value in payload.items()
        if key not in {"decision", "approver_id", "reason", "at"}
    }
    return {
        "approved": approved,
        "decided_by": str(payload.get("approver_id", "")),
        "reason": payload.get("reason"),
        "payload": extra,
    }
