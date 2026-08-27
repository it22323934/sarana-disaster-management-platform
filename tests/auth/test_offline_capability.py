"""The offline capability token: three days of usefulness, almost no authority.

Connectivity is the failure mode this platform exists to survive. A GN officer in a
division cut off by a cyclone must be able to keep working. The security answer is not to
make the app online-only - it is to make the offline credential capable of one thing.

These tests are the record of what that one thing is. If a future change widens it, they
fail, and widening it should be hard.
"""

from __future__ import annotations

import pytest

from core_api.domain.auth.capability import (
    CAPABILITY_TTL,
    CapabilityRequest,
    NotAFieldOfficer,
    capability_grants,
    may_hold_capability,
)
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Role, Scope
from sarana_shared.auth.tokens import TokenService
from sarana_shared.errors import Forbidden

pytestmark = pytest.mark.asyncio(loop_scope="session")

KANDY_GN = "LK-11-03-045"
NEIGHBOUR_GN = "LK-11-03-046"


def capability_principal(code: str = KANDY_GN) -> Principal:
    return Principal(
        subject_id="officer-1",
        roles=frozenset({Role.GN_OFFICER}),
        grants=capability_grants(code),
        device_id="handset-1",
        is_offline_capability=True,
    )


async def test_the_token_lasts_three_days() -> None:
    """Long enough for a cut-off division, short enough that a stolen handset expires."""
    assert CAPABILITY_TTL.total_seconds() == 72 * 3600


async def test_it_authorises_drafting_an_assessment_in_its_own_division() -> None:
    principal = capability_principal()

    assert principal.can(Scope.ASSESSMENT_WRITE, KANDY_GN)


@pytest.mark.parametrize(
    "scope",
    [
        Scope.DISBURSEMENT_RELEASE,
        Scope.DISPATCH_COMMIT,
        Scope.ENTITLEMENT_APPROVE_DS,
        Scope.ENTITLEMENT_APPROVE_DISTRICT,
        Scope.INCIDENT_READ,
        Scope.LEDGER_READ,
        Scope.ANOMALY_READ,
        Scope.ALERT_DISPATCH,
        Scope.ASSESSMENT_READ,
    ],
)
async def test_it_authorises_nothing_else(scope: Scope) -> None:
    """Case 6: refused on every endpoint except assessment drafting."""
    principal = capability_principal()

    assert not principal.can(scope, KANDY_GN)


async def test_the_guard_tells_the_officer_to_reconnect() -> None:
    """A generic permission error is useless to someone standing in a flooded village."""
    from sarana_shared.auth.capability_guard import assert_capability_permits

    principal = capability_principal()

    with pytest.raises(Forbidden, match="reconnect"):
        assert_capability_permits(principal, Scope.LEDGER_READ)


async def test_it_cannot_reach_a_neighbouring_division() -> None:
    principal = capability_principal()

    assert not principal.can(Scope.ASSESSMENT_WRITE, NEIGHBOUR_GN)


async def test_only_a_gn_officer_may_hold_one() -> None:
    """An approver working offline would accumulate approvals nobody can check."""
    assert may_hold_capability(frozenset({Role.GN_OFFICER}))
    assert not may_hold_capability(frozenset({Role.DS_APPROVER}))
    assert not may_hold_capability(frozenset({Role.DISTRICT_APPROVER}))
    assert not may_hold_capability(frozenset({Role.ADMIN}))


async def test_it_must_be_pinned_to_one_gn_division() -> None:
    with pytest.raises(NotAFieldOfficer, match="single GN division"):
        CapabilityRequest(
            subject_id="officer-1", gn_division_code="LK-11-03", device_id="handset-1"
        )


async def test_it_must_be_bound_to_a_device() -> None:
    """So a lost handset can be revoked without revoking the officer."""
    with pytest.raises(NotAFieldOfficer, match="bound to a device"):
        CapabilityRequest(subject_id="officer-1", gn_division_code=KANDY_GN, device_id="  ")


async def test_a_capability_token_is_a_distinct_kind(token_service: TokenService) -> None:
    """Case 6, at the token layer: it cannot be presented where an access token is expected."""
    from sarana_shared.errors import Unauthenticated

    token = token_service.issue(
        "officer-1",
        roles=frozenset({Role.GN_OFFICER}),
        grants=capability_grants(KANDY_GN),
        kind="capability",
        device_id="handset-1",
    )

    principal = token_service.principal_from(token, expect="capability")
    assert principal.is_offline_capability

    with pytest.raises(Unauthenticated):
        token_service.principal_from(token, expect="access")


async def test_a_minted_capability_token_carries_exactly_one_grant(
    token_service: TokenService,
) -> None:
    """The whole authority of a lost field device, in one assertion."""
    token = token_service.issue(
        "officer-1",
        roles=frozenset({Role.GN_OFFICER}),
        grants=capability_grants(KANDY_GN),
        kind="capability",
        device_id="handset-1",
    )

    claims = token_service.verify(token, expect="capability")

    assert claims.grants == [f"assessment:write:GN:{KANDY_GN}"]
