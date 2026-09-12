"""prerequisites: extensions, shared SQL objects, and the schemas agent-svc owns

Every data-owning service applies the same shared objects here. Each statement is
idempotent, so whichever service migrates first creates them and the rest are no-ops.
That is deliberate: it removes any ordering dependency between service migration chains,
so `alembic upgrade head` works in any order and in isolation.

Revision ID: agent_svc_0001
Revises:
Created: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from sarana_shared.db.sql import REQUIRED_EXTENSIONS, SHARED_OBJECTS

revision: str = "agent_svc_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Schemas this service owns outright.
OWNED_SCHEMAS: tuple[str, ...] = ("hazard",)

# Shared by every service. Never dropped on downgrade - see `downgrade`.
OUTBOX_SCHEMA = "outbox"


def upgrade() -> None:
    for extension in REQUIRED_EXTENSIONS:
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")

    for statement in SHARED_OBJECTS:
        op.execute(statement)

    for schema in (*OWNED_SCHEMAS, OUTBOX_SCHEMA):
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        # The application role needs to reach into the schema; the tables inside it are
        # granted individually by the migration that creates them.
        op.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO sarana_app')
        op.execute(f'GRANT USAGE, CREATE ON SCHEMA "{schema}" TO sarana_migrator')

    # The auditor is read-only structurally, not by an application flag: there is no
    # INSERT for the role to lose. Granted here, per owned schema, so no service's
    # migration chain depends on another having already created its schema.
    for schema in OWNED_SCHEMAS:
        op.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO sarana_auditor')
        op.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO sarana_auditor')
        op.execute(
            f'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA "{schema}" '
            "FROM sarana_auditor"
        )
        # Tables this chain creates after this migration inherit the same shape.
        op.execute(
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
            "GRANT SELECT ON TABLES TO sarana_auditor"
        )

    # Helper functions are called from CHECK constraints and RLS policies in every
    # schema, so the application role must be able to execute them.
    op.execute("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO sarana_app")


def downgrade() -> None:
    # RESTRICT, never CASCADE: a downgrade must fail loudly rather than silently drop
    # tables a later migration created.
    for schema in reversed(OWNED_SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" RESTRICT')

    # The outbox schema, the shared functions and the roles are deliberately left in
    # place. They belong to every service, and tearing them down here would break the
    # four services that are still migrated.
