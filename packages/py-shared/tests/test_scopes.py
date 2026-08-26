"""RBAC: permission and area are two independent checks, and both must pass."""

from __future__ import annotations

import pytest

from sarana_shared.auth.scopes import (
    HUMAN_GATE_SCOPES,
    ROLE_SCOPES,
    AreaScope,
    Principal,
    Role,
    Scope,
    scopes_for_roles,
)
from sarana_shared.errors import Forbidden

KANDY_GN = "LK-11-03-045"
BATTICALOA_GN = "LK-02-04-011"


def ds_officer(area: str) -> Principal:
    roles = frozenset({Role.DS_OFFICER})
    return Principal(
        subject_id="officer-1",
        roles=roles,
        scopes=scopes_for_roles(roles),
        area=AreaScope.of(area),
    )


def test_the_two_human_gates_are_exactly_two() -> None:
    assert HUMAN_GATE_SCOPES == frozenset(
        {Scope.DISPATCH_COMMIT, Scope.DISBURSEMENT_RELEASE}
    )


def test_no_machine_role_holds_either_gate() -> None:
    """The autonomy model expressed in code, not in a document."""
    for role in (Role.AGENT, Role.SERVICE):
        assert not ROLE_SCOPES[role] & HUMAN_GATE_SCOPES


def test_system_admin_does_not_hold_the_gates_either() -> None:
    """There is no super-user path around a gate."""
    assert not ROLE_SCOPES[Role.SYSTEM_ADMIN] & HUMAN_GATE_SCOPES


def test_the_right_role_in_the_wrong_district_is_still_refused() -> None:
    officer = ds_officer("LK-11-03")

    assert officer.has_scope(Scope.ENTITLEMENT_APPROVE_DS)
    assert officer.can(Scope.ENTITLEMENT_APPROVE_DS, KANDY_GN)
    assert not officer.can(Scope.ENTITLEMENT_APPROVE_DS, BATTICALOA_GN)


def test_denial_does_not_disclose_the_record() -> None:
    officer = ds_officer("LK-11-03")

    with pytest.raises(Forbidden) as caught:
        officer.assert_can(Scope.ENTITLEMENT_APPROVE_DS, BATTICALOA_GN)

    assert BATTICALOA_GN not in str(caught.value)
    assert "outside your assigned administrative area" in str(caught.value)


def test_missing_scope_names_the_scope_not_the_record() -> None:
    officer = ds_officer("LK-11-03")

    with pytest.raises(Forbidden, match="disbursement:release"):
        officer.assert_can(Scope.DISBURSEMENT_RELEASE, KANDY_GN)


def test_a_citizen_cannot_read_the_incident_queue() -> None:
    assert Scope.INCIDENT_READ not in ROLE_SCOPES[Role.CITIZEN]
    assert Scope.INCIDENT_WRITE in ROLE_SCOPES[Role.CITIZEN]
    assert Scope.GRIEVANCE_FILE in ROLE_SCOPES[Role.CITIZEN]


def test_every_role_can_file_or_read_a_grievance_path() -> None:
    """ADR-008: every citizen has a contestable path against any decision affecting them."""
    assert Scope.GRIEVANCE_FILE in ROLE_SCOPES[Role.CITIZEN]
    assert Scope.GRIEVANCE_RESOLVE in ROLE_SCOPES[Role.DS_OFFICER]


def test_an_empty_area_scope_covers_nothing() -> None:
    """The safe default. A principal with no area is not an error state."""
    nobody = AreaScope(codes=frozenset())

    assert not nobody.covers(KANDY_GN)


def test_national_area_scope_covers_everything() -> None:
    assert AreaScope.national().covers(BATTICALOA_GN)
