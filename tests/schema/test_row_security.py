"""Row-level security: the control that holds when the application is wrong.

Application-level scope checks are the first line and they will usually be right. These
tests cover the case where they are not - a handler that forgets its `WHERE` clause
returns nothing instead of returning every household in the country.

The scope comes from a `SET LOCAL sarana.user_scope`, set by the auth middleware inside
the request transaction. `SET LOCAL` is what stops it leaking to the next request on a
pooled connection.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from sarana_shared.db.sql import SCOPE_SETTING
from sarana_shared.domain.ids import uuid7
from tests.schema.factories import TRILINGUAL, make_admin_hierarchy, public_ref

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _set_scope(db: AsyncConnection, scope: str) -> None:
    await db.execute(text(f"SET LOCAL {SCOPE_SETTING} = '{scope}'"))


async def _become_the_application(db: AsyncConnection) -> None:
    """Switch to the application role for the rest of the transaction.

    Superusers bypass row-level security entirely, and FORCE does not change that. The
    test suite connects as the owner in order to build fixtures, so a policy test that
    stayed as the owner would pass no matter what the policy said. This is also how the
    application itself must connect: never as the owner.
    """
    await db.execute(text("SET LOCAL ROLE sarana_app"))


@pytest.mark.parametrize(
    ("scope", "target", "covered"),
    [
        ("LK", "LK-11-03-045", True),
        ("LK-11", "LK-11-03-045", True),
        ("LK-11-03", "LK-11-03-045", True),
        ("LK-11-03-045", "LK-11-03-045", True),
        ("LK-12", "LK-11-03-045", False),
        ("LK-11-04", "LK-11-03-045", False),
        # Segment-aware: the trailing hyphen is what stops a truncated code matching.
        ("LK-11-0", "LK-11-03", False),
    ],
)
async def test_scope_containment_matches_the_application_rule(
    db: AsyncConnection, scope: str, target: str, covered: bool
) -> None:
    """The database predicate and `contains()` in Python must agree exactly.

    Two implementations of one rule that disagree is worse than one implementation,
    because the disagreement only shows up on the row that matters.
    """
    await _set_scope(db, scope)

    result = await db.execute(
        text("SELECT public.sarana_scope_covers(:target)"), {"target": target}
    )

    assert result.scalar_one() is covered


async def test_an_unset_scope_covers_nothing(db: AsyncConnection) -> None:
    """The safe default. A connection that forgot to set a scope sees no rows."""
    result = await db.execute(text("SELECT public.sarana_scope_covers('LK-11-03-045')"))

    assert result.scalar_one() is False


async def test_the_owner_bypasses_row_security_which_is_why_the_app_is_not_the_owner(
    db: AsyncConnection,
) -> None:
    """Documents the reason the application connects as sarana_app.

    A superuser is not subject to any policy, so deploying the services with owner
    credentials would silently disable every protection in this module.
    """
    result = await db.execute(text("SELECT usesuper FROM pg_user WHERE usename = current_user"))

    assert result.scalar_one() is True, (
        "the fixture connection is expected to be the owner; the policy tests switch "
        "to sarana_app precisely because this one is not subject to RLS"
    )


async def test_a_household_outside_the_scope_is_invisible(db: AsyncConnection) -> None:
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

    await _become_the_application(db)

    await _set_scope(db, "LK-11-03")
    in_scope = await db.execute(
        text("SELECT count(*) FROM admin.household WHERE id = :id"), {"id": household_id}
    )
    assert in_scope.scalar_one() == 1

    await _set_scope(db, "LK-12")
    out_of_scope = await db.execute(
        text("SELECT count(*) FROM admin.household WHERE id = :id"), {"id": household_id}
    )
    assert out_of_scope.scalar_one() == 0


async def test_an_incident_outside_the_scope_is_invisible(db: AsyncConnection) -> None:
    incident_id = uuid7()
    await db.execute(
        text(
            "INSERT INTO incident.incident "
            "(id, public_ref, gn_division_id, gn_division_code, type, severity, "
            " status, summary, correlation_id) "
            "VALUES (:id, :ref, :gn_id, 'LK-11-03-045', 'FLOOD', 4, 'REPORTED', "
            f" '{TRILINGUAL}'::jsonb, 'test')"
        ),
        {
            "id": incident_id,
            "ref": public_ref("INC", incident_id),
            "gn_id": uuid7(),
        },
    )

    await _become_the_application(db)

    await _set_scope(db, "LK-11")
    visible = await db.execute(
        text("SELECT count(*) FROM incident.incident WHERE id = :id"), {"id": incident_id}
    )
    assert visible.scalar_one() == 1

    await _set_scope(db, "LK-02")
    hidden = await db.execute(
        text("SELECT count(*) FROM incident.incident WHERE id = :id"), {"id": incident_id}
    )
    assert hidden.scalar_one() == 0


async def test_row_security_is_enabled_and_forced_on_the_protected_tables(
    db: AsyncConnection,
) -> None:
    """FORCE matters: without it the table owner bypasses the policy silently."""
    result = await db.execute(
        text(
            "SELECT n.nspname || '.' || c.relname, c.relrowsecurity, c.relforcerowsecurity "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE (n.nspname, c.relname) IN "
            "  (('admin','household'), ('incident','incident'), ('aid','damage_assessment')) "
            "ORDER BY 1"
        )
    )
    rows = result.all()

    assert len(rows) == 3
    for name, enabled, forced in rows:
        assert enabled, f"row security is not enabled on {name}"
        assert forced, f"row security is not forced on {name}"
