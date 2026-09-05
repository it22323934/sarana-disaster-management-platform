"""Dispatch plans, and the human gate.

`POST /dispatch-plans/{id}/approve` is the most consequential endpoint in this service.
It sends people towards a hazard, and the order of its checks is load-bearing: scope,
then TOTP, then the graph, then the write. Nothing before the write can be skipped and
nothing after it can happen without it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from incident_svc.api.deps import CorrelationDep, SessionDep
from incident_svc.domain import dispatch_gate
from incident_svc.repo import OutboxEvent, queries
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.domain.ids import uuid7
from sarana_shared.errors import Conflict, NotFound, Unauthenticated, ValidationFailed
from sarana_shared.events import catalogue
from sarana_shared.events.envelope import EventEnvelope
from sarana_shared.events.outbox import enqueue

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["dispatch"])

ReadPrincipal = Depends(require(Scope.INCIDENT_READ))
ProposePrincipal = Depends(require(Scope.DISPATCH_PROPOSE))

# The human gate. `require` refuses a machine principal on this scope outright, and
# `strip_human_gates` removed it from every agent token at mint time, so an agent cannot
# reach this endpoint even if something upstream is misconfigured.
CommitPrincipal = Depends(require(Scope.DISPATCH_COMMIT, allow_machine=False))


class PlanSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    incident_ids: list[UUID]
    responder_ids: list[UUID]
    estimated_duration_min: int | None
    proposed_at: datetime
    proposed_by_agent: str
    status: str
    signed_off_by: str | None = None
    signed_off_at: datetime | None = None
    rejection_reason: str | None = None


class RouteStop(BaseModel):
    """One incident on one responder's route, in the order it will be reached."""

    model_config = ConfigDict(frozen=True)

    incident_id: str
    sequence: int
    eta_minutes: float


class ResponderRoute(BaseModel):
    model_config = ConfigDict(frozen=True)

    responder_id: str
    stops: list[RouteStop] = Field(default_factory=list)
    total_minutes: float = 0.0


class UnservableIncident(BaseModel):
    """An incident no responder could be routed to, and why.

    Never a silent omission. This is the entry a dispatcher escalates to a different
    agency, and a plan that quietly left it out would look complete while somebody waited.
    """

    model_config = ConfigDict(frozen=True)

    incident_id: str
    reason: str
    detail: str = ""


class IncidentFactors(BaseModel):
    """Why one incident sits where it does in the plan's ranking.

    `factors` stays a free-shaped mapping because the triage model owns its factor names.
    Pinning them here would mean a model that added a term produced a 500 on the gate
    screen, which is the one screen that must not fail.
    """

    model_config = ConfigDict(frozen=True)

    incident_id: str
    rank: int | None = None
    score: float | None = None
    dispatchability: float | None = None
    dispatchable: bool | None = None
    model_version: str | None = None
    method: str | None = None
    factors: dict[str, Any] = Field(default_factory=dict)
    explanation: str | None = None


class PlanReasoning(BaseModel):
    """What the agent did and why, as the `route` column recorded it.

    This is the payload build file 20 requires the dispatch gate to render "expanded by
    default". It has been in the database since file 16 - `Plan.as_route_column()` writes
    exactly this shape - and the only thing missing was a response model that exposed it.

    It is a whole object or nothing. A plan proposed by something that wrote no route
    column has no reasoning, and `None` says that; a half-populated object would let the
    gate screen render an empty factor list under a "why these are ranked here" heading,
    which reads as *the agent considered nothing* rather than *nothing recorded a reason*.
    """

    model_config = ConfigDict(frozen=True)

    routes: list[ResponderRoute] = Field(default_factory=list)
    unservable: list[UnservableIncident] = Field(default_factory=list)
    factors: list[IncidentFactors] = Field(default_factory=list)
    method: str | None = None
    status: str | None = None
    rationale: str | None = None
    rationale_method: str | None = None


class PlanDetail(PlanSummary):
    """One plan, with the reasoning behind it.

    Separate from `PlanSummary` rather than widening it: the list endpoint is polled every
    five seconds for the gate banner's count, and a national event puts hundreds of plans
    in it. Sending every factor breakdown on every poll would make the cheapest query in
    the console the most expensive one.
    """

    model_config = ConfigDict(frozen=True)

    langgraph_thread_id: str | None = None
    reasoning: PlanReasoning | None = Field(
        default=None,
        description="None when this plan carries no recorded reasoning at all.",
    )


