"""Fakes for the triage agent's four ports, and the geometry the routing tests use.

The coordinates are real places in Kandy district, spaced so travel times between them are
distinguishable — a routing test over three points a hundred metres apart cannot tell a good
sequence from a bad one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agent_svc.agents.triage.ports import Incident, Responder

# Ditwah's landfall night, pinned so ageing is testable.
NOW = datetime(2026, 11, 28, 4, 0, tzinfo=UTC)

DIVISION = "LK-21-01-001"
FAR_DIVISION = "LK-21-01-009"

# Kandy district, roughly 10-25 km apart.
GAMPOLA = (80.5714, 7.1642)
PERADENIYA = (80.5977, 7.2599)
KANDY = (80.6337, 7.2906)
DELTOTA = (80.7000, 7.1500)


def incident(
    incident_id: str,
    *,
    incident_type: str = "FLOOD",
    minutes_ago: float = 0.0,
    people: int | None = 2,
    danger: bool = False,
    vulnerable: tuple[str, ...] = (),
    at: tuple[float, float] | None = GAMPOLA,
    division: str = DIVISION,
    road_access_lost: bool = False,
    location_confidence: float = 1.0,
    corroboration: int = 1,
) -> Incident:
    return Incident(
        incident_id=incident_id,
        incident_type=incident_type,
        gn_division_code=division,
        first_reported_at=NOW - timedelta(minutes=minutes_ago),
        lon=at[0] if at else None,
        lat=at[1] if at else None,
        location_confidence=location_confidence,
        people_at_risk=people,
        vulnerable_present=vulnerable,
        immediate_danger=danger,
        corroboration_count=corroboration,
        road_access_lost=road_access_lost,
        access_feasibility=0.2 if road_access_lost else 1.0,
    )


def responder(
    responder_id: str,
    *,
    responder_type: str = "MEDICAL_TEAM",
    capacity: int = 8,
    at: tuple[float, float] = KANDY,
    status: str = "AVAILABLE",
    org: str = "DMC",
) -> Responder:
    return Responder(
        responder_id=responder_id,
        org=org,
        responder_type=responder_type,
        capacity=capacity,
        lon=at[0],
        lat=at[1],
        status=status,
    )


@dataclass
class FakeIncidents:
    queue: list[Incident] = field(default_factory=list)
    asked: list[str | None] = field(default_factory=list)

    async def open_incidents(self, *, district_code: str | None = None) -> list[Incident]:
        self.asked.append(district_code)
        return list(self.queue)


@dataclass
class FakeResponders:
    crews: list[Responder] = field(default_factory=list)

    async def available(self, *, district_code: str | None = None) -> list[Responder]:
        return [crew for crew in self.crews if crew.available]


@dataclass
class FakePlanStore:
    """Records what was proposed and what was rejected.

    Deliberately has no way to release anything: the agent has no such port, and a fake
    that offered one would let a test pass that the real system would refuse.
    """

    proposed: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    next_id: str = "plan-1"

    async def propose(self, **kwargs: Any) -> str:
        self.proposed.append(dict(kwargs))
        return self.next_id

    async def record_rejection(
        self, plan_id: str, *, reason: str, note: str | None, decided_by: str
    ) -> None:
        self.rejected.append(
            {"plan_id": plan_id, "reason": reason, "note": note, "decided_by": decided_by}
        )


class RecordingCall:
    """A model stand-in answering with a fixed string, remembering the prompts."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answer


class BrokenCall:
    """A model provider that is down. This agent must be near-unaffected."""

    async def __call__(self, prompt: str) -> str:
        raise ConnectionError("the model provider is unreachable")


@pytest.fixture
def store() -> FakePlanStore:
    return FakePlanStore()
