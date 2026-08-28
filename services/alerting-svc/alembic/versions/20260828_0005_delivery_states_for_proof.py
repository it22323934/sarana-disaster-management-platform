"""delivery states the proof-of-delivery picture actually needs

Build file 09 requires a delivery summary of the form:

    "9,412 of 11,480 targeted handsets confirmed, 1,203 unconfirmed,
     865 no channel available"

Three buckets, and the schema as shipped in file 04 could express only two of them. Its
`delivery_receipt.status` CHECK allowed QUEUED, SENT, DELIVERED, READ, FAILED and EXPIRED
- none of which means "the channel accepted it and can never tell us whether it arrived",
and none of which means "this person has no channel at all".

Both are the whole point of the feature. USSD pushes and LoRa hops are frequently
unacknowledged, and folding them into QUEUED would report them as in-flight forever;
folding them into DELIVERED would report a village as warned when nobody knows. And "no
channel available" is precisely the list a DMC operator sends a vehicle to.

So two states are added:

  UNKNOWN     - the channel accepted it, and delivery cannot be confirmed. Counts against
                coverage, never towards it.
  NO_CHANNEL  - no channel could reach this person at all.

Revision ID: alerting_svc_0005
Revises: alerting_svc_0004
Created: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "alerting_svc_0005"
down_revision: str | None = "alerting_svc_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ("QUEUED", "SENT", "DELIVERED", "READ", "FAILED", "EXPIRED")
_NEW = (*_OLD, "UNKNOWN", "NO_CHANNEL")


def _values(states: tuple[str, ...]) -> str:
    return ", ".join(f"'{state}'" for state in states)


def upgrade() -> None:
    op.execute("ALTER TABLE alerting.delivery_receipt DROP CONSTRAINT ck_delivery_receipt_status_known")
    op.execute(
        "ALTER TABLE alerting.delivery_receipt ADD CONSTRAINT ck_delivery_receipt_status_known "
        f"CHECK (status IN ({_values(_NEW)}))"
    )
    op.execute(
        "COMMENT ON COLUMN alerting.delivery_receipt.status IS "
        "'UNKNOWN means the channel accepted the message and cannot confirm delivery - it "
        "counts against coverage, never towards it. NO_CHANNEL means nobody could reach "
        "this person at all, which is the list an operator sends a vehicle to.'"
    )


def downgrade() -> None:
    # Rows in the new states have no honest equivalent in the old vocabulary, so they are
    # not silently rewritten to something that would read as delivered. A downgrade with
    # such rows present fails, which is the correct outcome.
    op.execute("ALTER TABLE alerting.delivery_receipt DROP CONSTRAINT ck_delivery_receipt_status_known")
    op.execute(
        "ALTER TABLE alerting.delivery_receipt ADD CONSTRAINT ck_delivery_receipt_status_known "
        f"CHECK (status IN ({_values(_OLD)}))"
    )
