"""store prev_anchor_hash, so removing a whole day is as detectable as altering one row

ADR-005 chains the anchors as well as the entries: each day's record references the
previous day's, so deleting an entire day breaks the anchor chain the same way deleting a
row breaks the entry chain. `sarana_shared.crypto.merkle.Anchor` carries the field and
`anchor_hash()` computes it - but `aid.ledger_anchor` had nowhere to put it, so the value
went into the S3 object and was lost from the published feed.

That left the weaker of the two guarantees in place. A verifier could check every root
against the entries it covers, and still not notice that Tuesday was missing entirely.

Revision ID: ledger_svc_0009
Revises: ledger_svc_0008
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ledger_svc_0009"
down_revision: str | None = "ledger_svc_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "aid"


def upgrade() -> None:
    op.add_column(
        "ledger_anchor",
        sa.Column(
            "prev_anchor_hash",
            sa.Text(),
            nullable=True,
            comment="The previous day's anchor_hash. NULL only for the first anchor ever.",
        ),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "prev_anchor_hash_is_sha256",
        "ledger_anchor",
        "prev_anchor_hash IS NULL OR prev_anchor_hash ~ '^[0-9a-f]{64}$'",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "prev_anchor_hash_is_sha256", "ledger_anchor", type_="check", schema=SCHEMA
    )
    op.drop_column("ledger_anchor", "prev_anchor_hash", schema=SCHEMA)
