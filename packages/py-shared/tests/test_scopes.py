"""RBAC: permission and area are two independent checks, and both must pass."""

from __future__ import annotations

import pytest

from sarana_shared.auth.grants import (
    ScopeType,
    grants_for_assignments,
)
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import HUMAN_GATE_SCOPES, ROLE_SCOPES, Role, Scope
from sarana_shared.errors import Forbidden

KANDY_GN = "LK-11-03-045"
KANDY_DS = "LK-11-03"
BATTICALOA_GN = "LK-02-04-011"


def principal_for(role: Role, scope_type: ScopeType, code: str) -> Principal:
    return Principal(
        subject_id="officer-1",
        roles=frozenset({role}),
        grants=grants_for_assignments([(role, scope_type, code)]),
    )


def test_the_two_human_gates_are_exactly_two() -> None:
    assert frozenset({Scope.DISPATCH_COMMIT, Scope.DISBURSEMENT_RELEASE}) == HUMAN_GATE_SCOPES


def test_no_machine_role_holds_either_gate() -> None:
    """The autonomy model expressed in code, not in a document."""
    for role in (Role.AGENT, Role.SERVICE):
        assert not ROLE_SCOPES[role] & HUMAN_GATE_SCOPES


def test_admin_does_not_hold_the_gates_either() -> None:
    """There is no super-user path around a gate."""
    assert not ROLE_SCOPES[Role.ADMIN] & HUMAN_GATE_SCOPES


def test_the_right_role_in_the_wrong_district_is_still_refused() -> None:
    officer = principal_for(Role.DS_APPROVER, ScopeType.DS, KANDY_DS)

    assert officer.has_scope(Scope.ENTITLEMENT_APPROVE_DS)
    assert officer.can(Scope.ENTITLEMENT_APPROVE_DS, KANDY_GN)
    assert not officer.can(Scope.ENTITLEMENT_APPROVE_DS, BATTICALOA_GN)


def test_no_scope_is_inherited_upward() -> None:
    """A GN officer never gains DS rights, however the codes relate."""
    officer = principal_for(Role.GN_OFFICER, ScopeType.GN, KANDY_GN)

    assert officer.can(Scope.ASSESSMENT_WRITE, KANDY_GN)
    assert not officer.can(Scope.ASSESSMENT_WRITE, KANDY_DS)
    assert not officer.can(Scope.ASSESSMENT_WRITE, "LK-11")


def test_a_gn_officer_cannot_approve_an_entitlement_in_their_own_division() -> None:
    """Holding the area is not the same as holding the permission."""
    officer = principal_for(Role.GN_OFFICER, ScopeType.GN, KANDY_GN)

    assert not officer.can(Scope.ENTITLEMENT_APPROVE_DS, KANDY_GN)


def test_a_national_grant_satisfies_any_narrower_target() -> None:
    operator = Principal(
        subject_id="dmc-1",
        roles=frozenset({Role.DMC_OPERATOR}),
        grants=grants_for_assignments([(Role.DMC_OPERATOR, ScopeType.NATIONAL, "LK")]),
    )

    assert operator.can(Scope.INCIDENT_READ, BATTICALOA_GN)
    assert operator.can(Scope.INCIDENT_READ, KANDY_DS)
    assert operator.is_national


def test_denial_does_not_disclose_the_record() -> None:
    officer = principal_for(Role.DS_APPROVER, ScopeType.DS, KANDY_DS)

    with pytest.raises(Forbidden) as caught:
        officer.assert_can(Scope.ENTITLEMENT_APPROVE_DS, BATTICALOA_GN)

    assert BATTICALOA_GN not in str(caught.value)
    assert "outside your assigned administrative area" in str(caught.value)


def test_missing_scope_names_the_scope_not_the_record() -> None:
    officer = principal_for(Role.DS_APPROVER, ScopeType.DS, KANDY_DS)

    with pytest.raises(Forbidden, match="disbursement:release"):
        officer.assert_can(Scope.DISBURSEMENT_RELEASE, KANDY_GN)


def test_a_citizen_cannot_read_the_incident_queue() -> None:
    assert Scope.INCIDENT_READ not in ROLE_SCOPES[Role.CITIZEN]
    assert Scope.INCIDENT_WRITE in ROLE_SCOPES[Role.CITIZEN]
    assert Scope.GRIEVANCE_FILE in ROLE_SCOPES[Role.CITIZEN]


def test_every_citizen_has_a_grievance_path() -> None:
    """ADR-008: any decision affecting a household is contestable by that household."""
    assert Scope.GRIEVANCE_FILE in ROLE_SCOPES[Role.CITIZEN]
    assert Scope.GRIEVANCE_RESOLVE in ROLE_SCOPES[Role.DS_APPROVER]


def test_a_principal_with_no_grants_can_do_nothing() -> None:
    """The safe default. No grants is not an error state, it is zero authority."""
    nobody = Principal(subject_id="u", roles=frozenset(), grants=frozenset())

    assert not nobody.can(Scope.INCIDENT_READ, KANDY_GN)
    assert not nobody.can(Scope.INCIDENT_READ)
