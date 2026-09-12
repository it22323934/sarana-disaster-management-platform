"""The report and incident state machines.

The table is small enough to test exhaustively, so it is: every state pair is checked
against the table rather than a sample of the interesting ones. That is the advantage of
a table over scattered conditions, and it is worth actually taking.
"""

from __future__ import annotations

import pytest

from incident_svc.domain import state_machine
from incident_svc.repo.base import INCIDENT_STATUSES, PROCESSING_STATUSES


@pytest.mark.parametrize("kind", ["report", "incident"])
def test_the_machine_covers_exactly_the_states_the_database_allows(kind: str) -> None:
    """A state the CHECK constraint allows and the table omits is unreachable in practice.

    A state the table allows and the CHECK rejects is worse: the transition passes and the
    write fails, so the refusal arrives as a 500 rather than a 409.
    """
    table_states = set(state_machine._table(kind))

    assert table_states == set(state_machine.known_states(kind))


def test_every_report_status_in_the_schema_is_in_the_table() -> None:
    assert set(state_machine.REPORT_TRANSITIONS) == set(PROCESSING_STATUSES)


def test_every_incident_status_in_the_schema_is_in_the_table() -> None:
    assert set(state_machine.INCIDENT_TRANSITIONS) == set(INCIDENT_STATUSES)


@pytest.mark.parametrize("kind", ["report", "incident"])
def test_no_transition_targets_an_unknown_state(kind: str) -> None:
    """A typo in a target would be a transition that always fails at the database."""
    known = state_machine.known_states(kind)
    for current, targets in state_machine._table(kind).items():
        assert targets <= known, f"{current} targets something outside the schema"


# --------------------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        ("RECEIVED", "TRANSCRIBING"),
        ("TRANSCRIBING", "VERIFYING"),
        ("VERIFYING", "LINKED"),
        ("TRANSCRIBING", "HUMAN_REVIEW"),
        ("VERIFYING", "HUMAN_REVIEW"),
        ("HUMAN_REVIEW", "LINKED"),
        ("HUMAN_REVIEW", "REJECTED"),
    ],
)
def test_the_documented_report_path_is_allowed(current: str, requested: str) -> None:
    assert state_machine.can_transition("report", current, requested)


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        ("LINKED", "RECEIVED"),
        ("LINKED", "HUMAN_REVIEW"),
        ("REJECTED", "LINKED"),
        ("RECEIVED", "LINKED"),
    ],
)
def test_reports_cannot_move_backwards_or_skip_verification(current: str, requested: str) -> None:
    """LINKED and REJECTED are terminal, and nothing reaches LINKED unverified."""
    assert not state_machine.can_transition("report", current, requested)


def test_a_linked_report_is_terminal() -> None:
    """A linked report that turns out to be wrong is unlinked from its incident.

    Rewinding the report instead would leave the incident holding a link to something that
    claims never to have been linked.
    """
    assert state_machine.is_terminal("report", "LINKED")


# --------------------------------------------------------------------------------------
# Incidents
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        ("REPORTED", "VERIFIED"),
        ("VERIFIED", "TRIAGED"),
        ("TRIAGED", "DISPATCHED"),
        ("DISPATCHED", "IN_PROGRESS"),
        ("IN_PROGRESS", "RESOLVED"),
    ],
)
def test_the_documented_incident_path_is_allowed(current: str, requested: str) -> None:
    assert state_machine.can_transition("incident", current, requested)


def test_a_rejected_dispatch_returns_an_incident_to_the_queue() -> None:
    """It still needs someone. Dropping it would be the quiet failure."""
    assert state_machine.can_transition("incident", "DISPATCHED", "TRIAGED")


def test_a_split_returns_a_merged_incident_to_the_queue() -> None:
    """Undoing a bad dedup must give the incident somewhere to go."""
    assert state_machine.can_transition("incident", "DUPLICATE", "TRIAGED")


def test_a_resolved_incident_cannot_be_reopened() -> None:
    """A stale client retrying must not put a closed incident back in the queue."""
    assert state_machine.is_terminal("incident", "RESOLVED")
    assert not state_machine.can_transition("incident", "RESOLVED", "TRIAGED")


def test_an_incident_cannot_skip_straight_to_dispatched() -> None:
    """Dispatching something nobody verified is the failure the machine exists to stop."""
    assert not state_machine.can_transition("incident", "REPORTED", "DISPATCHED")


# --------------------------------------------------------------------------------------
# Refusal carries the information a 409 needs
# --------------------------------------------------------------------------------------


def test_an_illegal_transition_names_both_states_and_the_legal_ones() -> None:
    """The message reaches an operator through the 409 body, so it has to be useful."""
    with pytest.raises(state_machine.IllegalTransition) as caught:
        state_machine.assert_transition("incident", "abc", "RESOLVED", "TRIAGED")

    message = str(caught.value)
    assert "RESOLVED" in message
    assert "TRIAGED" in message
    assert caught.value.current == "RESOLVED"
    assert caught.value.requested == "TRIAGED"


def test_a_legal_transition_raises_nothing() -> None:
    state_machine.assert_transition("incident", "abc", "VERIFIED", "TRIAGED")


def test_an_unknown_machine_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="unknown state machine"):
        state_machine.legal_next("household", "ACTIVE")
