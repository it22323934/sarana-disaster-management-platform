"""a released payment can fail, so the ledger needs a way to say so

About three per cent of transfers fail *after* the rail accepted them - account closed,
dormant, name mismatch - and by then `aid.disbursement` has already recorded a release and
published its hash. The table is append-only, so the record cannot be edited and must not
be: an auditor has to be able to see that the state believed it had paid this household.

The correction is therefore a **compensating entry**: a new row in a new table that
references the original, carries the rail's reason, and is hash-chained the same way. The
docstring on `aid.disbursement` has said "corrections are new compensating entries, never
edits" since file 04. This migration is what makes that sentence true.

Four decisions inside it.

**A separate table, not a negative-amount disbursement.** `aid.disbursement` constrains
`amount_lkr_cents > 0` and holds one row per entitlement, and both of those are real
invariants that stop a double-pay bug. More importantly, `ledger_svc.domain.ledger_entry`
defines the exact field set that is hashed *and* published *and* anchored - adding a field
to it would change the recomputed hash of every entry ever written and break
`tools/sarana-verify` against all of history. A reversal with its own payload shape on its
own chain cannot disturb that. It is also how double-entry bookkeeping has always worked.

**The reversal chain commits to the link.** `disbursement_id` is inside the hashed payload,
so a reversal cannot later be denied or re-pointed at a different payment.

**`aid.disbursement.reversed_at` is a back-pointer, not the record.** It exists so the
release gate can ask "is there a live payment for this entitlement?" in one indexed query.
It is outside the hashed payload for exactly the reason the citizen confirmation columns
are: the entry means "this money was released, on this date, by this person", and that
stays true. What happened afterwards is a fact *about* the entry, recorded in its own
chained row. A ledger whose entry hash changed when a bank bounced a payment would fail
verification for an honest reason.

**A reversed payment frees the entitlement to be paid again.** `uq_disbursement_entitlement`
becomes a partial unique index over live rows only. Without that, reversing a failed
payment would permanently bar the household from receiving the money they are owed - which
would make the reversal worse than leaving the bad record standing.

Revision ID: ledger_svc_0010
Revises: ledger_svc_0009
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ledger_svc_0010"
down_revision: str | None = "ledger_svc_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "aid"

# Why a rail returned money it had accepted. A closed list because each one has a
# different remedy, and the grievance raised for the household should say which applies:
# "payment failed" tells a family nothing they can act on.
REVERSAL_REASONS = (
    "ACCOUNT_CLOSED",
    "ACCOUNT_DORMANT",
    "NAME_MISMATCH",
    "INVALID_ACCOUNT",
    "LIMIT_EXCEEDED",
    "RAIL_RETURNED",
    "DUPLICATE_PAYMENT",
    "ADMINISTRATIVE_ERROR",
)

# Every column of `aid.disbursement` that is not an additive later fact. Extends the list
# 0008 introduced: `reversed_at` joins the confirmation columns as the second - and, for
# now, last - thing that may be written after the row lands.
IMMUTABLE_COLUMNS = (
    "id",
    "seq",
    "entitlement_id",
    "amount_lkr_cents",
    "released_by",
    "released_at",
    "payment_rail",
    "payment_ref",
    "prev_hash",
    "entry_hash",
    "correlation_id",
    "created_at",
)

WRITABLE_COLUMNS = (
    "citizen_confirmed",
    "citizen_confirmed_at",
    "citizen_confirm_channel",
    "reversed_at",
)

# `SYSTEM` is new. A grievance the platform raises on a household's behalf - because a bank
# returned their payment - arrived on no citizen channel at all, and recording it as SMS
# would put a falsehood in the field an officer uses to decide how to reply.
GRIEVANCE_CHANNELS = ("SMS", "USSD", "APP", "IN_PERSON", "PHONE", "WEB", "SYSTEM")

_OLD_ROW = ", ".join(f"OLD.{column}" for column in IMMUTABLE_COLUMNS)
_NEW_ROW = ", ".join(f"NEW.{column}" for column in IMMUTABLE_COLUMNS)

# Replaces `aid.disbursement_confirmation_only()`. Same shape, one more permitted fact.
ADDITIVE_ONLY = f"""
CREATE OR REPLACE FUNCTION aid.disbursement_additive_only()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'aid.disbursement is append-only: DELETE is not permitted. Corrections are '
            'new compensating entries in aid.disbursement_reversal, never removals.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF ROW({_NEW_ROW}) IS DISTINCT FROM ROW({_OLD_ROW}) THEN
        RAISE EXCEPTION
            'aid.disbursement is append-only apart from the citizen confirmation columns '
            'and reversed_at. Correct a payment with a compensating entry, never an edit.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF OLD.citizen_confirmed AND NOT NEW.citizen_confirmed THEN
        RAISE EXCEPTION
            'a citizen confirmation cannot be withdrawn. If the household now says the '
            'money did not arrive, that is a grievance against this disbursement.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    -- A reversal is a fact, not a status. Un-reversing would let an operator make a
    -- failed payment look successful again, which is precisely what the compensating
    -- entry exists to prevent.
    IF OLD.reversed_at IS NOT NULL AND NEW.reversed_at IS DISTINCT FROM OLD.reversed_at THEN
        RAISE EXCEPTION
            'reversed_at is set once. A reversal already recorded against this '
            'disbursement cannot be moved or cleared.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$function$;
