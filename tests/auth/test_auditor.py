"""The auditor is read-only structurally, not by an application flag.

An auditor whose read-only-ness is a boolean in the application stays read-only right up
until someone writes a handler that forgets to check it. This is a Postgres role holding
SELECT and nothing else: there is no INSERT for a bug to reach.

That distinction matters because the auditor is the role most likely to be handed to
somebody outside the operating team - a ministry reviewer, an external audit firm - and
the platform's transparency claim depends on them being able to look at everything while
being able to change nothing.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from sarana_shared.auth.scopes import ROLE_SCOPES, Role, Scope
from sarana_shared.domain.ids import uuid7

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Every schema the auditor may read.
READABLE_SCHEMAS = ("admin", "aid", "incident", "alerting", "hazard", "resilience", "audit")


async def test_the_auditor_role_exists(db: AsyncConnection) -> None:
    result = await db.execute(
        text("SELECT count(*) FROM pg_roles WHERE rolname = 'sarana_auditor'")
    )

    assert result.scalar_one() == 1


async def test_the_auditor_holds_select_and_nothing_else(db: AsyncConnection) -> None:
    """Case 8: the grant, not the flag."""
    result = await db.execute(
        text(
            "SELECT DISTINCT privilege_type "
            "FROM information_schema.role_table_grants "
            "WHERE grantee = 'sarana_auditor' "
            "ORDER BY 1"
        )
    )
    privileges = {row[0] for row in result}

    assert privileges == {"SELECT"}, f"auditor holds more than SELECT: {sorted(privileges)}"


async def test_the_auditor_can_read_every_schema(db: AsyncConnection) -> None:
    """Read-only is only useful if it is also read-everything."""
    result = await db.execute(
        text(
            "SELECT DISTINCT table_schema "
            "FROM information_schema.role_table_grants "
            "WHERE grantee = 'sarana_auditor' AND privilege_type = 'SELECT'"
        )
    )
    schemas = {row[0] for row in result}

    assert set(READABLE_SCHEMAS) <= schemas, f"missing: {sorted(set(READABLE_SCHEMAS) - schemas)}"


async def test_an_auditor_insert_fails_at_the_database(db: AsyncConnection) -> None:
    """Not a 403 from a handler. A permission error from PostgreSQL."""
    await db.execute(text("SET LOCAL ROLE sarana_auditor"))

    with pytest.raises(DBAPIError, match="permission denied"):
        await db.execute(
            text(
                "INSERT INTO aid.anomaly_flag "
                "(id, subject_type, subject_id, detector, detector_version, score, rationale) "
                "VALUES (:id, 'ASSESSMENT', :subject, 'd', '1.0', 0.5, "
                ' \'{"pattern": "x"}\'::jsonb)'
            ),
            {"id": uuid7(), "subject": uuid7()},
        )


async def test_an_auditor_update_fails_at_the_database(db: AsyncConnection) -> None:
    await db.execute(text("SET LOCAL ROLE sarana_auditor"))

    with pytest.raises(DBAPIError, match="permission denied"):
        await db.execute(text("UPDATE admin.app_user SET status = 'SUSPENDED'"))


async def test_an_auditor_delete_fails_at_the_database(db: AsyncConnection) -> None:
    await db.execute(text("SET LOCAL ROLE sarana_auditor"))

    with pytest.raises(DBAPIError, match="permission denied"):
        await db.execute(text("DELETE FROM audit.audit_entry"))


async def test_an_auditor_can_still_read(db: AsyncConnection) -> None:
    """The point of the role. Refusing writes must not refuse the job."""
    await db.execute(text("SET LOCAL ROLE sarana_auditor"))

    result = await db.execute(text("SELECT count(*) FROM aid.disbursement"))

    assert result.scalar_one() >= 0


async def test_the_auditor_scope_set_carries_no_write_permission() -> None:
    """The application layer agrees with the database, rather than contradicting it."""
    write_scopes = {
        Scope.ASSESSMENT_WRITE,
        Scope.INCIDENT_WRITE,
        Scope.ENTITLEMENT_APPROVE_DS,
        Scope.ENTITLEMENT_APPROVE_DISTRICT,
        Scope.DISBURSEMENT_RELEASE,
        Scope.DISPATCH_COMMIT,
        Scope.ALERT_DISPATCH,
        Scope.RESILIENCE_WRITE,
    }

    assert not ROLE_SCOPES[Role.AUDITOR] & write_scopes
