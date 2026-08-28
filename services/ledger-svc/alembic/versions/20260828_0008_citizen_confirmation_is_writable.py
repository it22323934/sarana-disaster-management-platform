"""let the household answer: narrow the append-only trigger to the confirmation columns

`aid.disbursement` carries `citizen_confirmed`, `citizen_confirmed_at` and
`citizen_confirm_channel`, and until this migration nothing could ever set them. The table
is append-only twice over - UPDATE revoked from `sarana_app` in 0003, and a trigger that
refuses UPDATE from anyone including the owner - so the confirmation loop in build file 10
had no way to record its own answer. Three columns that always read false are worse than
no columns at all, because a query that trusts them under-reports every payment that
actually arrived.

The append-only property is still what it was for the payment itself. What changes is that
one specific, additive fact - the household saying the money arrived - can be recorded
against the entry it concerns.

Three things keep that from becoming a general edit path:

  - the trigger compares every other column and refuses the update if any of them moved,
    so the amount, the releaser, the rail and both hashes are as immutable as before;
  - `citizen_confirmed` may go false -> true and never back, so a confirmation cannot be
    quietly withdrawn by whoever finds it inconvenient;
  - the grant is column-level. `sarana_app` holds UPDATE on exactly these three columns
    and on nothing else in the table.

The hash chain is unaffected, and deliberately so. `repo.chain_writer` hashes a payload
that names the payment - entitlement, amount, releaser, time, rail - and never the
confirmation columns, because the household's reply is evidence *about* the entry rather
than part of it. A ledger whose entry hash changed when someone replied to an SMS would
fail verification for an honest reason, which is the worst kind.

Revision ID: ledger_svc_0008
Revises: ledger_svc_0007
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "ledger_svc_0008"
down_revision: str | None = "ledger_svc_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Every column that is not part of the household's answer. Listed rather than derived:
# a column added later should have to be considered here explicitly, and the default for
# anything unlisted is that it cannot be touched.
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

CONFIRMATION_COLUMNS = ("citizen_confirmed", "citizen_confirmed_at", "citizen_confirm_channel")

_OLD_ROW = ", ".join(f"OLD.{column}" for column in IMMUTABLE_COLUMNS)
_NEW_ROW = ", ".join(f"NEW.{column}" for column in IMMUTABLE_COLUMNS)

CONFIRMATION_ONLY = f"""
CREATE OR REPLACE FUNCTION aid.disbursement_confirmation_only()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'aid.disbursement is append-only: DELETE is not permitted. Corrections are '
            'new compensating entries, never removals.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF ROW({_NEW_ROW}) IS DISTINCT FROM ROW({_OLD_ROW}) THEN
        RAISE EXCEPTION
            'aid.disbursement is append-only apart from the citizen confirmation '
            'columns. Correct a payment with a new compensating entry, never an edit.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF OLD.citizen_confirmed AND NOT NEW.citizen_confirmed THEN
        RAISE EXCEPTION
            'a citizen confirmation cannot be withdrawn. If the household now says the '
            'money did not arrive, that is a grievance against this disbursement.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$function$;
"""


def upgrade() -> None:
    op.execute(CONFIRMATION_ONLY)
    op.execute(
        "COMMENT ON FUNCTION aid.disbursement_confirmation_only() IS "
        "'Permits only the citizen confirmation columns to change, and only once. Every "
        "other column, including both hashes, is as immutable as it was under "
        "public.sarana_append_only().'"
    )

    op.execute("DROP TRIGGER IF EXISTS append_only ON aid.disbursement")
    op.execute(
        "CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON aid.disbursement "
        "FOR EACH ROW EXECUTE FUNCTION aid.disbursement_confirmation_only()"
    )

    columns = ", ".join(CONFIRMATION_COLUMNS)
    op.execute(f"GRANT UPDATE ({columns}) ON aid.disbursement TO sarana_app")


def downgrade() -> None:
    columns = ", ".join(CONFIRMATION_COLUMNS)
    op.execute(f"REVOKE UPDATE ({columns}) ON aid.disbursement FROM sarana_app")
    op.execute("DROP TRIGGER IF EXISTS append_only ON aid.disbursement")
    op.execute(
        "CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON aid.disbursement "
        "FOR EACH ROW EXECUTE FUNCTION public.sarana_append_only()"
    )
    op.execute("DROP FUNCTION IF EXISTS aid.disbursement_confirmation_only()")
