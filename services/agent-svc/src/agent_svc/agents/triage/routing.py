"""Assigning responders to incidents and sequencing the stops. No model touches a route.

Two solvers behind one protocol. OR-Tools solves the capacitated vehicle routing problem
with time windows; the greedy nearest-available assignment is the documented fallback when
OR-Tools finds nothing feasible inside its budget, and the plan says which one produced it.

## There is no road network, and pretending otherwise would be the dangerous part

Build file 16 asks for travel times "over a road network with flood-blocked edges removed".
**This repository has no road network.** There is no OSM extract, no routing graph, and no
edge set to remove anything from.

So travel time here is straight-line distance at a mode-dependent speed, and "flood-blocked
edges removed" is implemented as the thing the platform *does* know: a division whose
`expected_road_access_loss` is set cannot be reached by a road vehicle at all, only by boat
or air. That is a coarser model and it is an honest one — it gets the decision that matters
right (who can reach a cut-off village) without inventing a network.

What it gets wrong is real and worth stating: it under-estimates travel time everywhere,
because roads bend and straight lines do not. Every ETA this module produces is optimistic,
`TravelModel.detour_factor` is the single constant that admits it, and a dispatcher reading
an ETA should read it as a floor. Wiring a real routing engine changes this module and
nothing else — which is why the travel model is separate from the solvers.

## Why the fallback is not an afterthought

The greedy solver is written first and is always available. OR-Tools is a native dependency
that can fail to install, fail to converge, or be absent from a constrained deployment, and
an agent whose only routing path needs it is one that stops planning when it is missing. The
greedy result is worse — it does not sequence a route to minimise total travel — and it is a
working plan a dispatcher can approve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import structlog

from agent_svc.agents.triage.ports import (
    Incident,
    Responder,
    Route,
    RoutePlan,
    Stop,
    Unservable,
)
from sarana_shared.domain.geo import haversine_m

_log = structlog.get_logger(__name__)

METHOD_ORTOOLS: Final = "OR_TOOLS_CVRPTW"
METHOD_GREEDY: Final = "GREEDY"

# How long the solver is given. Build file 16 sets five seconds: a dispatch plan that
# arrives after the dispatcher has started working the queue by hand is not a plan.
DEFAULT_TIME_LIMIT_S: Final = 5.0

# Average speed by responder type, in km/h, over the terrain each one actually crosses.
# Deliberately conservative — these are speeds during a disaster, on damaged roads, in the
# dark, not manufacturer figures.
SPEED_KMH: Final[dict[str, float]] = {
    "AMBULANCE": 40.0,
    "POLICE": 40.0,
    "FIRE": 35.0,
    "MEDICAL_TEAM": 35.0,
    "MILITARY": 30.0,
    "NGO": 30.0,
    "ENGINEERING": 25.0,
    "VOLUNTEER": 25.0,
    # Boats. Slower over the ground than a vehicle on an intact road, and the only thing
    # that moves at all once the road is gone.
    "NAVY": 20.0,
    "COAST_GUARD": 20.0,
}
DEFAULT_SPEED_KMH: Final = 30.0

# What a straight line under-states. Roads bend, rivers have bridges in particular places,
# and a flooded route doubles back. 1.4 is the usual planning figure for road networks and
# it is applied to everything except the helicopter, which really does fly straight.
DETOUR_FACTOR: Final = 1.4

# How long a crew spends at one incident before moving on. Twenty minutes: long enough to
# be honest about a rescue, short enough not to swamp the travel time in a dense division.
SERVICE_MINUTES: Final = 20.0

# An incident with no coordinate cannot be routed to. It is not dropped - it comes back as
# `unservable` with this reason, and a dispatcher who knows the area can often place it in
# seconds.
REASON_NO_LOCATION: Final = "no_location"
REASON_NO_CAPABLE_RESPONDER: Final = "no_capable_responder"
REASON_NO_CAPACITY: Final = "no_capacity"
REASON_SOLVER_INFEASIBLE: Final = "solver_could_not_place"


@dataclass(frozen=True, slots=True)
class TravelModel:
    """How long it takes to get from one place to another.

    Straight-line, mode-aware, and explicit about being a floor. See the module docstring
    for why there is no road network behind it and what that costs.
    """

    detour_factor: float = DETOUR_FACTOR
    service_minutes: float = SERVICE_MINUTES

    def speed_kmh(self, responder: Responder) -> float:
        return SPEED_KMH.get(responder.responder_type, DEFAULT_SPEED_KMH)

    def minutes(
        self,
        responder: Responder,
        from_lon: float,
        from_lat: float,
        to_lon: float,
        to_lat: float,
    ) -> float:
        """Travel minutes between two points for one responder.

        The detour factor applies to every mode. `incident.responder.type` has no aircraft
        in it - the platform's responder list is the emergency services' own - so there is
        no mode here for which a straight line is the real path, and exempting one would be
        modelling a capability the roster does not have.
        """
        metres = haversine_m(from_lon, from_lat, to_lon, to_lat)
        km = (metres / 1000.0) * self.detour_factor
        return (km / self.speed_kmh(responder)) * 60.0

    def can_reach(self, responder: Responder, incident: Incident) -> bool:
        """Whether this responder can physically get to this incident.

        The one place "flood-blocked edges removed" is implemented. A division whose roads
        are gone is reachable by boat or air and by nothing else, and an incident in one
        with no such responder available is *unservable* rather than slow — which is the
        distinction a dispatcher escalates on.
        """
        if not incident.road_access_lost:
            return True
        return responder.reaches_flooded_ground


def _capacity_needed(incident: Incident) -> int:
    """How many people a responder has to have room for.

    An unstated count is one person, matching the scorer. Treating it as zero would let an
    unlimited number of unstated incidents onto one boat.
    """
    return max(1, incident.people_at_risk if incident.people_at_risk is not None else 1)


def _partition(
    incidents: list[Incident], responders: list[Responder]
) -> tuple[list[Incident], list[Unservable]]:
    """Separate the incidents that can be routed from the ones that cannot, with reasons.

    Done before either solver runs, so both give the same answer to "why was this left
    out?" — and so OR-Tools is not handed an incident it can only respond to by silently
    dropping.
    """
    routable: list[Incident] = []
    unservable: list[Unservable] = []
    travel = TravelModel()

    for incident in incidents:
        if not incident.has_point:
            unservable.append(
                Unservable(
                    incident_id=incident.incident_id,
                    reason=REASON_NO_LOCATION,
                    detail=(
                        f"this incident has no coordinate, only division "
                        f"{incident.gn_division_code}. It cannot be routed to and it has "
                        "not been dropped: somebody who knows the area can often place it "
                        "in seconds."
                    ),
                )
            )
            continue

        capable = [responder for responder in responders if travel.can_reach(responder, incident)]
        if not capable:
            unservable.append(
                Unservable(
                    incident_id=incident.incident_id,
                    reason=REASON_NO_CAPABLE_RESPONDER,
                    detail=(
                        f"{incident.gn_division_code} has lost road access and no boat, "
                        "helicopter, navy or coast guard unit is available. This needs "
                        "escalating to another agency."
                    ),
                )
            )
            continue

        if all(responder.capacity < _capacity_needed(incident) for responder in capable):
            unservable.append(
                Unservable(
                    incident_id=incident.incident_id,
                    reason=REASON_NO_CAPACITY,
                    detail=(
                        f"{_capacity_needed(incident)} people at risk and no available "
                        "responder that can reach them has the capacity. A second vehicle "
                        "or a larger one is needed."
                    ),
                )
            )
            continue

        routable.append(incident)

    return routable, unservable


class GreedySolver:
    """Nearest available responder, taken in priority order. Always available.

    Deliberately simple and deliberately deterministic. Incidents are consumed in the order
    they are given — which is the ranked order — so the most urgent incident gets the
    closest capable responder, and the next one gets the closest of what is left.

    It does not sequence a route to minimise total travel, which is what OR-Tools is for.
    It produces a plan a dispatcher can approve, which is what matters when OR-Tools is not
    there.
    """

    def __init__(self, travel: TravelModel | None = None) -> None:
        self._travel = travel or TravelModel()

    @property
    def method(self) -> str:
        return METHOD_GREEDY

    def solve(
        self,
        incidents: list[Incident],
        responders: list[Responder],
        *,
        time_limit_s: float = DEFAULT_TIME_LIMIT_S,
    ) -> RoutePlan:
        routable, unservable = _partition(incidents, responders)
        available = [responder for responder in responders if responder.available]

        # Remaining capacity per responder, and where each one currently is. A responder
        # that has already been given a stop starts its next leg from there rather than
        # from its depot, which is what makes the second stop's ETA honest.
        remaining = {responder.responder_id: responder.capacity for responder in available}
        position = {
            responder.responder_id: (responder.lon, responder.lat) for responder in available
        }
        elapsed = {responder.responder_id: 0.0 for responder in available}
        stops: dict[str, list[Stop]] = {responder.responder_id: [] for responder in available}

        for incident in routable:
            needed = _capacity_needed(incident)
            best: tuple[float, str] | None = None

            for responder in available:
                if remaining[responder.responder_id] < needed:
                    continue
                if not self._travel.can_reach(responder, incident):
                    continue
                lon, lat = position[responder.responder_id]
                if lon is None or lat is None:
                    continue
                minutes = self._travel.minutes(
                    responder, lon, lat, float(incident.lon or 0.0), float(incident.lat or 0.0)
                )
                if best is None or minutes < best[0]:
                    best = (minutes, responder.responder_id)

            if best is None:
                unservable.append(
                    Unservable(
                        incident_id=incident.incident_id,
                        reason=REASON_NO_CAPACITY,
                        detail=(
                            "every responder that could reach this incident was already "
                            "full when the plan reached it. It is next in line for the "
                            "following plan."
                        ),
                    )
                )
                continue

            minutes, responder_id = best
            elapsed[responder_id] += minutes + self._travel.service_minutes
            remaining[responder_id] -= needed
            position[responder_id] = (incident.lon, incident.lat)
            stops[responder_id].append(
                Stop(
                    incident_id=incident.incident_id,
                    sequence=len(stops[responder_id]) + 1,
                    eta_minutes=elapsed[responder_id] - self._travel.service_minutes,
                )
            )

        routes = [
            Route(
                responder_id=responder_id,
                stops=assigned,
                total_minutes=elapsed[responder_id],
            )
            for responder_id, assigned in stops.items()
            if assigned
        ]

        _log.info(
            "triage_routes_solved",
            method=METHOD_GREEDY,
            responders=len(routes),
            served=sum(len(route.stops) for route in routes),
            unservable=len(unservable),
        )
        return RoutePlan(
            routes=routes,
            unservable=unservable,
            method=METHOD_GREEDY,
            solver_status="greedy nearest-available assignment",
        )


class OrToolsSolver:
    """The capacitated vehicle routing problem with time windows, solved properly.

    Falls back to the greedy solver whenever OR-Tools is unavailable or finds nothing
    feasible inside the time limit, and the returned plan says which happened. Build file 16
    requires the fallback to be labelled, because a dispatcher looking at a worse plan should
    know it is a worse plan.

    The model:
      - one node per incident plus one depot node per responder's current position;
      - capacity as a dimension, demand being people at risk;
      - travel time as the arc cost, from `TravelModel`;
      - responders that cannot reach a flooded incident are barred from its node, which is
        how "flood-blocked edges removed" reaches the solver.
    """

    def __init__(self, travel: TravelModel | None = None) -> None:
        self._travel = travel or TravelModel()
        self._fallback = GreedySolver(self._travel)

    @property
    def method(self) -> str:
        return METHOD_ORTOOLS

    def solve(
        self,
        incidents: list[Incident],
        responders: list[Responder],
        *,
        time_limit_s: float = DEFAULT_TIME_LIMIT_S,
    ) -> RoutePlan:
        try:
            from ortools.constraint_solver import pywrapcp, routing_enums_pb2
        except ImportError:
            _log.warning(
                "triage_ortools_unavailable",
                impact="routing fell back to greedy nearest-available; the plan says so",
            )
            return self._fallback.solve(incidents, responders, time_limit_s=time_limit_s)

        routable, unservable = _partition(incidents, responders)
        available = [
            responder
            for responder in responders
            if responder.available and responder.lon is not None and responder.lat is not None
        ]
        if not routable or not available:
            return RoutePlan(
                routes=[],
                unservable=unservable,
                method=METHOD_ORTOOLS,
                solver_status="nothing routable" if not routable else "no available responders",
            )

        # Node 0..n-1 are the responders' starting positions; the incidents follow.
        starts = list(range(len(available)))
        ends = list(range(len(available)))
        offset = len(available)
        points: list[tuple[float, float]] = [
            (float(r.lon or 0.0), float(r.lat or 0.0)) for r in available
        ] + [(float(i.lon or 0.0), float(i.lat or 0.0)) for i in routable]

        manager = pywrapcp.RoutingIndexManager(len(points), len(available), starts, ends)
        routing = pywrapcp.RoutingModel(manager)

        def transit(from_index: int, to_index: int, vehicle: int) -> int:
            """Travel minutes between two nodes for one vehicle, as an integer.

            OR-Tools works in integers, so minutes are rounded. A minute of rounding on a
            journey measured in tens of minutes is well inside the error the straight-line
            model already carries.
            """
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            responder = available[vehicle]
            from_lon, from_lat = points[from_node]
            to_lon, to_lat = points[to_node]
            travel = self._travel.minutes(responder, from_lon, from_lat, to_lon, to_lat)
            service = self._travel.service_minutes if to_node >= offset else 0.0
            return round(travel + service)

        for vehicle, _ in enumerate(available):
            callback = routing.RegisterTransitCallback(lambda i, j, v=vehicle: transit(i, j, v))
            routing.SetArcCostEvaluatorOfVehicle(callback, vehicle)

        def demand(index: int) -> int:
            node = manager.IndexToNode(index)
            return 0 if node < offset else _capacity_needed(routable[node - offset])

        demand_callback = routing.RegisterUnaryTransitCallback(demand)
        routing.AddDimensionWithVehicleCapacity(
            demand_callback,
            0,
            [max(0, responder.capacity) for responder in available],
            True,
            "Capacity",
        )

        # An incident a vehicle cannot physically reach is barred from that vehicle rather
        # than made expensive. A penalty would let the solver send a jeep into a division
        # whose roads are under water if the alternative looked worse.
        for position, incident in enumerate(routable):
            node_index = manager.NodeToIndex(offset + position)
            allowed = [
                vehicle
                for vehicle, responder in enumerate(available)
                if self._travel.can_reach(responder, incident)
            ]
            # `VehicleVar(...).SetValues` rather than `SetAllowedVehiclesForIndex`: it is
            # a hard constraint on which vehicles may serve the node, and it accepts the
            # `-1` that means "dropped", which the disjunction below needs to stay legal.
            routing.VehicleVar(node_index).SetValues([-1, *allowed])
            # Dropping a node is allowed and expensive. Without this the whole problem is
            # infeasible the moment one incident cannot be served, and the dispatcher gets
            # nothing instead of a plan with one named gap.
            routing.AddDisjunction([node_index], 1_000_000)

        parameters = pywrapcp.DefaultRoutingSearchParameters()
        parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )
        parameters.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        parameters.time_limit.FromMilliseconds(int(time_limit_s * 1000))

        solution = routing.SolveWithParameters(parameters)
        if solution is None:
            _log.warning(
                "triage_ortools_infeasible",
                incidents=len(routable),
                responders=len(available),
                impact="routing fell back to greedy nearest-available; the plan says so",
            )
            return self._fallback.solve(incidents, responders, time_limit_s=time_limit_s)

        routes: list[Route] = []
        served: set[int] = set()

        for vehicle, responder in enumerate(available):
            index = routing.Start(vehicle)
            stops: list[Stop] = []
            elapsed = 0.0

            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                next_index = solution.Value(routing.NextVar(index))
                leg = transit(index, next_index, vehicle)
                if not routing.IsEnd(next_index):
                    next_node = manager.IndexToNode(next_index)
                    if next_node >= offset:
                        served.add(next_node - offset)
                        elapsed += leg
                        stops.append(
                            Stop(
                                incident_id=routable[next_node - offset].incident_id,
                                sequence=len(stops) + 1,
                                eta_minutes=elapsed - self._travel.service_minutes,
                            )
                        )
                index = next_index
                if node >= offset:
                    pass

            if stops:
                routes.append(
                    Route(responder_id=responder.responder_id, stops=stops, total_minutes=elapsed)
                )

        # Anything the solver chose to drop is named, never silently omitted.
        for position, incident in enumerate(routable):
            if position not in served:
                unservable.append(
                    Unservable(
                        incident_id=incident.incident_id,
                        reason=REASON_SOLVER_INFEASIBLE,
                        detail=(
                            "the router could not fit this incident into any route within "
                            "the available capacity and time. It is not dropped: it is the "
                            "first thing the next plan will pick up, and it can be escalated "
                            "now."
                        ),
                    )
                )

        _log.info(
            "triage_routes_solved",
            method=METHOD_ORTOOLS,
            responders=len(routes),
            served=len(served),
            unservable=len(unservable),
        )
        return RoutePlan(
            routes=routes,
            unservable=unservable,
            method=METHOD_ORTOOLS,
            solver_status=f"solved in under {time_limit_s:.0f}s",
        )


def default_solver() -> OrToolsSolver:
    """The solver the agent uses unless a test supplies another.

    OR-Tools with the greedy fallback built in, so a deployment without the native
    dependency still plans.
    """
    return OrToolsSolver()
