"""When two agents disagree about the same subject: pause, assemble, escalate.

**The supervisor never auto-resolves a conflict touching life safety or money. Ever.** That
is build file 18's word, and it is the one rule in this module that has no exception clause.

The conflicts that actually arise are not exotic:

  intake links two reports as duplicates; a responder on the ground reports them as distinct
  addresses — and if the merge stands, one household is never visited;

  a forecast downgrades while an alert for the upgraded level is mid-dispatch — cancel and
  people stop believing the next one, continue and the alert overstates the danger;

  an assessment is updated after its entitlement was calculated — the money is either wrong
  or was already released;

  two responders both claim the same incident — a duplicated crew somewhere is a missing
  crew somewhere else.

Every one of those is a case where the *right* answer needs something the platform does not
have: what somebody saw when they got there. So the supervisor pauses the subject, assembles
both positions with their evidence and confidence, and puts them in front of a person.

## The model may propose, and its proposal is labelled as one

`adjudicate` runs at the escalated tier and returns `recommended: A | B | neither` with a
rationale — and `why_the_other_might_be_right`, which is **required**. A recommendation that
cannot articulate the counter-case is suppressed entirely.

That requirement is doing real work. A model that cannot say why the other position might be
right has not weighed two positions; it has picked one and justified it, and a human reading
a confident one-sided proposal adopts it. The counter-case is what keeps the human deciding.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Protocol

import structlog

_log = structlog.get_logger(__name__)

# Conflicts that may never be auto-resolved, whatever any model recommends. Everything that
# sends a crew or moves money is on this list, and the list is deliberately allow-nothing:
# a kind not named here still escalates, because the default is to ask.
LIFE_SAFETY_OR_MONEY: Final[frozenset[str]] = frozenset(
    {
        "duplicate_link_disputed",
        "forecast_downgraded_mid_dispatch",
        "assessment_updated_after_entitlement",
        "responder_double_claim",
        "alert_severity_disputed",
    }
)

RECOMMENDATIONS: Final[tuple[str, ...]] = ("A", "B", "neither")


@dataclass(frozen=True, slots=True)
class Position:
    """One side of a disagreement, with what produced it.

    `source` is the agent or the role that holds this position, never a person's name: the
    conflict record goes into a checkpoint and is read during debugging.
    """

    source: str
    claim: str
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)
    observed_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "claim": self.claim,
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
        }


@dataclass(frozen=True, slots=True)
class Conflict:
    """Two positions about one subject, and what the platform did about it."""

    kind: str
    subject_type: str
    subject_id: str
    position_a: Position
    position_b: Position
    detected_at: datetime | None = None

    @property
    def touches_life_safety_or_money(self) -> bool:
        """Whether this may ever be resolved without a person.

        **Always True, and that is not a stub.** Every conflict kind this platform can
        produce sends a crew or moves money, and a kind nobody anticipated is the one least
        likely to be safe to resolve automatically - so the default is to ask.

        `LIFE_SAFETY_OR_MONEY` exists so the log can name which known kind this was, not to
        admit exceptions. If a genuinely inconsequential conflict kind ever appears, adding
        it here is a deliberate act somebody has to argue for against build file 18's "never
        auto-resolves a conflict touching life safety or money. Ever."
        """
        return True

    @property
    def is_a_known_kind(self) -> bool:
        """Whether this is one of the conflicts the platform anticipated.

        An unknown kind still escalates; this only distinguishes "we planned for this" from
        "something new happened", which is worth seeing in a log.
        """
        return self.kind in LIFE_SAFETY_OR_MONEY

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "position_a": self.position_a.as_dict(),
            "position_b": self.position_b.as_dict(),
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
        }


@dataclass(frozen=True, slots=True)
class Adjudication:
    """A model's proposal. Never applied, always labelled.

    `why_the_other_might_be_right` is required and `usable` is False without it. See the
    module docstring: a recommendation that cannot state the counter-case has picked a side
    rather than weighed two.
    """

    recommended: str
    rationale: str
    why_the_other_might_be_right: str
    confidence: float
    method: str = "TEMPLATE"

    @property
    def usable(self) -> bool:
        return (
            self.recommended in RECOMMENDATIONS
            and bool(self.rationale.strip())
            and bool(self.why_the_other_might_be_right.strip())
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "recommended": self.recommended,
            "rationale": self.rationale,
            "why_the_other_might_be_right": self.why_the_other_might_be_right,
            "confidence": round(self.confidence, 3),
            "method": self.method,
            # Restated on the record itself, because this dict is what the console renders
            # and a proposal that does not say it is a proposal reads as a decision.
            "is_a_proposal": True,
            "note": "a proposal for a human, not a resolution. Nothing has been applied.",
        }


class ModelCall(Protocol):
    async def __call__(self, prompt: str) -> str: ...


NO_PROPOSAL: Final = Adjudication(
    recommended="neither",
    rationale=(
        "No proposal was produced. Both positions are shown as they were recorded and a "
        "person decides between them."
    ),
    why_the_other_might_be_right=(
        "Neither position has been weighed by this platform, so both should be read on "
        "their own evidence."
    ),
    confidence=0.0,
    method="TEMPLATE",
)

INSTRUCTIONS: Final = """Two parts of a Sri Lankan disaster response system disagree about \
the same subject. You are proposing a resolution for a human to accept or reject. You are \
not deciding.

