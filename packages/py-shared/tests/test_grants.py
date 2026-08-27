"""Scope grant parsing and the matching rules that must not be got wrong."""

from __future__ import annotations

import pytest

from sarana_shared.auth.grants import (
    InvalidGrant,
    ScopeGrant,
    ScopeType,
    grants_for_assignments,
    strip_human_gates,
)
from sarana_shared.auth.scopes import HUMAN_GATE_SCOPES, Role, Scope


def test_a_grant_round_trips_through_its_string_form() -> None:
    grant = ScopeGrant.parse("assessment:write:GN:LK-11-03-045")

    assert grant.scope is Scope.ASSESSMENT_WRITE
    assert grant.scope_type is ScopeType.GN
    assert str(grant) == "assessment:write:GN:LK-11-03-045"


def test_a_national_grant_uses_the_wildcard() -> None:
    grant = ScopeGrant.parse("ledger:read:NATIONAL:*")

    assert grant.scope_type is ScopeType.NATIONAL
    assert grant.covers(Scope.LEDGER_READ, "LK-02-04-011")


@pytest.mark.parametrize(
    "value",
    [
        "assessment:write",
        "assessment:write:GN",
        "assessment:write:GN:Kandy",
        "assessment:teleport:GN:LK-11-03-045",
        "assessment:write:PROVINCE:LK-P02",
        # A DS code presented as a GN grant: the level must match the claim.
        "assessment:write:GN:LK-11-03",
    ],
)
def test_a_malformed_grant_is_refused(value: str) -> None:
    with pytest.raises(InvalidGrant):
        ScopeGrant.parse(value)


def test_a_national_grant_cannot_name_a_division() -> None:
    """`NATIONAL:LK-11` would read as unrestricted while meaning something narrower."""
    with pytest.raises(InvalidGrant, match=r"must use"):
        ScopeGrant.parse("ledger:read:NATIONAL:LK-11")


@pytest.mark.parametrize(
    ("grant", "target", "covered"),
    [
        ("incident:read:NATIONAL:*", "LK-11-03-045", True),
        ("incident:read:DISTRICT:LK-11", "LK-11-03-045", True),
        ("incident:read:DISTRICT:LK-11", "LK-11-03", True),
        ("incident:read:DS:LK-11-03", "LK-11-03-045", True),
        ("incident:read:GN:LK-11-03-045", "LK-11-03-045", True),
        # No upward inheritance.
        ("incident:read:GN:LK-11-03-045", "LK-11-03", False),
        ("incident:read:DS:LK-11-03", "LK-11", False),
        # Sideways is refused too.
        ("incident:read:DS:LK-11-03", "LK-11-04-001", False),
        ("incident:read:DISTRICT:LK-11", "LK-12-03-045", False),
    ],
)
def test_containment_follows_the_hierarchy(grant: str, target: str, covered: bool) -> None:
    assert ScopeGrant.parse(grant).covers(Scope.INCIDENT_READ, target) is covered


def test_a_grant_only_covers_its_own_permission() -> None:
    grant = ScopeGrant.parse("incident:read:NATIONAL:*")

    assert not grant.covers(Scope.DISBURSEMENT_RELEASE, "LK-11-03-045")


def test_one_role_in_two_divisions_produces_two_grant_sets() -> None:
    """A DS officer covering a second division during a surge holds each area separately."""
    grants = grants_for_assignments(
        [
            (Role.DS_APPROVER, ScopeType.DS, "LK-11-03"),
            (Role.DS_APPROVER, ScopeType.DS, "LK-11-04"),
        ]
    )

    codes = {grant.scope_code for grant in grants}
    assert codes == {"LK-11-03", "LK-11-04"}


def test_machine_principals_are_stripped_of_both_gates() -> None:
    """No configuration mistake can hand an agent a human gate."""
    granted = grants_for_assignments(
        [
            (Role.DISTRICT_APPROVER, ScopeType.DISTRICT, "LK-11"),
        ]
    )
    assert {g.scope for g in granted} & HUMAN_GATE_SCOPES

    stripped = strip_human_gates(granted)

    assert not {g.scope for g in stripped} & HUMAN_GATE_SCOPES
    assert len(stripped) < len(granted)
