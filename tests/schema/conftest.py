"""Fixtures for the schema constraint suite.

These tests exercise the database, not the ORM. Every constraint in build file 04 is
proved by attempting the violation and asserting the failure - a constraint with no test
showing it fires does not count as delivered.

Migrations are applied through the same `alembic upgrade head` that `make migrate` runs,
so the suite tests the real path rather than a metadata `create_all` that would silently
skip every trigger, generated column, policy and grant.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from sarana_shared.db.session import DatabaseSettings, create_engine

REPO_ROOT = Path(__file__).resolve().parents[2]

# Order matters only for readability; each chain is independent by construction.
DATA_SERVICES = ("core-api", "incident-svc", "alerting-svc", "ledger-svc", "agent-svc")


@pytest.fixture(scope="session")
def migrated_url(postgres_url: str) -> str:
    """Apply every service's migrations to the test database and return its DSN."""
    environment = {**os.environ, "SARANA_DATABASE_URL": postgres_url}

    for service in DATA_SERVICES:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPO_ROOT / "services" / service,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.fail(f"migrations failed for {service}:\n{result.stdout}\n{result.stderr}")

    return postgres_url


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def schema_engine(migrated_url: str) -> AsyncIterator[AsyncEngine]:
    """Engine bound to the fully migrated test database."""
    engine = create_engine(
        DatabaseSettings(url=migrated_url, application_name="sarana-schema-tests")
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def db(schema_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """A connection inside a transaction that is always rolled back.

    Constraint tests deliberately provoke errors. Rolling back means one test's failed
    INSERT cannot leave a half-built row for the next one to trip over, and the hash
    chains stay empty between tests so their genesis behaviour is testable repeatedly.
    """
    async with schema_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()
