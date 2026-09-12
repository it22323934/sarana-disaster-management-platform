"""The two human gates, one implementation, and the rule that makes it real.

**Do not trust the resume payload.** A resume value is client input. It arrives over HTTP,
it is shaped by whoever called the endpoint, and a graph that reads `decision["approved"]`
and commits has authenticated nothing — it has read a JSON field that said yes.

So `verify_approval_record` goes back to the **database** and checks that a real approval row
exists, for this exact subject, recorded against a principal whose second factor was verified
inside the step-up window. The resume payload is used to find the record, never as the record.

This is where the platform's safety story is either real or theatre. The difference is one
function call.

## Three independent layers, and why each must be tested alone

  1. **Graph** — the `interrupt()`, this module's re-verification, and the gated-tool refusal
     in `runtime.tools`.
  2. **API** — scope, fresh TOTP, and segregation of duty, in incident-svc and ledger-svc.
  3. **Database** — a trigger and `NOT NULL` on `signed_off_by` / `released_by`.

Any one alone is a single point of failure for the platform's core promise, and three layers
that can only be tested through each other are one layer wearing three hats.
`test_gates_three_layers.py` disables two at a time and asserts the third still refuses.

## The interrupt rule, restated because this is the file where it bites hardest

**The gate node re-executes from the top when the run resumes.** Everything above
`interrupt()` runs a second time. So nothing above it may have a side effect, and nothing
below it may run twice without being idempotent. `commit` is always a separate node
downstream — a payment instructed twice is not recoverable by apologising.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final, Protocol

import structlog

from agent_svc.agents.supervisor.routes import GATE_PRECONDITIONS

_log = structlog.get_logger(__name__)

# How fresh a second factor has to be. Mirrors `sarana_shared.auth.principal.STEP_UP_WINDOW`;
# a test asserts they agree, because two windows that were meant to be equal are two windows
# that eventually are not, and the looser one silently wins.
STEP_UP_WINDOW: Final = timedelta(minutes=5)


class GateKind(StrEnum):
    """The gates. Two of them, and there are deliberately only two.

    Every other approval in the platform is an ordinary authorisation check. These two send
    people towards a hazard and move public money, and they are the two scopes
    `strip_human_gates` removes from every machine principal at mint time.
    """

    DISPATCH_SIGNOFF = "dispatch_signoff"
    DISBURSEMENT_RELEASE = "disbursement_release"


class GateRefused(Exception):
    """The gate did not pass, and why. Never caught into a warning."""


class ApprovalNotFound(GateRefused):
    """No approval record exists for this subject.

    The case that matters: a resume payload claiming an approval that was never recorded.
    That is either a client bug or somebody calling the resume endpoint directly, and both
    are refusals rather than warnings.
    """


class ApproverMismatch(GateRefused):
    """The recorded approval is for a different subject, or by a different person.

    The realistic attack: an approval for incident A presented on a resume about incident B,
    by a copied state key or a resume on the wrong thread.
    """


class StepUpTooOld(GateRefused):
    """The approver's second factor was not verified recently enough.

    A session alone is never sufficient. What is missing is proof of who is at the keyboard.
    """


class SubjectNotReady(GateRefused):
    """The subject has not reached the state this gate protects.

    A disbursement gate presented for an entitlement with one approval is a gate asking a
    person to confirm something the platform has not finished doing.
    """


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """What the database says about an approval. The authority, not the payload."""

    gate: str
    subject_id: str
    approved: bool
    approver_id: str
    decided_at: datetime
    step_up_at: datetime | None = None
    reason: str | None = None

    def step_up_fresh(self, *, now: datetime, window: timedelta = STEP_UP_WINDOW) -> bool:
        if self.step_up_at is None:
            return False
        return (now - self.step_up_at) <= window


class ApprovalStore(Protocol):
    """Where an approval is read back from, after a resume claims one.

    Deliberately read-only. The supervisor verifies approvals; it never records one — that
    is `dispatch_gate.approve` in incident-svc and the disbursement release in ledger-svc,
    both behind scopes no machine principal holds.
    """

    async def approval_for(self, gate: str, subject_id: str) -> ApprovalRecord | None:
        """The recorded approval for this subject, or None if there is not one.

        None rather than raising for a missing record: "nobody approved this" is a real and
        common answer, and it is the one the gate refuses on.
        """
        ...

    async def facts_for(self, subject_id: str) -> set[str]:
        """What has already happened to this subject, for the precondition check."""
        ...


async def verify_approval_record(
    gate: GateKind,
    subject_id: str,
    decision: dict[str, Any],
    *,
    store: ApprovalStore,
    now: datetime,
) -> ApprovalRecord:
    """Re-check, from the database, that this approval is real.

    **The resume payload is client input and is not trusted.** It is used to identify what to
    look up and to carry the reason; every fact the gate acts on comes from the record.

    Five ways to fail, checked separately so the message says which:

      no record at all — a resume claiming an approval nobody made;
      a record for a different subject — the realistic carry-over attack;
      a record by a different person than the payload claims — a mismatch worth refusing
        even though the record would be authoritative, because the two disagreeing means
        something is wrong upstream and proceeding would hide it;
      a stale second factor — a session is not proof of who is at the keyboard;
      a refusal — a person said no, which is a decision and is not an absence.

    Raises:
        GateRefused: one of the five subclasses above.
    """
    record = await store.approval_for(gate.value, subject_id)

    if record is None:
        _log.error(
            "gate_no_approval_record",
            gate=gate.value,
            subject_id=subject_id,
            claimed_by=str(decision.get("decided_by", "")),
            impact="the resume claimed an approval that does not exist in the database; refused",
        )
        raise ApprovalNotFound(
            f"{gate.value}: no approval record exists for {subject_id}. A resume payload is "
            "client input and is never sufficient on its own."
        )

    if record.subject_id != subject_id:
        _log.error(
            "gate_subject_mismatch",
            gate=gate.value,
            recorded_subject=record.subject_id,
            resumed_subject=subject_id,
            impact="an approval for one subject was presented for another; refused",
        )
        raise ApproverMismatch(
            f"{gate.value}: the recorded approval is for {record.subject_id}, not "
            f"{subject_id}. An approval is for one thing, not for whatever is in front of it."
        )

    claimed = str(decision.get("decided_by", "")).strip()
    if claimed and claimed != record.approver_id:
        _log.error(
            "gate_approver_mismatch",
            gate=gate.value,
            recorded=record.approver_id,
            claimed=claimed,
            impact="the resume names a different approver from the record; refused",
        )
        raise ApproverMismatch(
            f"{gate.value}: the resume says {claimed} approved this and the record says "
            f"{record.approver_id}. They disagree, so neither is acted on."
        )

    if not record.step_up_fresh(now=now):
        raise StepUpTooOld(
            f"{gate.value}: the approver's second factor was not verified within the last "
            f"{int(STEP_UP_WINDOW.total_seconds() // 60)} minutes. An authenticated session "
            "is not proof of who is at the keyboard."
        )

    if not record.approved:
        raise GateRefused(
            f"{gate.value}: a person reviewed this and said no. A refusal is a decision, "
            "not an absence, and it is not retried into an approval."
        )

    _log.info(
        "gate_approval_verified",
        gate=gate.value,
        subject_id=subject_id,
        approver_id=record.approver_id,
        source="database record, not the resume payload",
    )
    return record


async def assert_sequenced(gate: GateKind, subject_id: str, *, store: ApprovalStore) -> set[str]:
    """Refuse a gate presented before the subject is ready for it.

    A disbursement gate on an entitlement with one approval asks a person to confirm
    something the platform has not finished doing — and the person, reasonably, confirms it.
    The gate is only meaningful when everything it depends on has actually happened.

    Raises:
        SubjectNotReady: naming what has not happened yet.
    """
    facts = await store.facts_for(subject_id)
    required = GATE_PRECONDITIONS.get(gate.value, ())
    missing = tuple(fact for fact in required if fact not in facts)

    if missing:
        _log.error(
            "gate_subject_not_ready",
            gate=gate.value,
            subject_id=subject_id,
            missing=list(missing),
            impact="the gate was not presented; a person asked to confirm an unfinished "
            "process confirms it",
        )
        raise SubjectNotReady(
            f"{gate.value} cannot be presented for {subject_id}: "
            f"{', '.join(missing)} has not happened."
        )
    return facts


def payload_for(
    gate: GateKind, subject_id: str, detail: dict[str, Any], *, waiting_since: datetime
) -> dict[str, Any]:
    """What the approval inbox renders.

    `waiting_since` is on every gate payload, and it is not decoration. A dispatch sign-off
    waiting eight minutes during a flood is an operational emergency, and the console cannot
    show that unless the item carries when it started waiting.

    Build file 18 is blunt about what the metric is for: if it shows humans are consistently
    too slow, that is a staffing finding to report honestly, not a reason to weaken the gate.
    """
    return {
        "kind": gate.value,
        "subject_id": subject_id,
        "requires_step_up": True,
        "waiting_since": waiting_since.isoformat(),
        **detail,
    }


def age_minutes(waiting_since: datetime, *, now: datetime) -> float:
    """How long this gate has been waiting, for the SLA display."""
    return max(0.0, (now - waiting_since).total_seconds() / 60.0)