Return only JSON:
{
  "recommended": "A" | "B" | "neither",
  "rationale": "one or two sentences",
  "why_the_other_might_be_right": "one or two sentences, required",
  "confidence": 0.0 to 1.0
}

why_the_other_might_be_right is not optional. If you cannot state a genuine case for the \
position you did not choose, answer "neither" - a recommendation that cannot articulate the \
counter-case will be discarded.

Remember what each error costs. Merging two reports that are actually different addresses \
means one household is never visited. Splitting one incident into two means a duplicated \
crew. Those costs are not symmetric and the second is far cheaper.
"""


async def adjudicate(conflict: Conflict, *, call: ModelCall | None = None) -> Adjudication:
    """Ask for a proposal. Return `NO_PROPOSAL` whenever one cannot be had.

    Every failure path lands on no proposal rather than on a guess: no model, an unreachable
    provider, unparseable output, or a recommendation with no counter-case. The conflict is
    still escalated and both positions are still shown — what is lost is a suggestion, and
    the human was always the one deciding.
    """
    if call is None:
        return NO_PROPOSAL

    try:
        answer = await call(_prompt(conflict))
    except Exception as error:  # noqa: BLE001 - a conflict never waits on a model provider
        _log.warning(
            "supervisor_adjudication_unavailable",
            kind=conflict.kind,
            error=type(error).__name__,
            impact="the conflict is escalated with both positions and no proposal",
        )
        return NO_PROPOSAL

    parsed = _parse(answer)
    if parsed is None:
        return NO_PROPOSAL

    if not parsed.usable:
        _log.info(
            "supervisor_adjudication_suppressed",
            kind=conflict.kind,
            recommended=parsed.recommended,
            impact="the proposal could not state why the other position might be right, so "
            "it was discarded; the conflict is escalated without it",
        )
        return NO_PROPOSAL

    return parsed


@dataclass(frozen=True, slots=True)
class Escalation:
    """What goes in front of the person, and what was done meanwhile.

    `paused` is always True for the conflicts this platform has. The subject stops moving
    until somebody decides, because the alternative is acting on one of two positions that
    the system itself could not choose between.
    """

    conflict: Conflict
    proposal: Adjudication
    paused: bool = True

    def as_interrupt_payload(self) -> dict[str, Any]:
        """The approval inbox's contract for a conflict.

        Both positions, the proposal marked as a proposal, and no default selection. A
        screen that pre-selects the recommendation converts a decision into a confirmation.
        """
        return {
            "kind": "conflict",
            "conflict": self.conflict.as_dict(),
            "options": {
                "A": self.conflict.position_a.as_dict(),
                "B": self.conflict.position_b.as_dict(),
            },
            "proposal": self.proposal.as_dict(),
            "subject_paused": self.paused,
            "note": (
                "The subject is paused. Both positions are shown as recorded; the proposal "
                "is a suggestion and nothing has been applied."
            ),
        }


async def escalate(conflict: Conflict, *, call: ModelCall | None = None) -> Escalation:
    """Pause the subject, assemble both positions, and attach a proposal if one can be had.

    Never resolves. There is no branch in this function that applies a recommendation, and
    that is the point: `Escalation` has no "resolved" state to reach.
    """
    proposal = await adjudicate(conflict, call=call)

    _log.info(
        "supervisor_conflict_escalated",
        kind=conflict.kind,
        subject_type=conflict.subject_type,
        subject_id=conflict.subject_id,
        known_kind=conflict.is_a_known_kind,
        recommended=proposal.recommended,
        proposal_method=proposal.method,
        impact="the subject is paused until a person decides; nothing was applied",
    )
    return Escalation(conflict=conflict, proposal=proposal)


def _prompt(conflict: Conflict) -> str:
    """The prompt. Both positions, symmetrically, with no hint which is preferred."""
    return (
        f"{INSTRUCTIONS}\n"
        f"Conflict: {conflict.kind}\n"
        f"Subject: {conflict.subject_type} {conflict.subject_id}\n"
        f"\nPosition A - {conflict.position_a.source}\n"
        f"  claim: {conflict.position_a.claim}\n"
        f"  confidence: {conflict.position_a.confidence:.2f}\n"
        f"  evidence: {json.dumps(conflict.position_a.evidence, sort_keys=True)}\n"
        f"\nPosition B - {conflict.position_b.source}\n"
        f"  claim: {conflict.position_b.claim}\n"
        f"  confidence: {conflict.position_b.confidence:.2f}\n"
        f"  evidence: {json.dumps(conflict.position_b.evidence, sort_keys=True)}\n"
        f"\nJSON:"
    )


def _parse(answer: str) -> Adjudication | None:
    body = answer.strip()
    if body.startswith("```"):
        body = body.split("```")[1] if "```" in body[3:] else body[3:]
        body = body.removeprefix("json").strip()

    try:
        raw = json.loads(body)
    except (ValueError, TypeError):
        _log.warning("supervisor_adjudication_unparseable")
        return None

    if not isinstance(raw, dict):
        return None

    return Adjudication(
        recommended=str(raw.get("recommended", "")).strip(),
        rationale=str(raw.get("rationale", "")).strip(),
        why_the_other_might_be_right=str(raw.get("why_the_other_might_be_right", "")).strip(),
        confidence=float(raw.get("confidence", 0.0)),
        method="LLM",
    )
