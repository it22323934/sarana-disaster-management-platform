r"""The triage and dispatch agent.

```
START -> receive -> score_priority -> rank_queue -> check_resources -> compute_routes
      -> assemble_plan -> dispatch_signoff  ** MANDATORY HUMAN GATE **
      -> approve: release -> record -> END
      -> reject:  record_rejection -> record -> END
```

This agent is where the two-gate design earns its keep. It can be as autonomous as we like
right up to the moment a vehicle moves, and then it stops.

## The gate, and the four things that hold it

`release` calls a tool registered with `requires_human_gate=True`, so
`runtime.tools.assert_human_gate` refuses it without a decision naming **this plan**. That
is the layer inside this service. Three more sit outside it:

  1. `Scope.DISPATCH_COMMIT` is removed from every machine principal at mint time by
     `strip_human_gates`, so no agent can hold it however it is configured;
  2. `incident_svc.domain.dispatch_gate.approve` is the only writer of `signed_off_by`, and
     it requires a second factor verified within five minutes;
  3. a database trigger rejects RELEASED without a recorded sign-off, whichever application
     wrote the row.

Four independent layers for one property looks like paranoia until you consider what it
protects: an agent, unattended at 3 a.m., sending people towards a hazard, with nobody
accountable for the decision.

**This agent never releases anything.** `release` records what a person already decided and
emits the event. The decision was made by `dispatch_gate.approve` before the graph was
resumed at all.

## Rejections are the most valuable data in the system

A rejected plan is a dispatcher telling us the ranking was wrong, in a situation where they
know something the platform does not. `record_rejection` writes a taxonomy reason, appends
an observation to the Resilience Graph, and re-queues the incidents — none of which happens
if a rejection is treated as an error path.

## Where a model is used

One node writes a sentence. `assemble_plan` asks for a trilingual rationale after the
ranking and the routes are already fixed, and discards it whole if it comes back in fewer
than three languages. Scoring, ranking, resource checking and routing reach no model at all,
so a total provider outage changes the prose and nothing else — which is the property build
file 16 asks for.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final

import structlog
from langgraph.graph import END, START, StateGraph

from agent_svc.agents.triage import plan as plan_rules
from agent_svc.agents.triage import rejections, scoring
from agent_svc.agents.triage import routing as routing_rules
from agent_svc.agents.triage.ports import (
    Incident,
    IncidentSource,
    ModelCall,
    PlanStore,
    Responder,
    ResponderSource,
    RouteSolver,
)
from agent_svc.runtime.nodes import audit_write, request_approval, rg_append
from agent_svc.runtime.registry import AgentSpec
from agent_svc.runtime.state import AgentState
from agent_svc.runtime.tools import REGISTRY as TOOLS
from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now

_log = structlog.get_logger(__name__)

AGENT: Final = "triage"
SUBJECT_TYPE: Final = "dispatch_plan"

# The event this agent emits once a plan has been released by a person. Never emitted on
# the agent's own authority - `release` runs only after `dispatch_signoff` returned an
# approval, and the gated tool refuses without one.
EVENT_RELEASED: Final = "dispatch.plan.released"


class TriageState(AgentState, total=False):
    """The triage run's own state.

    Carries the queue, the plan and the decision. No responder's name, no citizen's, and no
    household id: a dispatch plan is read in an operations room and its checkpoint outlives
    the run.
    """

    district_code: str | None
    incidents: list[dict[str, Any]]
    responders: list[dict[str, Any]]
    scores: list[dict[str, Any]]
    plan: dict[str, Any]
    plan_id: str
    released: bool
    rejection: dict[str, Any]
    observations: Annotated[list[dict[str, Any]], list.__add__]


# ---------------------------------------------------------------------------------------
# The gated tool. This is the layer inside agent-svc.
# ---------------------------------------------------------------------------------------


async def _release_dispatch(*, store: PlanStore, plan_id: str, decision: dict[str, Any]) -> str:
    """Record that a person released this plan, and return its id.

    Gated: `runtime.tools.assert_human_gate` refuses this call without a decision naming
    this exact subject, so the function is never entered on the agent's own authority.

    It writes no status. `incident_svc.domain.dispatch_gate.approve` is the only writer of
    `signed_off_by`, and it has already run by the time the graph is resumed — this records
    the agent's side of a decision somebody else made.
    """
    _log.info(
        "triage_plan_released",
        plan_id=plan_id,
        decided_by=str(decision.get("decided_by")),
        note="recorded by the agent; the release itself was performed by the dispatch gate",
    )
    return plan_id


TOOLS.tool(side_effect=True, requires_human_gate=True, name="release_dispatch_plan")(
    _release_dispatch
)


# ---------------------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------------------


def build_nodes(
    *,
    incidents: IncidentSource,
    responders: ResponderSource,
    store: PlanStore,
    solver: RouteSolver | None = None,
    model: scoring.TriageModel | None = None,
    call: ModelCall | None = None,
    now: datetime | None = None,
    time_limit_s: float = routing_rules.DEFAULT_TIME_LIMIT_S,
    audit: Any = None,
    graph_writer: Any = None,
) -> dict[str, Any]:
    """Build the nodes, closed over their dependencies.

    `now` is injected rather than read inside a node, because ageing is a claim about how
    long an incident has waited and a test that could not fix the clock could not test the
    property that stops incidents starving.
    """
    engine = model or scoring.WeightedSumModel()
    router = solver or routing_rules.default_solver()

    def clock() -> datetime:
        return now if now is not None else utc_now()

    async def receive(state: TriageState) -> dict[str, Any]:
        """Read the open queue and who is available."""
        district = state.get("output", {}).get("district_code")
        open_incidents = await incidents.open_incidents(district_code=district)
        available = await responders.available(district_code=district)

        _log.info(
            "triage_queue_received",
            district=district,
            incidents=len(open_incidents),
            responders=len(available),
        )
        return {
            "district_code": district,
            "incidents": [_incident_as_dict(item) for item in open_incidents],
            "responders": [_responder_as_dict(item) for item in available],
            "notes": [f"{len(open_incidents)} open incidents, {len(available)} responders"],
        }

    async def score_priority(state: TriageState) -> dict[str, Any]:
        """Score every open incident. Deterministic, no model, every term returned."""
        moment = clock()
        factors = [
            scoring.TriageFactors(
                incident_id=raw["incident_id"],
                incident_type=raw["incident_type"],
                immediate_danger=bool(raw.get("immediate_danger")),
                people_at_risk=raw.get("people_at_risk"),
                vulnerable_present=tuple(raw.get("vulnerable_present", [])),
                minutes_since_report=_minutes_since(raw["first_reported_at"], moment),
                location_confidence=float(raw.get("location_confidence", 1.0)),
                access_feasibility=float(raw.get("access_feasibility", 1.0)),
                corroboration_count=int(raw.get("corroboration_count", 1)),
            )
            for raw in state.get("incidents", [])
        ]
        scored = [engine.score(item) for item in factors]

        _log.info(
            "triage_incidents_scored",
            count=len(scored),
            method=engine.method,
            version=engine.model_version,
            undispatchable=sum(1 for item in scored if not item.dispatchable),
        )
        return {
            "scores": [_score_as_dict(item) for item in scored],
            "notes": [f"scored {len(scored)} incidents ({engine.method})"],
        }

    async def rank_queue(state: TriageState) -> dict[str, Any]:
        """Order the queue, most urgent first, ties broken on age.

        Ranking is separate from scoring so the tie-break rule has somewhere to live and
        somewhere to be tested. A queue that reorders under a dispatcher between refreshes
        is one they stop trusting.
        """
        raw_scores = state.get("scores", [])
        by_id = {raw["incident_id"]: raw for raw in state.get("incidents", [])}

        ordered = sorted(
            raw_scores,
            key=lambda item: (
                -float(item["score"]),
                -_minutes_since(by_id[item["incident_id"]]["first_reported_at"], clock())
                if item["incident_id"] in by_id
                else 0.0,
                item["incident_id"],
            ),
        )
        return {
            "scores": ordered,
            "notes": [f"queue ranked; top is {ordered[0]['incident_id']}" if ordered else "empty"],
        }

    async def check_resources(state: TriageState) -> dict[str, Any]:
        """Say plainly when there is nobody to send.

        A plan with no responders is not an error and it is not an empty screen: it is the
        information that the district has run out of crews, which is the thing a dispatcher
        escalates on.
        """
        available = state.get("responders", [])
        if not available:
            _log.warning(
                "triage_no_responders_available",
                district=state.get("district_code"),
                incidents=len(state.get("incidents", [])),
                impact="no plan can be proposed; every incident stays queued and this needs "
                "escalating to another agency",
            )
        return {"notes": [f"{len(available)} responders available"]}

    async def compute_routes(state: TriageState) -> dict[str, Any]:
        """Solve the routing. Fully deterministic; no model touches a route."""
        ranked_ids = [raw["incident_id"] for raw in state.get("scores", [])]
        by_id = {raw["incident_id"]: _incident_from(raw) for raw in state.get("incidents", [])}

        # Only dispatchable incidents are routed. An incident nobody can place stays at its
        # full urgency in the queue and comes back as unservable - it is not ranked down,
        # which would quietly deprioritise the people the platform serves worst.
        dispatchable = {
            raw["incident_id"] for raw in state.get("scores", []) if raw.get("dispatchable", True)
        }
        ordered = [
            by_id[incident_id]
            for incident_id in ranked_ids[: plan_rules.MAX_INCIDENTS_PER_PLAN]
            if incident_id in by_id and incident_id in dispatchable
        ]
        crews = [_responder_from(raw) for raw in state.get("responders", [])]

        routes = router.solve(ordered, crews, time_limit_s=time_limit_s)
        return {
            "plan": {
                "routes": routes.route_summary(),
                "unservable": [item.as_dict() for item in routes.unservable],
                "method": routes.method,
                "solver_status": routes.solver_status,
                "estimated_duration_min": routes.estimated_duration_min,
                "served": routes.served,
            },
            "notes": [
                f"{len(routes.served)} incidents routed via {routes.method}, "
                f"{len(routes.unservable)} unservable"
            ],
        }

    async def assemble_plan(state: TriageState) -> dict[str, Any]:
        """Write the plan in PROPOSED and attach the rationale.

        The only node that writes before the gate, and what it writes is a proposal. There
        is no argument it can pass that produces a released plan.
        """
        by_id = {raw["incident_id"]: _incident_from(raw) for raw in state.get("incidents", [])}
        scores = [_score_from(raw) for raw in state.get("scores", [])]
        crews = [_responder_from(raw) for raw in state.get("responders", [])]
        routes = _routes_from(state.get("plan", {}))

        rationale, method = await plan_rules.write_rationale(scores, by_id, call=call)

        plan_id = str(uuid7())
        assembled = plan_rules.assemble(
            plan_id=plan_id,
            scores=scores,
            incidents=by_id,
            responders=crews,
            routes=routes,
            rationale=rationale,
            rationale_method=method,
            proposed_at=clock(),
        )

        stored_id = await store.propose(
            incident_ids=assembled.incident_ids,
            responder_ids=assembled.responder_ids,
            route=assembled.as_route_column(),
            estimated_duration_min=assembled.eta,
            thread_id=str(state.get("thread_id", "")),
            correlation_id=str(state.get("correlation_id", "")),
        )

        _log.info(
            "triage_plan_proposed",
            plan_id=stored_id,
            incidents=len(assembled.incident_ids),
            responders=len(assembled.responder_ids),
            unservable=len(routes.unservable),
            eta_min=assembled.eta,
            rationale=method,
        )
        return {
            "plan_id": stored_id,
            "plan": {
                **dict(state.get("plan", {})),
                **assembled.as_interrupt_payload(),
                "plan_id": stored_id,
            },
            "notes": [f"plan {stored_id} proposed ({method} rationale)"],
        }

    async def dispatch_signoff(state: TriageState) -> dict[str, Any]:
        """The mandatory human gate.

        **This node re-executes from the top when the run resumes.** Everything above the
        `interrupt()` call runs a second time, so nothing above it may have a side effect
        that is not idempotent — and there is deliberately nothing above it but reading
        state. The plan was written by `assemble_plan`, upstream; the release is recorded by
        `release`, downstream. Both are separate nodes for exactly that reason.

        The payload is the approval screen's contract. Everything a dispatcher needs is in
        it, including the unservable list and the factor breakdown, because a gate where the
        person cannot see why is a rubber stamp rather than a control.
        """
        payload = dict(state.get("plan", {}))

        decision = request_approval(
            state,
            question="Release this dispatch plan?",
            detail=payload,
        )

        # Below the interrupt. Runs exactly once.
        approved = bool(decision.get("approved"))
        _log.info(
            "triage_dispatch_decided",
            plan_id=state.get("plan_id"),
            approved=approved,
            decided_by=str(decision.get("decided_by")),
            reason=decision.get("reason"),
        )
        return {"human_decision": decision, "notes": ["dispatcher decided"]}

    async def release(state: TriageState) -> dict[str, Any]:
        """Record the release and emit. Never decides anything.

        Calls a gated tool, which refuses without a human decision naming this plan. That
        refusal is the layer inside this service; three more sit outside it, and the
        decision itself was made by `dispatch_gate.approve` before this graph was resumed.
        """
        plan_id = str(state.get("plan_id", ""))
        decision = state.get("human_decision") or {}

        await TOOLS.invoke(
            "release_dispatch_plan", state, store=store, plan_id=plan_id, decision=decision
        )

        observations = [
            {
                "subject_type": "incident",
                "subject_id": incident_id,
                "observation": "dispatch_released",
                "value": plan_id,
                "confidence": 1.0,
                "source": f"{AGENT}:human",
            }
            for incident_id in state.get("plan", {}).get("served", [])
        ]
        return {
            "released": True,
            "observations": observations,
            "notes": [f"plan {plan_id} released by {decision.get('decided_by', 'a dispatcher')}"],
        }

    async def record_rejection(state: TriageState) -> dict[str, Any]:
        """Record why the plan was turned down, and re-queue.

        The most valuable data the platform produces. A rejection is a dispatcher telling
        us the ranking was wrong in a situation where they know something we do not, and
        treating it as an error path would throw that away.
        """
        plan_id = str(state.get("plan_id", ""))
        decision = state.get("human_decision") or {}
        recorded = rejections.record(decision, plan_id=plan_id)

        await store.record_rejection(
            plan_id,
            reason=recorded.reason,
            note=recorded.note,
            decided_by=str(decision.get("decided_by", "")),
        )

        _log.info(
            "triage_plan_rejected",
            plan_id=plan_id,
            reason=recorded.reason,
            requeued=len(state.get("plan", {}).get("served", [])),
        )
        return {
            "released": False,
            "rejection": recorded.as_dict(),
            "observations": recorded.observations(
                state.get("plan", {}).get("served", []), agent=AGENT
            ),
            "notes": [f"plan {plan_id} rejected: {recorded.reason}; incidents re-queued"],
        }

    async def record(state: TriageState) -> dict[str, Any]:
        """Append the observations, write the audit entry, and finish."""
        await rg_append(state, observations=state.get("observations", []), writer=graph_writer)

        released = bool(state.get("released"))
        decision = state.get("human_decision") or {}
        rejection = dict(state.get("rejection", {}))

        audited = await audit_write(
            state,
            action="triage.dispatch.released" if released else "triage.dispatch.rejected",
            subject=str(state.get("plan_id", "")),
            detail={
                "district": state.get("district_code"),
                "incidents": len(state.get("plan", {}).get("served", [])),
                "responders": len(state.get("responders", [])),
                "unservable": len(state.get("plan", {}).get("unservable", [])),
                "routing_method": state.get("plan", {}).get("method"),
                "estimated_duration_min": state.get("plan", {}).get("estimated_duration_min"),
                "decided_by": decision.get("decided_by"),
                "released": released,
                "rejection_reason": rejection.get("reason"),
            },
            writer=audit,
        )

        return {
            **audited,
            "status": "COMPLETED",
            "output": {
                "plan_id": state.get("plan_id"),
                "released": released,
                "district_code": state.get("district_code"),
                "incidents_planned": len(state.get("plan", {}).get("served", [])),
                "unservable": state.get("plan", {}).get("unservable", []),
                "routing_method": state.get("plan", {}).get("method"),
                "estimated_duration_min": state.get("plan", {}).get("estimated_duration_min"),
                "rejection_reason": rejection.get("reason"),
                "decided_by": decision.get("decided_by"),
                "confidence": 1.0,
                "reasoning": (
                    "a dispatcher released this plan"
                    if released
                    else f"a dispatcher rejected this plan: {rejection.get('reason', 'unknown')}"
                ),
                "needs_human_review": False,
                # A person decided. Never DETERMINISTIC and never MODEL: the record has to
                # say a human made this call, because that is the whole point of the gate.
                "provenance": "HUMAN",
            },
        }

    return {
        "receive": receive,
        "score_priority": score_priority,
        "rank_queue": rank_queue,
        "check_resources": check_resources,
        "compute_routes": compute_routes,
        "assemble_plan": assemble_plan,
        "dispatch_signoff": dispatch_signoff,
        "release": release,
        "record_rejection": record_rejection,
        "record": record,
    }


# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------


def _minutes_since(value: Any, now: datetime) -> float:
    moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    if moment is None:
        return 0.0
    return max(0.0, (now - moment).total_seconds() / 60.0)


def _incident_as_dict(incident: Incident) -> dict[str, Any]:
    return {
        "incident_id": incident.incident_id,
        "incident_type": incident.incident_type,
        "gn_division_code": incident.gn_division_code,
        "first_reported_at": incident.first_reported_at.isoformat(),
        "lon": incident.lon,
        "lat": incident.lat,
        "location_confidence": incident.location_confidence,
        "people_at_risk": incident.people_at_risk,
        "vulnerable_present": list(incident.vulnerable_present),
        "immediate_danger": incident.immediate_danger,
        "corroboration_count": incident.corroboration_count,
        "road_access_lost": incident.road_access_lost,
        "access_feasibility": incident.access_feasibility,
    }


def _incident_from(raw: dict[str, Any]) -> Incident:
    reported = raw["first_reported_at"]
    return Incident(
        incident_id=raw["incident_id"],
        incident_type=raw["incident_type"],
        gn_division_code=raw["gn_division_code"],
        first_reported_at=(
            datetime.fromisoformat(reported) if isinstance(reported, str) else reported
        ),
        lon=raw.get("lon"),
        lat=raw.get("lat"),
        location_confidence=float(raw.get("location_confidence", 1.0)),
        people_at_risk=raw.get("people_at_risk"),
        vulnerable_present=tuple(raw.get("vulnerable_present", [])),
        immediate_danger=bool(raw.get("immediate_danger")),
        corroboration_count=int(raw.get("corroboration_count", 1)),
        road_access_lost=bool(raw.get("road_access_lost")),
        access_feasibility=float(raw.get("access_feasibility", 1.0)),
    )


def _responder_as_dict(responder: Responder) -> dict[str, Any]:
    return {
        "responder_id": responder.responder_id,
        "org": responder.org,
        "responder_type": responder.responder_type,
        "capacity": responder.capacity,
        "lon": responder.lon,
        "lat": responder.lat,
        "status": responder.status,
        "home_gn_division_code": responder.home_gn_division_code,
    }


def _responder_from(raw: dict[str, Any]) -> Responder:
    return Responder(
        responder_id=raw["responder_id"],
        org=raw["org"],
        responder_type=raw["responder_type"],
        capacity=int(raw["capacity"]),
        lon=raw.get("lon"),
        lat=raw.get("lat"),
        status=raw.get("status", "AVAILABLE"),
        home_gn_division_code=raw.get("home_gn_division_code"),
    )


def _score_as_dict(score: scoring.TriageScore) -> dict[str, Any]:
    return {
        "incident_id": score.incident_id,
        "score": score.score,
        "dispatchability": score.dispatchability,
        "dispatchable": score.dispatchable,
        "factors": score.factors,
        "model_version": score.model_version,
        "method": score.method,
    }


def _score_from(raw: dict[str, Any]) -> scoring.TriageScore:
    return scoring.TriageScore(
        incident_id=raw["incident_id"],
        score=float(raw["score"]),
        dispatchability=float(raw["dispatchability"]),
        factors=dict(raw.get("factors", {})),
        model_version=str(raw.get("model_version", scoring.MODEL_VERSION)),
        method=str(raw.get("method", scoring.METHOD)),
    )


def _routes_from(raw: dict[str, Any]) -> Any:
    """Rebuild the route plan from state, for the assembly node."""
    from agent_svc.agents.triage.ports import Route, RoutePlan, Stop, Unservable

    return RoutePlan(
        routes=[
            Route(
                responder_id=route["responder_id"],
                stops=[
                    Stop(
                        incident_id=stop["incident_id"],
                        sequence=int(stop["sequence"]),
                        eta_minutes=float(stop["eta_minutes"]),
                    )
                    for stop in route.get("stops", [])
                ],
                total_minutes=float(route.get("total_minutes", 0.0)),
            )
            for route in raw.get("routes", [])
        ],
        unservable=[
            Unservable(
                incident_id=item["incident_id"],
                reason=item["reason"],
                detail=item["detail"],
            )
            for item in raw.get("unservable", [])
        ],
        method=str(raw.get("method", routing_rules.METHOD_GREEDY)),
        solver_status=str(raw.get("solver_status", "")),
    )


# ---------------------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------------------


def _after_resources(state: TriageState) -> str:
    """Nothing to plan is a completed run, not an empty gate.

    Putting an empty plan in front of a dispatcher trains them to approve without looking,
    which is precisely how a gate stops being one.
    """
    if not state.get("responders") or not state.get("incidents"):
        return "end"
    return "compute_routes"


def _after_signoff(state: TriageState) -> str:
    decision = state.get("human_decision") or {}
    return "release" if decision.get("approved") else "record_rejection"


def build(
    checkpointer: Any,
    *,
    incidents: IncidentSource | None = None,
    responders: ResponderSource | None = None,
    store: PlanStore | None = None,
    solver: RouteSolver | None = None,
    model: scoring.TriageModel | None = None,
    call: ModelCall | None = None,
    now: datetime | None = None,
    time_limit_s: float = routing_rules.DEFAULT_TIME_LIMIT_S,
    audit: Any = None,
    graph_writer: Any = None,
) -> Any:
    """Compile the graph.

    The three sources are optional so `AgentRegistry.compile_all` can build this at boot the
    same way it builds every other agent. A graph without them refuses at the node that
    needs one, rather than proposing an empty plan — which a dispatcher would read as a
    quiet night.
    """
    nodes = build_nodes(
        incidents=incidents or _RefusingIncidents(),
        responders=responders or _RefusingResponders(),
        store=store or _RefusingStore(),
        solver=solver,
        model=model,
        call=call,
        now=now,
        time_limit_s=time_limit_s,
        audit=audit,
        graph_writer=graph_writer,
    )

    builder = StateGraph(TriageState)
    for name, node in nodes.items():
        builder.add_node(name, node)

    builder.add_edge(START, "receive")
    builder.add_edge("receive", "score_priority")
    builder.add_edge("score_priority", "rank_queue")
    builder.add_edge("rank_queue", "check_resources")
    builder.add_conditional_edges(
        "check_resources", _after_resources, {"compute_routes": "compute_routes", "end": END}
    )
    builder.add_edge("compute_routes", "assemble_plan")
    builder.add_edge("assemble_plan", "dispatch_signoff")
    builder.add_conditional_edges(
        "dispatch_signoff",
        _after_signoff,
        {"release": "release", "record_rejection": "record_rejection"},
    )
    builder.add_edge("release", "record")
    builder.add_edge("record_rejection", "record")
    builder.add_edge("record", END)

    return builder.compile(checkpointer=checkpointer)


class _RefusingIncidents:
    """Stands in when incident-svc is unreachable. Refuses loudly.

    An empty queue and an unreachable database produce the same empty plan and mean
    opposite things, and only one of them means everybody has been rescued.
    """

    async def open_incidents(self, *, district_code: str | None = None) -> Any:
        raise RuntimeError(
            "The triage agent has no incident source configured. An empty queue and an "
            "unreachable one look identical from a plan, and only one of them means "
            "everybody has been rescued."
        )


class _RefusingResponders:
    """Stands in when the responder roster is unreachable."""

    async def available(self, *, district_code: str | None = None) -> Any:
        raise RuntimeError(
            "The triage agent cannot read the responder roster, so it cannot know who is "
            "available. It refuses rather than proposing a plan with nobody in it."
        )


class _RefusingStore:
    """Stands in when there is nowhere to write a plan."""

    async def propose(self, **kwargs: Any) -> Any:
        raise RuntimeError(
            "The triage agent has no plan store configured, so this plan was never written. "
            "A gate over a plan that does not exist is not a gate."
        )

    async def record_rejection(self, plan_id: str, **kwargs: Any) -> None:
        raise RuntimeError("The triage agent has no plan store configured.")


def _eval_build(checkpointer: Any) -> Any:
    """Imported lazily so the production graph does not depend on the eval one."""
    from agent_svc.agents.triage.evaluation import build as build_eval

    return build_eval(checkpointer)


SPEC: Final = AgentSpec(
    name=AGENT,
    subject_type=SUBJECT_TYPE,
    build=build,
    description=(
        "Ranks open incidents on a published weighted formula, assigns responders and "
        "sequences routes, then stops: a named dispatcher with a fresh second factor "
        "releases the plan, and the agent never can."
    ),
    degraded_note=(
        "Scoring, ranking, resource checking and routing reach no model at all, so a "
        "provider outage leaves the queue and the routes byte-identical and only the "
        "trilingual rationale becomes plainer - it falls back to a template rendered from "
        "the same factors. Without OR-Tools, routing falls back to a nearest-available "
        "greedy assignment which is worse and is labelled as such on the plan. A total "
        "model outage is close to a non-event for this agent."
    ),
    gated=True,
    eval_build=_eval_build,
)
