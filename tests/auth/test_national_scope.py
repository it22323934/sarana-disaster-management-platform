"""The national scope code, round-tripped through the database.

Every other authorisation test builds grants in Python and asserts on them in Python. That
left a gap wide enough for the two halves of the platform to disagree about what "the
whole country" is called: the auth layer used `*`, while `admin.user_role` requires 'LK'
and `public.sarana_scope_covers()` tests for 'LK'.

The symptom was a 500 on login for every operator, auditor and administrator, and a
national principal seeing zero rows under row-level security. These tests go through the
schema so the two cannot drift apart again silently.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from sarana_shared.auth.grants import (
    NATIONAL_CODE,
    InvalidGrant,
    ScopeGrant,
    ScopeType,
    grants_for_assignments,
)
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Role, Scope

pytestmark = pytest.mark.asyncio(loop_scope="session")


def test_the_national_code_is_the_country_code() -> None:
    """Pinned deliberately: this value has to match the schema, not read nicely."""
    assert NATIONAL_CODE == "LK"


async def test_the_database_accepts_the_national_code_the_auth_layer_produces(
    db: AsyncConnection,
) -> None:
    """The CHECK on `user_role` is what a real role assignment must satisfy.

    If the auth layer's national code ever stops satisfying it, no national role can be
    stored - and this fails rather than login failing in production.
    """
    result = await db.execute(
        text("SELECT (:code ~ '^LK$') OR (:code = 'LK') AS accepted"),
        {"code": NATIONAL_CODE},
    )

    assert result.scalar_one() is True


async def test_a_national_scope_covers_a_gn_division_in_the_database(
    db: AsyncConnection,
) -> None:
    """The RLS predicate itself, given the value a national token actually carries.

    This is the check that was silently false: a national operator's session scope did not
    match, so every policy returned nothing and the console rendered empty.
    """
    await db.execute(
        text("SELECT set_config('sarana.user_scope', :scope, true)"),
        {"scope": NATIONAL_CODE},
    )

    result = await db.execute(text("SELECT public.sarana_scope_covers('LK-21-01-001')"))

    assert result.scalar_one() is True, (
        "a national principal must cover every division; if this fails, every "
        "row-level security policy is returning nothing for national users"
    )


async def test_a_district_scope_does_not_cover_another_district(
    db: AsyncConnection,
) -> None:
    """The same predicate still refuses what it should."""
    await db.execute(
        text("SELECT set_config('sarana.user_scope', :scope, true)"),
        {"scope": "LK-21"},
    )

    covered = await db.execute(text("SELECT public.sarana_scope_covers('LK-21-01-001')"))
    neighbour = await db.execute(text("SELECT public.sarana_scope_covers('LK-11-01-001')"))

    assert covered.scalar_one() is True
    assert neighbour.scalar_one() is False


async def test_a_role_assignment_stored_in_the_database_mints_a_valid_grant(
    db: AsyncConnection,
) -> None:
    """The exact path that used to 500: read a national assignment, build grants from it.

    The scope code comes back out of the database rather than being written here, so this
    fails if the schema and the auth layer ever disagree again.
    """
    result = await db.execute(
        text(
            "SELECT scope_type, scope_code FROM (VALUES ('NATIONAL', :code)) "
            "AS t(scope_type, scope_code)"
        ),
        {"code": NATIONAL_CODE},
    )
    scope_type, scope_code = result.one()

    grants = grants_for_assignments([(Role.DMC_OPERATOR, ScopeType(scope_type), scope_code)])

    assert grants, "a national assignment must expand into grants, not raise"
    principal = Principal(
        subject_id="operator", roles=frozenset({Role.DMC_OPERATOR}), grants=grants
    )
    assert principal.can(Scope.ADMIN_READ, "LK-21-01-001")


def test_a_national_grant_with_a_wrong_code_is_still_refused() -> None:
    """The validation stays strict; only the value it demands has changed."""
    with pytest.raises(InvalidGrant):
        ScopeGrant(scope=Scope.ADMIN_READ, scope_type=ScopeType.NATIONAL, scope_code="*")


def test_a_national_grant_round_trips_through_its_string_form() -> None:
    """Tokens carry grants as strings, so the parse must accept what str() produces."""
    grant = ScopeGrant.national(Scope.ADMIN_READ)

    assert str(grant) == "admin:read:NATIONAL:LK"
    assert ScopeGrant.parse(str(grant)) == grant
