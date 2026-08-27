"""event backbone: envelope field rename, trace context, and the shared event tables

Build file 06 renamed two envelope fields and added a third:

  type   -> event_type   so it reads as a field name rather than a Python builtin
  source -> producer     "source" already means a hazard feed elsewhere in the schema
  trace_context          W3C traceparent, so a replay rejoins the original trace

`correlation_id` also becomes a real uuid column rather than text. It was always a UUIDv7
string; typing it as one stops anything writing a correlation id that is not one, which
matters because the value travels into logs, events and audit entries alike.

`outbox.processed_event` and `outbox.dead_letter` are shared by every service and created
here idempotently, so whichever service migrates first creates them and the rest are
no-ops. That keeps the migration chains independent of each other.

Revision ID: core_api_0005
Revises: core_api_0004
Created: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from sarana_shared.db.sql import SHARED_EVENT_TABLES

revision: str = "core_api_0005"
down_revision: str | None = "core_api_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "outbox.core_api_event"


def upgrade() -> None:
    for statement in SHARED_EVENT_TABLES:
        op.execute(statement)

    op.execute(f"ALTER TABLE {TABLE} RENAME COLUMN type TO event_type")
    op.execute(f"ALTER TABLE {TABLE} RENAME COLUMN source TO producer")
    op.execute(
        f"ALTER TABLE {TABLE} ADD COLUMN trace_context jsonb NOT NULL DEFAULT '{{}}'::jsonb"
    )
    # USING, because the existing values are UUIDv7 text and would otherwise fail the cast.
    op.execute(
        f"ALTER TABLE {TABLE} ALTER COLUMN correlation_id TYPE uuid "
        "USING correlation_id::uuid"
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLE} TO sarana_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON outbox.processed_event TO sarana_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON outbox.dead_letter TO sarana_app")


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE {TABLE} ALTER COLUMN correlation_id TYPE varchar(64) "
        "USING correlation_id::text"
    )
    op.execute(f"ALTER TABLE {TABLE} DROP COLUMN trace_context")
    op.execute(f"ALTER TABLE {TABLE} RENAME COLUMN producer TO source")
    op.execute(f"ALTER TABLE {TABLE} RENAME COLUMN event_type TO type")

    # The shared tables are left in place. They belong to every service, and dropping
    # them here would break the four that are still migrated.
