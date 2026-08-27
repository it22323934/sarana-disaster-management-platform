"""the disbursement human gate, the ledger hash chain, RLS and grants

This migration is where the Transparent Aid Ledger stops being a table and becomes a
claim someone can check.

  - `disbursement`, `approval` and `ledger_anchor` are hash-chained and append-only.
    UPDATE and DELETE are revoked from the application role and refused by a trigger.
    Corrections are new compensating entries, never edits.
  - `released_by` must hold DISTRICT_APPROVER or ADMIN at the moment of the write. That
    is a property of the role assignment, not a foreign key, so a trigger checks it.
  - `damage_assessment` is row-level secured on the GN division code.

Revision ID: ledger_svc_0003
Revises: ledger_svc_0002
Created: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "ledger_svc_0003"
down_revision: str | None = "ledger_svc_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_TABLES: tuple[str, ...] = ("approval", "disbursement", "ledger_anchor")

CHAINED_TABLES: tuple[str, ...] = ("approval", "disbursement")

TOUCHED_TABLES: tuple[str, ...] = (
    "cost_schedule",
    "cost_schedule_line",
    "damage_assessment",
    "entitlement",
    "approval",
    "anomaly_flag",
    "grievance",
)

RELEASE_AUTHORITY = """
CREATE OR REPLACE FUNCTION aid.enforce_release_authority()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    authorised boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM admin.user_role ur
        JOIN admin.role r ON r.id = ur.role_id
        WHERE ur.user_id = NEW.released_by
          AND r.code IN ('DISTRICT_APPROVER', 'ADMIN')
    ) INTO authorised;

    IF NOT authorised THEN
        RAISE EXCEPTION
            'user % may not release a disbursement: releasing funds requires '
            'DISTRICT_APPROVER or ADMIN at the time of the write. Releasing a '
            'financial disbursement is one of the two mandatory human gates.',
            NEW.released_by
            USING ERRCODE = 'insufficient_privilege';
    END IF;

    RETURN NEW;
END;
$function$;
"""


def upgrade() -> None:
    for table in TOUCHED_TABLES:
        op.execute(
            f"CREATE TRIGGER touch_updated_at BEFORE UPDATE ON aid.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.sarana_touch_updated_at()"
        )

    # --- the hash chain ---------------------------------------------------------------
    # ADR-005. The chain alone proves nothing - the operator could recompute it after
    # tampering - which is why ledger_anchor exists and why the daily Merkle root goes to
    # S3 Object Lock in compliance mode, immutable even to the account root user.
    for table in CHAINED_TABLES:
        op.execute(
            f"CREATE TRIGGER hash_chain BEFORE INSERT ON aid.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.sarana_hash_chain()"
        )

    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON aid.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.sarana_append_only()"
        )

    # --- HUMAN GATE: releasing a financial disbursement --------------------------------
    op.execute(RELEASE_AUTHORITY)
    op.execute(
        "CREATE TRIGGER enforce_release_authority BEFORE INSERT ON aid.disbursement "
        "FOR EACH ROW EXECUTE FUNCTION aid.enforce_release_authority()"
    )

    # --- row-level security on assessments ---------------------------------------------
    # A GN officer owns assessments for their own division and nobody else may write
    # them (ADR-006). That single-writer property is what makes the offline operation log
    # sufficient and a CRDT unnecessary, so it has to actually hold.
    op.execute("ALTER TABLE aid.damage_assessment ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE aid.damage_assessment FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY assessment_in_scope ON aid.damage_assessment "
        "USING (public.sarana_scope_covers(gn_division_code))"
    )

    # --- grants ------------------------------------------------------------------------
    for table in (
        "cost_schedule",
        "cost_schedule_line",
        "damage_assessment",
        "entitlement",
        "anomaly_flag",
        "grievance",
    ):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON aid.{table} TO sarana_app")

    for table in APPEND_ONLY_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON aid.{table} TO sarana_app")
        op.execute(f"REVOKE UPDATE, DELETE ON aid.{table} FROM sarana_app")

    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON outbox.ledger_svc_event TO sarana_app"
    )
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA aid TO sarana_app")

    # The release-authority trigger reads the role assignment tables.
    op.execute("GRANT USAGE ON SCHEMA admin TO sarana_app")


def downgrade() -> None:
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA aid FROM sarana_app")
    op.execute("REVOKE ALL ON outbox.ledger_svc_event FROM sarana_app")

    op.execute("DROP POLICY IF EXISTS assessment_in_scope ON aid.damage_assessment")
    op.execute("ALTER TABLE aid.damage_assessment DISABLE ROW LEVEL SECURITY")

    op.execute("DROP TRIGGER IF EXISTS enforce_release_authority ON aid.disbursement")
    op.execute("DROP FUNCTION IF EXISTS aid.enforce_release_authority()")

    for table in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS append_only ON aid.{table}")
    for table in CHAINED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS hash_chain ON aid.{table}")
    for table in TOUCHED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS touch_updated_at ON aid.{table}")
