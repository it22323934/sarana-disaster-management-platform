"""per-device sync cursor, so a gap in a field device operation log pauses rather than skips

Build file 10 requires that operations from a Field Companion apply in `seq` order per
device, and that "a gap in the sequence pauses that device's sync and reports which `seq`
is missing, rather than applying out of order".

Enforcing that needs one piece of state the assessments themselves cannot supply: the
highest seq the server has accepted from each device. Without it, a batch arriving as
8, 9, 10 after 7 was lost looks identical to a batch that is simply the next three
operations, and the officer's record gets rebuilt out of an update whose create never
arrived.

`last_applied_seq` only ever moves forward, enforced by a CHECK on the update path in the
application and by the fact that `plan()` never returns a lower cursor. A device that is
reset gets a new `device_id`; reusing one and rewinding the cursor would let a replayed
log overwrite work already accepted.

Revision ID: ledger_svc_0007
Revises: ledger_svc_0006
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ledger_svc_0007"
down_revision: str | None = "ledger_svc_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "aid"


def upgrade() -> None:
    op.create_table(
        "device_sync_cursor",
        sa.Column(
            "device_id",
            sa.String(length=64),
            primary_key=True,
            comment="The Field Companion installation, not the handset and not the officer",
        ),
        sa.Column("last_applied_seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "blocked_on_seq",
            sa.BigInteger(),
            nullable=True,
            comment="The seq this device has not sent. Non-null means its sync is paused.",
        ),
        sa.CheckConstraint("last_applied_seq >= 0", name="cursor_non_negative"),
        sa.CheckConstraint(
            "blocked_on_seq IS NULL OR blocked_on_seq > last_applied_seq",
            name="block_is_ahead_of_the_cursor",
        ),
        schema=SCHEMA,
    )

    op.create_index(
        "ix_device_sync_cursor_blocked",
        "device_sync_cursor",
        ["blocked_on_seq"],
        unique=False,
        schema=SCHEMA,
        postgresql_where=sa.text("blocked_on_seq IS NOT NULL"),
    )

    op.execute(
        f"COMMENT ON TABLE {SCHEMA}.device_sync_cursor IS "
        "'Highest operation seq accepted from each field device. Moves forward only.'"
    )


def downgrade() -> None:
    op.drop_index("ix_device_sync_cursor_blocked", table_name="device_sync_cursor", schema=SCHEMA)
    op.drop_table("device_sync_cursor", schema=SCHEMA)
