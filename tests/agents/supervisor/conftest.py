"""Fakes for the supervisor.

`FakeApprovals` is the interesting one: it is the database, and every test about the gates is
really a test about what happens when the resume payload and the database disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agent_svc.agents.supervisor.gates import ApprovalRecord

NOW = datetime(2026, 11, 28, 4, 0, tzinfo=UTC)

SUBJECT = "plan-1"
APPROVER = "dispatcher-7"


def approval(
    *,
    gate: str = "dispatch_signoff",
    subject_id: str = SUBJECT,
    approved: bool = True,
    approver_id: str = APPROVER,
    step_up_minutes_ago: float | None = 1.0,
) -> ApprovalRecord:
    return ApprovalRecord(
        gate=gate,
        subject_id=subject_id,
        approved=approved,
        approver_id=approver_id,
        decided_at=NOW,
        step_up_at=(
            None if step_up_minutes_ago is None else NOW - timedelta(minutes=step_up_minutes_ago)
        ),
    )


@dataclass
class FakeApprovals:
    """The database, as the gate sees it.

    `records` is what really happened; a resume payload can claim anything, and the whole
    point of the gate is that these two are compared.
    """

    records: dict[tuple[str, str], ApprovalRecord] = field(default_factory=dict)
    facts: dict[str, set[str]] = field(default_factory=dict)
    lookups: list[tuple[str, str]] = field(default_factory=list)

    async def approval_for(self, gate: str, subject_id: str) -> ApprovalRecord | None:
        self.lookups.append((gate, subject_id))
        return self.records.get((gate, subject_id))

    async def facts_for(self, subject_id: str) -> set[str]:
        return set(self.facts.get(subject_id, set()))


@dataclass
class RecordingStarter:
    """Watches what the supervisor would have started."""

    started: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(self, **kwargs: Any) -> None:
        self.started.append(kwargs)


class RecordingCall:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answer


class BrokenCall:
    async def __call__(self, prompt: str) -> str:
        raise ConnectionError("the model provider is unreachable")


# A proposal that is complete and usable: it recommends and it states the counter-case.
GOOD_PROPOSAL = (
    '{"recommended": "B", "rationale": "The responder saw two separate buildings.", '
    '"why_the_other_might_be_right": "The embeddings matched closely and the two reports '
    'give the same street name, so one household may have reported twice.", '
    '"confidence": 0.7}'
)


@pytest.fixture
def approvals() -> FakeApprovals:
    return FakeApprovals()
