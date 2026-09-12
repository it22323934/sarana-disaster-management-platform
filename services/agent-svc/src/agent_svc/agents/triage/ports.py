"""What the triage graph needs from the outside world, as narrow protocols.

Four ports. The properties this agent has to demonstrate — that a plan cannot reach
RELEASED without a human, that a blocked road changes a route, that an unservable incident
is named rather than dropped, that the graph survives a restart while paused — all have to
be tests, and none of them can depend on a live responder fleet.

## Nothing here can release a dispatch

There is deliberately no port through which this agent can mark a plan RELEASED. It
proposes; `incident_svc.domain.dispatch_gate.approve` releases, after a scope check and a
second factor. The agent's own resume is what un-pauses the graph, and the graph's release
node records what a human already decided rather than deciding it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

# Responder types, mirroring `incident.responder.type`. A type this agent plans with and
# the column rejects would fail at the INSERT, after a dispatcher approved the plan. A test
# asserts the two lists agree.
RESPONDER_TYPES: tuple[str, ...] = (
    "AMBULANCE",
    "FIRE",
    "POLICE",
    "MILITARY",
    "NAVY",
    "COAST_GUARD",
    "VOLUNTEER",
    "NGO",
    "MEDICAL_TEAM",
    "ENGINEERING",
)

# Which responder types can reach a division whose roads are gone. Everything else is a
# vehicle on a road, and a road that is under water is not a road.
#
# This is the single most load-bearing fact in the routing model: it is what makes an
# incident *unservable* rather than merely slow, and an unservable incident is the one a
# dispatcher has to escalate to another agency.
WATER_OR_AIR_CAPABLE: frozenset[str] = frozenset({"NAVY", "COAST_GUARD", "MILITARY"})


@dataclass(frozen=True, slots=True)
class Incident:
    """One open incident, as the planner sees it.

    A projection of `incident.incident` joined to what intake and the forecast know. No
    name, no phone number, no household id — a plan is read in an operations room and goes
    into a checkpoint that outlives the run.
    """

    incident_id: str
    incident_type: str
    gn_division_code: str
    first_reported_at: datetime

    lon: float | None = None
    lat: float | None = None
    location_confidence: float = 1.0

    people_at_risk: int | None = None
    vulnerable_present: tuple[str, ...] = ()
    immediate_danger: bool = False
    corroboration_count: int = 1

    # From the impact forecast for this division. `road_access_lost` is what removes road
    # edges from the routing graph; `access_feasibility` is the softer figure the score
    # reads.
    road_access_lost: bool = False
    access_feasibility: float = 1.0

    @property
    def has_point(self) -> bool:
        return self.lon is not None and self.lat is not None

    def summary(self) -> dict[str, Any]:
        """What the dispatcher's approval screen shows for this incident."""
        return {
            "incident_id": self.incident_id,
            "type": self.incident_type,
            "gn_division_code": self.gn_division_code,
            "people_at_risk": self.people_at_risk,
            "vulnerable_present": list(self.vulnerable_present),
            "immediate_danger": self.immediate_danger,
            "has_point": self.has_point,
            "location_confidence": round(self.location_confidence, 3),
            "road_access_lost": self.road_access_lost,
            "reported_at": self.first_reported_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class Responder:
    """A team or vehicle that can be sent somewhere."""

    responder_id: str
    org: str
    responder_type: str
    capacity: int
    lon: float | None = None
    lat: float | None = None
    status: str = "AVAILABLE"
    home_gn_division_code: str | None = None

    @property
    def available(self) -> bool:
        return self.status == "AVAILABLE"

    @property
    def reaches_flooded_ground(self) -> bool:
        """Whether this responder can get to a division whose roads are gone."""
        return self.responder_type in WATER_OR_AIR_CAPABLE

    def summary(self) -> dict[str, Any]:
        return {
            "responder_id": self.responder_id,
            "org": self.org,
            "type": self.responder_type,
            "capacity": self.capacity,
            "status": self.status,
            "home_gn_division_code": self.home_gn_division_code,
        }


@dataclass(frozen=True, slots=True)
class Unservable:
    """An incident no responder could be routed to, and why.

    Never a silent omission. An unservable incident is critical information for the
    dispatcher — it is the one they escalate to a different agency, and a plan that quietly
    left it out would look complete while somebody waited.
    """

    incident_id: str
    reason: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"incident_id": self.incident_id, "reason": self.reason, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class Stop:
    """One incident on one responder's route."""

    incident_id: str
    sequence: int
    eta_minutes: float


@dataclass(frozen=True, slots=True)
class Route:
    """One responder's assigned sequence of stops."""

    responder_id: str
    stops: list[Stop] = field(default_factory=list)
    total_minutes: float = 0.0

    @property
    def serves(self) -> list[str]:
        return [stop.incident_id for stop in self.stops]


@dataclass(frozen=True, slots=True)
class RoutePlan:
    """What the solver produced: routes, what it could not serve, and how it was solved."""

    routes: list[Route] = field(default_factory=list)
    unservable: list[Unservable] = field(default_factory=list)
    method: str = "GREEDY"
    solver_status: str = ""

    @property
    def served(self) -> list[str]:
        return [incident_id for route in self.routes for incident_id in route.serves]

    @property
    def estimated_duration_min(self) -> int:
        """The longest single route, which is when the last crew gets back.

        The longest rather than the sum: the routes run concurrently, and summing them would
        tell a dispatcher a plan takes six hours when every crew is home in ninety minutes.
        """
        return int(max((route.total_minutes for route in self.routes), default=0.0))

    def route_summary(self) -> list[dict[str, Any]]:
        """What the approval screen renders for the routes."""
        return [
            {
                "responder_id": route.responder_id,
                "stops": [
                    {
                        "incident_id": stop.incident_id,
                        "sequence": stop.sequence,
                        "eta_minutes": round(stop.eta_minutes, 1),
                    }
                    for stop in route.stops
                ],
                "total_minutes": round(route.total_minutes, 1),
            }
            for route in self.routes
        ]


class RouteSolver(Protocol):
    """Assign responders to incidents and sequence the stops.

    Fully deterministic. No model touches a route — a hallucinated stop order sends a crew
    to the wrong village in the wrong order, and nothing downstream would catch it.
    """

    @property
    def method(self) -> str:
        """`OR_TOOLS_CVRPTW` or `GREEDY`. Recorded on the plan and shown to the dispatcher."""
        ...

    def solve(
        self, incidents: list[Incident], responders: list[Responder], *, time_limit_s: float
    ) -> RoutePlan: ...


class IncidentSource(Protocol):
    """The open incidents in scope for this planning run."""

    async def open_incidents(self, *, district_code: str | None = None) -> list[Incident]:
        """Every incident still awaiting a responder, oldest first.

        Raises rather than returning an empty list when the source is unreachable. An empty
        queue and an unreachable database produce the same empty plan and mean opposite
        things, and only one of them means everybody has been rescued.
        """
        ...


class ResponderSource(Protocol):
    """Who is available, where they are, and what they can carry."""

    async def available(self, *, district_code: str | None = None) -> list[Responder]: ...


class PlanStore(Protocol):
    """Where a proposed plan is written, and where a rejection is recorded."""

    async def propose(
        self,
        *,
        incident_ids: list[str],
        responder_ids: list[str],
        route: dict[str, Any],
        estimated_duration_min: int,
        thread_id: str,
        correlation_id: str,
    ) -> str:
        """Write a plan in PROPOSED and return its id.

        PROPOSED and nothing else. There is no argument this agent can pass that produces
        a released plan: `signed_off_by` is written only by `dispatch_gate.approve`, and a
        database trigger rejects RELEASED without it.
        """
        ...

    async def record_rejection(
        self, plan_id: str, *, reason: str, note: str | None, decided_by: str
    ) -> None:
        """Record why a dispatcher turned a plan down.

        The highest-value data the platform produces — see `rejections.py`.
        """
        ...


class ModelCall(Protocol):
    """One model call: a prompt in, text out. Used only for the rationale."""

    async def __call__(self, prompt: str) -> str: ...
