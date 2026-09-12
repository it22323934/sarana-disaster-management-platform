"""The authorisation rules that must hold, tested where each one is actually enforced.

These are the cases named in the build brief. Each is written against the layer that
enforces it: the scope model for RBAC, the database for row-level security and
segregation of duty, the domain layer for the approval threshold.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from sarana_shared.auth.grants import ScopeType, grants_for_assignments
from sarana_shared.auth.principal import Principal, StepUpRequired
from sarana_shared.auth.scopes import Role, Scope
from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now
from sarana_shared.errors import Forbidden
from tests.schema.factories import (
    append_chained,
    make_admin_hierarchy,
    make_entitlement,
    make_user_with_role,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

KANDY_GN = "LK-11-03-045"
NEIGHBOUR_GN = "LK-11-03-046"
KANDY_DS = "LK-11-03"
KANDY_DISTRICT = "LK-11"


def gn_officer(code: str = KANDY_GN) -> Principal:
    return Principal(
        subject_id=str(uuid7()),
        roles=frozenset({Role.GN_OFFICER}),
        grants=grants_for_assignments([(Role.GN_OFFICER, ScopeType.GN, code)]),
    )


def ds_approver(code: str = KANDY_DS) -> Principal:
    return Principal(
        subject_id=str(uuid7()),
        roles=frozenset({Role.DS_APPROVER}),
        grants=grants_for_assignments([(Role.DS_APPROVER, ScopeType.DS, code)]),
    )


async def test_a_gn_officer_cannot_read_a_neighbouring_division(
    db: AsyncConnection,
) -> None:
    """Case 1: 403, and the denial does not confirm the record exists."""
    officer = gn_officer()

    assert officer.can(Scope.ASSESSMENT_READ, KANDY_GN)

    with pytest.raises(Forbidden) as caught:
        officer.assert_can(Scope.ASSESSMENT_READ, NEIGHBOUR_GN)

    assert NEIGHBOUR_GN not in str(caught.value)


async def test_row_security_hides_the_neighbouring_division_too(
    db: AsyncConnection,
) -> None:
    """The same rule, at the layer that holds when the handler forgets its filter."""
    hierarchy = await make_admin_hierarchy(db)
    household_id = uuid7()
    await db.execute(
        text(
            "INSERT INTO admin.household "
            "(id, gn_division_id, reference_code, member_count, preferred_language) "
            "VALUES (:id, :gn_id, :ref, 4, 'ta')"
        ),
        {"id": household_id, "gn_id": hierarchy["gn_id"], "ref": f"HH-{household_id.hex[-12:]}"},
    )

    await db.execute(text("SET LOCAL ROLE sarana_app"))
    await db.execute(text("SET LOCAL sarana.user_scope = 'LK-11-03-046'"))

    result = await db.execute(text("SELECT count(*) FROM admin.household"))

    assert result.scalar_one() == 0


async def test_a_gn_officer_cannot_approve_even_in_their_own_division() -> None:
    """Case 2: holding the area is not the same as holding the permission."""
    officer = gn_officer()

    with pytest.raises(Forbidden, match="entitlement:approve_ds"):
        officer.assert_can(Scope.ENTITLEMENT_APPROVE_DS, KANDY_GN)


async def test_the_assessor_cannot_approve_their_own_entitlement(
    db: AsyncConnection,
) -> None:
    """Case 3: segregation of duty, enforced by the database, not only by the domain."""
    hierarchy = await make_admin_hierarchy(db)
    entitlement = await make_entitlement(db, hierarchy)
    assessor = entitlement["officer_id"]

    with pytest.raises(DBAPIError, match="may not also approve"):
        await append_chained(
            db,
            schema="aid",
            table="approval",
            columns={
                "id": uuid7(),
                "entitlement_id": entitlement["entitlement_id"],
                "level": "DS",
                "approver_id": assessor,
                "decision": "APPROVED",
            },
        )


async def test_one_person_cannot_be_both_levels_of_approval(
    db: AsyncConnection,
) -> None:
    """The second level exists to be a second pair of eyes."""
    hierarchy = await make_admin_hierarchy(db)
    entitlement = await make_entitlement(db, hierarchy)
    approver = await make_user_with_role(db, "DS_APPROVER", KANDY_DS)

    await append_chained(
        db,
        schema="aid",
        table="approval",
        columns={
            "id": uuid7(),
            "entitlement_id": entitlement["entitlement_id"],
            "level": "DS",
            "approver_id": approver,
            "decision": "APPROVED",
        },
    )

    with pytest.raises(DBAPIError, match="already approved"):
        await append_chained(
            db,
            schema="aid",
            table="approval",
            columns={
                "id": uuid7(),
                "entitlement_id": entitlement["entitlement_id"],
                "level": "DISTRICT",
                "approver_id": approver,
                "decision": "APPROVED",
            },
        )


async def test_an_amount_above_the_threshold_needs_district_approval() -> None:
    """Case 4: one signature is not enough above the threshold."""
    from ledger_svc.domain.approval import ApprovalIncomplete, ApprovalState

    above = ApprovalState(
        amount_lkr_cents=100_000_000,
        assessed_by=uuid7(),
        ds_approver_id=uuid7(),
    )

    assert above.requires_district()
    assert not above.is_fully_approved()

    with pytest.raises(ApprovalIncomplete, match="District Secretariat"):
        above.assert_ready_to_disburse()


async def test_an_amount_below_the_threshold_needs_only_the_ds() -> None:
    """The threshold cuts both ways: a second signature on every small payment would put
    a district officer in the path of thousands of household disbursements."""
    from ledger_svc.domain.approval import ApprovalState

    below = ApprovalState(
        amount_lkr_cents=10_000_000,
        assessed_by=uuid7(),
        ds_approver_id=uuid7(),
    )

    assert below.is_fully_approved()
    below.assert_ready_to_disburse()


async def test_releasing_funds_without_a_fresh_second_factor_is_refused() -> None:
    """Case 5: a valid session is not enough for a human gate."""
    approver = Principal(
        subject_id=str(uuid7()),
        roles=frozenset({Role.DISTRICT_APPROVER}),
        grants=grants_for_assignments(
            [(Role.DISTRICT_APPROVER, ScopeType.DISTRICT, KANDY_DISTRICT)]
        ),
        step_up_at=None,
    )

    assert approver.can(Scope.DISBURSEMENT_RELEASE, KANDY_GN)

    with pytest.raises(StepUpRequired):
        approver.assert_may_commit_gate(Scope.DISBURSEMENT_RELEASE, KANDY_GN)


async def test_a_lapsed_second_factor_does_not_authorise_a_gate() -> None:
    """Six minutes is outside the five-minute window, and the window is the point."""
    from datetime import timedelta

    stale = utc_now() - timedelta(minutes=6)
    approver = Principal(
        subject_id=str(uuid7()),
        roles=frozenset({Role.DISTRICT_APPROVER}),
        grants=grants_for_assignments(
            [(Role.DISTRICT_APPROVER, ScopeType.DISTRICT, KANDY_DISTRICT)]
        ),
        step_up_at=stale,
    )

    with pytest.raises(StepUpRequired):
        approver.assert_may_commit_gate(Scope.DISBURSEMENT_RELEASE, KANDY_GN)


async def test_a_fresh_second_factor_authorises_the_gate() -> None:
    approver = Principal(
        subject_id=str(uuid7()),
        roles=frozenset({Role.DISTRICT_APPROVER}),
        grants=grants_for_assignments(
            [(Role.DISTRICT_APPROVER, ScopeType.DISTRICT, KANDY_DISTRICT)]
        ),
        step_up_at=utc_now(),
    )

    approver.assert_may_commit_gate(Scope.DISBURSEMENT_RELEASE, KANDY_GN)


async def test_an_agent_can_never_pass_a_human_gate() -> None:
    """An agent has no second factor and never will. Say so plainly."""
    agent = Principal(
        subject_id="forecast-agent",
        roles=frozenset({Role.AGENT}),
        grants=grants_for_assignments([(Role.AGENT, ScopeType.NATIONAL, "LK")]),
        is_machine=True,
        step_up_at=utc_now(),
    )

    with pytest.raises(Forbidden, match="cannot be taken by an agent"):
        agent.assert_may_commit_gate(Scope.DISPATCH_COMMIT, KANDY_GN)