"""

# The back-pointer is maintained by the database rather than the application, so a reversal
# row and a stale `reversed_at` cannot disagree. The application would have to remember;
# the trigger cannot forget.
STAMP_REVERSAL = """
CREATE OR REPLACE FUNCTION aid.stamp_disbursement_reversed()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    UPDATE aid.disbursement
       SET reversed_at = NEW.reversed_at
     WHERE id = NEW.disbursement_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'cannot reverse disbursement %: no such row', NEW.disbursement_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    RETURN NEW;
END;
$function$;
"""


def upgrade() -> None:
    reasons = ", ".join(f"'{reason}'" for reason in REVERSAL_REASONS)

    op.create_table(
        "disbursement_reversal",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("disbursement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entitlement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount_lkr_cents", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column(
            "rail_reference",
            sa.String(length=128),
            nullable=True,
            comment="The rail's own reference for the transfer that failed, so the "
            "reversal can be reconciled against the bank's statement.",
        ),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "grievance_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="The grievance raised on the household's behalf. NOT NULL because the "
            "case is opened before the entry is written: a reversal that could exist "
            "without one is a household nobody told, and this table is append-only so it "
            "could never be filled in afterwards.",
        ),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("prev_hash", sa.Text(), nullable=True),
        sa.Column("entry_hash", sa.Text(), nullable=True),
        sa.CheckConstraint("amount_lkr_cents > 0", name=op.f("ck_reversal_amount_positive")),
        sa.CheckConstraint(f"reason IN ({reasons})", name=op.f("ck_reversal_reason_known")),
        sa.ForeignKeyConstraint(
            ["disbursement_id"],
            [f"{SCHEMA}.disbursement.id"],
            name=op.f("fk_reversal_disbursement"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["entitlement_id"],
            [f"{SCHEMA}.entitlement.id"],
            name=op.f("fk_reversal_entitlement"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_disbursement_reversal")),
        # A payment is reversed once. A rail reporting the same failure twice is the same
        # failure, and a second reversal would double-count the money coming back.
        sa.UniqueConstraint("disbursement_id", name="uq_reversal_disbursement"),
        sa.UniqueConstraint("seq", name="uq_reversal_seq"),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_aid_disbursement_reversal_entitlement_id"),
        "disbursement_reversal",
        ["entitlement_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_reversal_seq", "disbursement_reversal", ["seq"], unique=False, schema=SCHEMA
    )

    # The published chain. Same trigger as every other chained table: the application
    # supplies both hashes and the database enforces that prev_hash is really the tail.
    op.execute(
        "CREATE TRIGGER hash_chain BEFORE INSERT ON aid.disbursement_reversal "
        "FOR EACH ROW EXECUTE FUNCTION public.sarana_enforce_supplied_chain()"
    )
    # Append-only, like everything else in the ledger. A reversal that could be edited
    # would be a way to un-fail a payment.
    op.execute(
        "CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON aid.disbursement_reversal "
        "FOR EACH ROW EXECUTE FUNCTION public.sarana_append_only()"
    )
    op.execute("GRANT SELECT, INSERT ON aid.disbursement_reversal TO sarana_app")

    op.add_column(
        "disbursement",
        sa.Column(
            "reversed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Set by aid.stamp_disbursement_reversed() when a compensating entry "
            "is written. A back-pointer for the release gate, not the record itself - "
            "the record is the row in aid.disbursement_reversal, and it is hashed.",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_disbursement_reversed_at",
        "disbursement",
        ["reversed_at"],
        unique=False,
        schema=SCHEMA,
    )

    op.execute(ADDITIVE_ONLY)
    op.execute(
        "COMMENT ON FUNCTION aid.disbursement_additive_only() IS "
        "'Permits only the citizen confirmation columns and reversed_at to change, each "
        "once. Every other column, including both hashes, is as immutable as it was "
        "under public.sarana_append_only().'"
    )
    op.execute("DROP TRIGGER IF EXISTS append_only ON aid.disbursement")
    op.execute(
        "CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON aid.disbursement "
        "FOR EACH ROW EXECUTE FUNCTION aid.disbursement_additive_only()"
    )
    op.execute("DROP FUNCTION IF EXISTS aid.disbursement_confirmation_only()")

    op.execute(STAMP_REVERSAL)
    op.execute(
        "CREATE TRIGGER stamp_reversed AFTER INSERT ON aid.disbursement_reversal "
        "FOR EACH ROW EXECUTE FUNCTION aid.stamp_disbursement_reversed()"
    )

    columns = ", ".join(WRITABLE_COLUMNS)
    op.execute(f"GRANT UPDATE ({columns}) ON aid.disbursement TO sarana_app")

    # A grievance raised because a bank returned a payment did not arrive on any citizen
    # channel. Recording it as SMS would be a lie in the one field an officer uses to
    # decide how to reply to the household - and would make "how do citizens reach us?"
    # unanswerable from the data. Part of this migration rather than its own because a
    # reversal that cannot raise its grievance is half a feature.
    #
    # `op.f()` on both: 0002 created this constraint with `op.f(...)`, which marks the
    # name as already final. Without it the naming convention prepends `ck_grievance_` a
    # second time and the DROP looks for `ck_grievance_ck_grievance_channel_known`.
    op.drop_constraint(
        op.f("ck_grievance_channel_known"), "grievance", type_="check", schema=SCHEMA
    )
    op.create_check_constraint(
        op.f("ck_grievance_channel_known"),
        "grievance",
        f"channel IN ({', '.join(repr(c) for c in GRIEVANCE_CHANNELS)})",
        schema=SCHEMA,
    )

    # One *live* payment per entitlement. The plain unique constraint would bar a
    # household whose payment bounced from ever being paid, which would make reversing it
    # worse than leaving the failed record standing.
    op.drop_constraint("uq_disbursement_entitlement", "disbursement", type_="unique", schema=SCHEMA)
    op.create_index(
        "uq_disbursement_entitlement_live",
        "disbursement",
        ["entitlement_id"],
        unique=True,
        postgresql_where=sa.text("reversed_at IS NULL"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_grievance_channel_known"), "grievance", type_="check", schema=SCHEMA
    )
    op.create_check_constraint(
        op.f("ck_grievance_channel_known"),
        "grievance",
        "channel IN ('SMS', 'USSD', 'APP', 'IN_PERSON', 'PHONE', 'WEB')",
        schema=SCHEMA,
    )

    op.drop_index("uq_disbursement_entitlement_live", "disbursement", schema=SCHEMA)
    op.create_unique_constraint(
        "uq_disbursement_entitlement", "disbursement", ["entitlement_id"], schema=SCHEMA
    )

    columns = ", ".join(WRITABLE_COLUMNS)
    op.execute(f"REVOKE UPDATE ({columns}) ON aid.disbursement FROM sarana_app")

    op.execute("DROP TRIGGER IF EXISTS stamp_reversed ON aid.disbursement_reversal")
    op.execute("DROP FUNCTION IF EXISTS aid.stamp_disbursement_reversed()")

    op.execute("DROP TRIGGER IF EXISTS append_only ON aid.disbursement")
    op.execute("DROP FUNCTION IF EXISTS aid.disbursement_additive_only()")

    op.drop_index("ix_disbursement_reversed_at", "disbursement", schema=SCHEMA)
    op.drop_column("disbursement", "reversed_at", schema=SCHEMA)

    op.drop_table("disbursement_reversal", schema=SCHEMA)

    # Restore 0008's trigger. Rebuilt here rather than imported so a downgrade does not
    # depend on an earlier migration module still being importable.
    old_row = ", ".join(f"OLD.{column}" for column in IMMUTABLE_COLUMNS)
    new_row = ", ".join(f"NEW.{column}" for column in IMMUTABLE_COLUMNS)
    op.execute(
        f"""
CREATE OR REPLACE FUNCTION aid.disbursement_confirmation_only()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'aid.disbursement is append-only: DELETE is not permitted.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF ROW({new_row}) IS DISTINCT FROM ROW({old_row}) THEN
        RAISE EXCEPTION 'aid.disbursement is append-only apart from the citizen '
            'confirmation columns.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.citizen_confirmed AND NOT NEW.citizen_confirmed THEN
        RAISE EXCEPTION 'a citizen confirmation cannot be withdrawn.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$function$;
"""
    )
    op.execute(
        "CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON aid.disbursement "
        "FOR EACH ROW EXECUTE FUNCTION aid.disbursement_confirmation_only()"
    )
    op.execute(
        "GRANT UPDATE (citizen_confirmed, citizen_confirmed_at, citizen_confirm_channel) "
        "ON aid.disbursement TO sarana_app"
    )