def _reasoning_from(route: Any) -> PlanReasoning | None:
    """Read the `route` JSONB column into the gate screen's contract.

    Tolerant on the way in and strict on the way out. The column is written by the triage
    agent and could have been written by an older version of it, so a missing key becomes
    an empty list rather than a 500 on the one screen that must not fail. An empty or
    absent column returns None, which the console renders as "no reasoning was recorded"
    rather than as "the agent considered nothing".
    """
    if not isinstance(route, dict) or not route:
        return None
    return PlanReasoning(
        routes=[r for r in route.get("routes") or [] if isinstance(r, dict)],
        unservable=[u for u in route.get("unservable") or [] if isinstance(u, dict)],
        factors=[f for f in route.get("factors") or [] if isinstance(f, dict)],
        method=route.get("method"),
        status=route.get("status"),
        rationale=route.get("rationale"),
        rationale_method=route.get("rationale_method"),
    )


class ResponderSummary(BaseModel):
    """A team or vehicle, and where it currently is.

    Typed rather than left as a bare dict, because it was not: the console had guessed a
    `callsign` field this service has never had, and an untyped endpoint let the guess
    survive to the browser, where it failed at the zod boundary and quietly emptied the
    responder list on the dispatch gate. A response model makes the vocabulary a contract.

    `lon`/`lat` are the responder's last known position and are nullable, which is the
    honest state for a team that has not reported one. The map draws only the ones that
    have a position and says how many it could not place, exactly as it does for incidents.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    org: str
    type: str
    capacity: int
    status: str
    home_gn_division_id: str | None = None
    lon: float | None = None
    lat: float | None = None


class ApproveRequest(BaseModel):
    """A dispatcher releasing a plan.

    Carries no TOTP code: the second factor is verified by core-api's step-up endpoint,
    which owns the MFA secrets, and this request is authorised by the step-up stamp its
    token carries. See `domain/dispatch_gate.py` for why the check lives there.
    """

    model_config = ConfigDict(extra="forbid")

    acknowledged: bool = Field(
        default=True,
        description="Reserved for the console's confirmation dialogue.",
    )


class RejectRequest(BaseModel):
    """A dispatcher turning a plan down.

    The reason comes from a fixed taxonomy because rejections are the training signal the
    Learn loop runs on, and free text cannot be aggregated.
    """

    model_config = ConfigDict(extra="forbid")

    reason: dispatch_gate.RejectionReason
    note: str | None = Field(default=None, max_length=1000)


class DecisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan_id: str
    status: str
    decided_by: str
    decided_at: datetime
    graph_resumed: bool = Field(
        description="False when no agent reasoning thread was attached to this plan."
    )
    reason: str | None = None


@router.get("/dispatch-plans", response_model=list[PlanSummary])
async def list_plans(
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    status_filter: str | None = Query(default=None, alias="status", max_length=24),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Any:
    return await queries.list_plans(session, status=status_filter, limit=limit, offset=offset)


@router.get("/dispatch-plans/{plan_id}", response_model=PlanDetail)
async def get_plan(
    plan_id: UUID,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
) -> Any:
    """One plan, with the reasoning the human gate is required to show.

    The factor breakdown and the `unservable` list are read from the plan's own `route`
    column rather than from the agent's interrupt payload. They are the same data - the
    triage agent writes both from one `Plan` - and reading the column means the gate screen
    works for a plan whose reasoning thread has already been checkpointed away, which is
    every plan more than an hour old.
    """
    row = await queries.get_plan(session, plan_id)
    if row is None:
        raise NotFound("No such dispatch plan.", context={"plan_id": str(plan_id)})
    return {
        **row,
        "id": str(row["id"]),
        "reasoning": _reasoning_from(row.get("route")),
    }


def _caller_token(request: Request) -> str | None:
    """The raw bearer token this request arrived with, for forwarding to agent-svc.

    Returns None rather than raising. The middleware has already authenticated the caller
    by the time either endpoint runs, so an absent header here means a test client or a
    transport that stripped it - not an authorisation problem - and
    `AgentThreadResumer.resume` refuses with a sentence saying exactly what is missing.

    Forwarding a token is a thing to do carefully, so: it goes to one URL, configured at
    boot, over one endpoint that refuses machine principals. It is never logged, never
    stored, and never sent anywhere the deployment did not name.
    """
    header = request.headers.get("Authorization") or ""
    scheme, _, credential = header.partition(" ")
    return credential.strip() if scheme.lower() == "bearer" and credential.strip() else None


@router.post("/dispatch-plans/{plan_id}/approve", response_model=DecisionResponse)
async def approve_plan(
    plan_id: UUID,
    body: ApproveRequest,
    request: Request,
    session: SessionDep,
    correlation_id: CorrelationDep,
    principal: Principal = CommitPrincipal,
) -> Any:
    """**HUMAN GATE.** Release a dispatch plan.

    Four independent things must all hold, and each fails differently on purpose:

      - `Scope.DISPATCH_COMMIT`, refused to every machine principal (403).
      - A second factor verified within the last five minutes (401 - the caller may hold
        the scope; what is missing is proof of who is at the keyboard).
      - The plan has not already been decided (409).
      - The database accepts the write, whose trigger rejects RELEASED without a sign-off.
    """
    plan = await queries.get_plan(session, plan_id)
    if plan is None:
        raise NotFound("No such dispatch plan.", context={"plan_id": str(plan_id)})

    try:
        decision = await dispatch_gate.approve(
            plan,
            principal=principal,
            resumer=request.app.state.thread_resumer,
            # The dispatcher's own token, forwarded. agent-svc refuses machine principals
            # on `agent:review`, so the resume is performed as the person who decided -
            # which is also the truthful attribution.
            token=_caller_token(request),
        )
    except dispatch_gate.StepUpFailed as error:
        _log.warning("dispatch_step_up_failed", plan_id=str(plan_id), actor=principal.subject_id)
        raise Unauthenticated(
            str(error), context={"reason": "step_up_required", "plan_id": str(plan_id)}
        ) from error
    except dispatch_gate.AlreadyDecided as error:
        raise Conflict(str(error), context={"plan_id": str(plan_id)}) from error
    except dispatch_gate.GateRefused as error:
        raise Conflict(str(error), context={"plan_id": str(plan_id)}) from error

    released = await queries.release_plan(session, plan_id, decision.approver_id)
    if released is None:
        # Lost a race with another approver. The database decided, not the application.
        raise Conflict(
            f"dispatch plan {plan_id} was signed off by someone else while this request "
            "was in flight",
            context={"plan_id": str(plan_id)},
        )

    enqueue(
        session,
        OutboxEvent,
        EventEnvelope(
            event_type=catalogue.DISPATCH_SIGNOFF_GRANTED,
            producer="incident-svc",
            correlation_id=uuid7(),
            subject=str(plan_id),
            payload=decision.as_audit_payload(),
        ),
    )

    _log.info(
        "dispatch_released",
        plan_id=str(plan_id),
        approver_id=principal.subject_id,
        graph_resumed=decision.graph_resumed,
    )

    return {
        "plan_id": released["id"],
        "status": released["status"],
        "decided_by": released["signed_off_by"],
        "decided_at": released["signed_off_at"],
        "graph_resumed": decision.graph_resumed,
    }


@router.post("/dispatch-plans/{plan_id}/reject", response_model=DecisionResponse)
async def reject_plan(
    plan_id: UUID,
    body: RejectRequest,
    request: Request,
    session: SessionDep,
    correlation_id: CorrelationDep,
    principal: Principal = CommitPrincipal,
) -> Any:
    """Turn a plan down, with a reason the Learn loop can use."""
    plan = await queries.get_plan(session, plan_id)
    if plan is None:
        raise NotFound("No such dispatch plan.", context={"plan_id": str(plan_id)})

    try:
        decision = await dispatch_gate.reject(
            plan,
            principal=principal,
            reason=body.reason,
            note=body.note,
            resumer=request.app.state.thread_resumer,
            token=_caller_token(request),
        )
    except dispatch_gate.StepUpFailed as error:
        raise Unauthenticated(str(error), context={"reason": "step_up_required"}) from error
    except dispatch_gate.AlreadyDecided as error:
        raise Conflict(str(error)) from error
    except dispatch_gate.GateRefused as error:
        raise ValidationFailed(str(error)) from error

    rejected = await queries.reject_plan(session, plan_id, body.reason.value)
    if rejected is None:
        raise Conflict(
            f"dispatch plan {plan_id} was already decided while this request was in flight"
        )

    enqueue(
        session,
        OutboxEvent,
        EventEnvelope(
            event_type=catalogue.DISPATCH_SIGNOFF_REJECTED,
            producer="incident-svc",
            correlation_id=uuid7(),
            subject=str(plan_id),
            payload=decision.as_audit_payload(),
        ),
    )

    # Every rejected plan returns its incidents to the queue. They still need someone.
    for incident_id in plan["incident_ids"]:
        current = await queries.get_incident(session, incident_id)
        if current and current["status"] not in {"RESOLVED", "REJECTED", "DUPLICATE"}:
            await queries.set_incident_status(session, incident_id, "TRIAGED")

    return {
        "plan_id": rejected["id"],
        "status": rejected["status"],
        "decided_by": str(decision.approver_id),
        "decided_at": decision.at,
        "graph_resumed": decision.graph_resumed,
        "reason": body.reason.value,
    }


@router.get("/responders", response_model=list[ResponderSummary])
async def list_responders(
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    available: bool | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> Any:
    return await queries.list_responders(session, available=available, limit=limit)
