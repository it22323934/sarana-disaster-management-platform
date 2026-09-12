"""Legal state transitions for reports and incidents.

A table, not scattered `if` statements. Two reasons, and the second is the one that
matters: a table can be read in full by someone deciding whether a change is safe, and it
can be tested exhaustively. Conditions spread across handlers can only be tested for the
paths someone thought of.

The vocabularies here are the ones the database CHECK constraints enforce, which are not
quite the names in the build brief. Where they differ the schema wins, because it is what
actually rejects a bad write:

    brief NEW               -> REPORTED    (a report has arrived, nothing has verified it)
    brief MERGED            -> DUPLICATE   (folded into another incident)
    brief DISPATCH_PROPOSED -> no separate state

The last one is deliberate rather than an omission. A proposed dispatch is a fact about a
`dispatch_plan`, which has its own status, not about the incident: an incident with a
rejected plan is still TRIAGED and still needs someone. Encoding it twice would let the two
disagree, and the version on the dispatcher's screen would be a coin toss.
"""

from __future__ import annotations

from typing import Final

from incident_svc.repo.base import INCIDENT_STATUSES, PROCESSING_STATUSES

# --------------------------------------------------------------------------------------
# Raw reports
# --------------------------------------------------------------------------------------

# RECEIVED -> TRANSCRIBING -> VERIFYING -> LINKED, with HUMAN_REVIEW reachable from either
# processing step and REJECTED reachable from review.
REPORT_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "RECEIVED": frozenset({"TRANSCRIBING", "VERIFYING", "HUMAN_REVIEW", "REJECTED"}),
    "TRANSCRIBING": frozenset({"VERIFYING", "HUMAN_REVIEW", "REJECTED"}),
    "VERIFYING": frozenset({"LINKED", "HUMAN_REVIEW", "REJECTED"}),
    # A human who has corrected a transcription sends it on to be linked, or rejects it.
    "HUMAN_REVIEW": frozenset({"VERIFYING", "LINKED", "REJECTED"}),
    # Terminal. A linked report that turns out to be wrong is handled by unlinking it from
    # its incident, not by rewinding the report.
    "LINKED": frozenset(),
    "REJECTED": frozenset(),
}

# --------------------------------------------------------------------------------------
# Incidents
# --------------------------------------------------------------------------------------

INCIDENT_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "REPORTED": frozenset({"VERIFIED", "DUPLICATE", "REJECTED"}),
    "VERIFIED": frozenset({"TRIAGED", "DUPLICATE", "REJECTED"}),
    # A rejected dispatch plan returns the incident to TRIAGED - it still needs someone,
    # and it goes back into the queue rather than being quietly dropped.
    "TRIAGED": frozenset({"DISPATCHED", "TRIAGED", "DUPLICATE", "RESOLVED", "REJECTED"}),
    "DISPATCHED": frozenset({"IN_PROGRESS", "TRIAGED", "RESOLVED"}),
    "IN_PROGRESS": frozenset({"RESOLVED", "TRIAGED"}),
    "RESOLVED": frozenset(),
    # A bad automatic dedup is undone by a split, which returns the incident to the state
    # it can be worked from rather than to where it started.
    "DUPLICATE": frozenset({"TRIAGED", "VERIFIED"}),
    "REJECTED": frozenset({"TRIAGED"}),
}


class IllegalTransition(Exception):
    """A state change the machine does not allow.

    Carries both states so the audit entry and the 409 body can say what was attempted
    rather than only that something was refused.
    """

    def __init__(self, kind: str, subject_id: str, current: str, requested: str) -> None:
        super().__init__(
            f"{kind} {subject_id} cannot move from {current} to {requested}. "
            f"Legal from {current}: {', '.join(sorted(legal_next(kind, current))) or 'nothing'}."
        )
        self.kind = kind
        self.subject_id = subject_id
        self.current = current
        self.requested = requested


def _table(kind: str) -> dict[str, frozenset[str]]:
    if kind == "report":
        return REPORT_TRANSITIONS
    if kind == "incident":
        return INCIDENT_TRANSITIONS
    raise ValueError(f"unknown state machine {kind!r}")


def legal_next(kind: str, current: str) -> frozenset[str]:
    """Every state reachable in one step. Empty for a terminal state."""
    return _table(kind).get(current, frozenset())


def can_transition(kind: str, current: str, requested: str) -> bool:
    """Whether one step is allowed."""
    return requested in legal_next(kind, current)


def assert_transition(kind: str, subject_id: str, current: str, requested: str) -> None:
    """Allow a transition or refuse it.

    Raises:
        IllegalTransition: mapped to 409 by the API layer, and audited.
    """
    if not can_transition(kind, current, requested):
        raise IllegalTransition(kind, subject_id, current, requested)


def is_terminal(kind: str, state: str) -> bool:
    """Whether nothing further can happen to this record."""
    return not legal_next(kind, state)


def unreachable_states(kind: str) -> frozenset[str]:
    """States no transition leads to.

    A state nothing can reach is either the entry point or a mistake, and the difference
    is worth being able to assert rather than assume.
    """
    table = _table(kind)
    reachable: set[str] = set()
    for targets in table.values():
        reachable |= targets
    return frozenset(set(table) - reachable)


def known_states(kind: str) -> frozenset[str]:
    """The vocabulary this machine covers, which must match the database CHECK."""
    if kind == "report":
        return frozenset(PROCESSING_STATUSES)
    if kind == "incident":
        return frozenset(INCIDENT_STATUSES)
    raise ValueError(f"unknown state machine {kind!r}")
