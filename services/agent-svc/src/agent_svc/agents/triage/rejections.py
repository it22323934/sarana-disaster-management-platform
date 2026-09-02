"""What a dispatcher said when they turned a plan down, and why that is the point.

**Rejections are the most valuable data this platform produces.** A rejection is a
dispatcher telling us the ranking was wrong in a situation where they know something the
system does not — the road is passable because they drove it an hour ago, the family already
walked out, that address is a shop. None of that is in any database, and every one of those
is a case where the formula was confidently wrong.

So a rejection is never an error path. It is recorded with a taxonomy reason, it appends an
observation to the Resilience Graph, and the incidents go back on the queue rather than
being marked handled. An agent that logged "plan rejected" and moved on would be discarding
the only supervision signal it will ever get.

## Why the reason is a fixed taxonomy and the note is not

Free text cannot be aggregated, and the number that matters is the *distribution* — which
kind of mistake this agent makes most. So the reason comes from
`incident_svc.domain.dispatch_gate.RejectionReason`, the same list the API enforces, and the
note carries whatever else the dispatcher wants to say. `OTHER` still requires a note,
because an untyped rejection with no explanation teaches nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import structlog

from incident_svc.domain.dispatch_gate import RejectionReason

_log = structlog.get_logger(__name__)

# The taxonomy, imported rather than restated. Two lists that were meant to match are two
# lists that eventually do not, and the one that would silently win is whichever the API
# happened to validate against.
REASONS: Final[tuple[str, ...]] = tuple(reason.value for reason in RejectionReason)

# What a rejection with no stated reason is recorded as. Not dropped, and not guessed at:
# `OTHER` with a note saying the reason was missing, so the distribution shows how often the
# console let somebody through without picking one.
UNSTATED: Final = RejectionReason.OTHER.value


@dataclass(frozen=True, slots=True)
class Rejection:
    """One dispatcher's decision to turn a plan down."""

    plan_id: str
    reason: str
    note: str | None
    decided_by: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "reason": self.reason,
            "note": self.note,
            "decided_by": self.decided_by,
        }

    def observations(self, incident_ids: list[str], *, agent: str) -> list[dict[str, Any]]:
        """One observation per incident the rejected plan covered.

        Per incident rather than one for the plan, because the Learn loop asks "was this
        incident ranked correctly?" and a plan-level record cannot answer it. The value is
        the reason, so the distribution is queryable without reading any free text.
        """
        return [
            {
                "subject_type": "incident",
                "subject_id": incident_id,
                "observation": "dispatch_plan_rejected",
                "value": self.reason,
                "confidence": 1.0,
                "source": f"{agent}:human",
            }
            for incident_id in incident_ids
        ]


def record(decision: dict[str, Any], *, plan_id: str) -> Rejection:
    """Turn a resume payload into a rejection record.

    An unrecognised reason is stored as `OTHER` with the original preserved in the note,
    rather than raising. The dispatcher has already decided by the time this runs and the
    incidents are already back on the queue; refusing to record their reason would lose the
    signal to protect a vocabulary.
    """
    raw = str(decision.get("reason") or "").strip().lower()
    note = decision.get("note") or decision.get("free_text")

    if raw in REASONS:
        reason = raw
    elif raw:
        reason = UNSTATED
        note = f"unrecognised reason {raw!r}" + (f"; {note}" if note else "")
        _log.warning(
            "triage_rejection_reason_unrecognised",
            plan_id=plan_id,
            supplied=raw[:64],
            known=list(REASONS),
            impact="recorded as OTHER with the original preserved; the signal is not lost",
        )
    else:
        reason = UNSTATED
        note = "no reason was supplied" + (f"; {note}" if note else "")

    return Rejection(
        plan_id=plan_id,
        reason=reason,
        note=str(note) if note else None,
        decided_by=str(decision.get("decided_by", "")),
    )


def distribution(rejections: list[Rejection]) -> dict[str, int]:
    """How many rejections of each kind.

    The number that actually matters. An accept rate alone says how often the agent is
    agreed with; this says *how it is wrong*, which is the thing a change can be aimed at.
    """
    counts = dict.fromkeys(REASONS, 0)
    for rejection in rejections:
        counts[rejection.reason] = counts.get(rejection.reason, 0) + 1
    return counts
