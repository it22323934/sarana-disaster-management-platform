"""a schema LangGraph's checkpointer may create its own tables in

LangGraph's `AsyncPostgresSaver.setup()` issues DDL at service boot, and it runs as the
application role because that is the connection the service holds. Every other schema in
this database grants CREATE to `sarana_migrator` alone — the application role owns no DDL
anywhere, deliberately — so `setup()` failed with `permission denied for schema public`
and agent-svc could not start at all.

Rather than loosening `public`, the checkpointer gets a schema of its own and the
application role is allowed to create inside that one only.

**Why this does not weaken the row-level security discipline.** What lives here is
LangGraph's internal machinery: `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` and
its `checkpoint_migrations` version table. No domain table, no household, no policy. The
application role still cannot create anything in `public` or in any schema holding data an
RLS policy protects, which is the property that matters — a role that can create a table
in a protected schema can create one without a policy on it.

**Why `setup()` is still allowed to run rather than the tables being created here.**
LangGraph owns this schema's shape and changes it between versions; a copy of its DDL
pinned in an Alembic revision is a copy that goes stale silently, and the failure would
land on the first interrupt rather than at boot. So the migration creates the room and
LangGraph furnishes it.

The service reaches it by search_path — see `runtime/checkpoint.py`.

Revision ID: agent_svc_0005
Revises: agent_svc_0004
Created: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "agent_svc_0005"
down_revision: str | None = "agent_svc_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Named for what it holds rather than for LangGraph, so swapping the checkpointer
# implementation does not leave a schema named after a library nobody uses any more.
CHECKPOINT_SCHEMA = "agent_checkpoint"


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{CHECKPOINT_SCHEMA}"')

    # CREATE, and only here. `setup()` is idempotent and runs on every boot, so the grant
    # is permanent rather than something to withdraw once the tables exist.
    op.execute(f'GRANT USAGE, CREATE ON SCHEMA "{CHECKPOINT_SCHEMA}" TO sarana_app')
    op.execute(f'GRANT USAGE, CREATE ON SCHEMA "{CHECKPOINT_SCHEMA}" TO sarana_migrator')

    # The auditor reads paused runs when reconstructing who approved what. Checkpoint rows
    # are the only record of a decision's state between the interrupt and the resume.
    op.execute(f'GRANT USAGE ON SCHEMA "{CHECKPOINT_SCHEMA}" TO sarana_auditor')
    op.execute(
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{CHECKPOINT_SCHEMA}" '
        "GRANT SELECT ON TABLES TO sarana_auditor"
    )


def downgrade() -> None:
    # RESTRICT, never CASCADE. These rows are every run paused on a human decision, and a
    # downgrade that dropped them would discard approvals nobody has answered yet.
    op.execute(f'DROP SCHEMA IF EXISTS "{CHECKPOINT_SCHEMA}" RESTRICT')
