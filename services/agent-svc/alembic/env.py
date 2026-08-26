"""Alembic environment for agent-svc.

Runs against the async engine and restricts autogenerate to the schemas this service
owns (agent), so a migration here never proposes to drop another service's
tables just because they are absent from this metadata.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Importing the models package registers every table on Base.metadata.
import agent_svc.repo  # noqa: F401
from sarana_shared.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Schemas this service owns. Anything outside them is another service's business.
OWNED_SCHEMAS: set[str] = {"agent"}


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """Restrict autogenerate to this service's schemas."""
    schema = getattr(obj, "schema", None)
    if type_ == "table":
        return schema in OWNED_SCHEMAS
    parent_schema = getattr(getattr(obj, "table", None), "schema", None)
    return parent_schema in OWNED_SCHEMAS if parent_schema is not None else True


def _database_url() -> str:
    url = os.environ.get("SARANA_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "SARANA_DATABASE_URL is not set. Alembic needs it to reach the database."
        )
    return url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live connection."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_object=include_object,
        version_table_schema="agent",
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=include_object,
        version_table_schema="agent",
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Apply migrations against the live database."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()

    engine = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
