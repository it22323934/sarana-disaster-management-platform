"""segregation of duty on money, enforced in the database

Three rules, all about the same thing: nobody signs off their own work on a payment.

  1. The officer who wrote a damage assessment may not approve the entitlement it
     produced. Assessment and approval are the two independent judgements the whole aid
     process rests on, and one person doing both removes the check entirely.
  2. The DS approver may not also be the District approver on the same entitlement. The
     second level exists to be a second pair of eyes above a threshold; the same eyes
     twice is not a second level.
  3. The person who released a disbursement may not be the one who approved the
     entitlement behind it.

Enforced here as triggers as well as in the domain layer. The domain check is the first
line and gives the better error message; this is the one that still holds when a fix-up
script runs at three in the morning during a cyclone.

Revision ID: ledger_svc_0004
Revises: ledger_svc_0003
Created: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "ledger_svc_0004"
down_revision: str | None = "ledger_svc_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPROVAL_SEGREGATION = """
CREATE OR REPLACE FUNCTION aid.enforce_approval_segregation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    assessor uuid;
    other_level_approver uuid;
BEGIN
    SELECT da.assessed_by
    INTO assessor
    FROM aid.entitlement e
    JOIN aid.damage_assessment da ON da.id = e.assessment_id
    WHERE e.id = NEW.entitlement_id;

    IF assessor = NEW.approver_id THEN
        RAISE EXCEPTION
            'user % assessed the damage behind entitlement % and may not also approve '
            'it. Assessment and approval are the two independent judgements the aid '
            'process rests on.',
            NEW.approver_id, NEW.entitlement_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    SELECT a.approver_id
    INTO other_level_approver
    FROM aid.approval a
    WHERE a.entitlement_id = NEW.entitlement_id
      AND a.level <> NEW.level
      AND a.decision = 'APPROVED'
    LIMIT 1;

    IF other_level_approver = NEW.approver_id THEN
        RAISE EXCEPTION
            'user % has already approved entitlement % at the other level. The second '
            'level of approval exists to be a second pair of eyes.',
            NEW.approver_id, NEW.entitlement_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$function$;
"""

RELEASE_SEGREGATION = """
CREATE OR REPLACE FUNCTION aid.enforce_release_segregation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    approved_by_releaser boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM aid.approval a
        WHERE a.entitlement_id = NEW.entitlement_id
          AND a.approver_id = NEW.released_by
          AND a.decision = 'APPROVED'
    ) INTO approved_by_releaser;

    IF approved_by_releaser THEN
        RAISE EXCEPTION
            'user % approved entitlement % and may not also release the money against '
            'it. Approval and release are separate decisions by separate people.',
            NEW.released_by, NEW.entitlement_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$function$;
"""


def upgrade() -> None:
    op.execute(APPROVAL_SEGREGATION)
    op.execute(
        "CREATE TRIGGER enforce_segregation BEFORE INSERT ON aid.approval "
        "FOR EACH ROW EXECUTE FUNCTION aid.enforce_approval_segregation()"
    )

    op.execute(RELEASE_SEGREGATION)
    op.execute(
        "CREATE TRIGGER enforce_segregation BEFORE INSERT ON aid.disbursement "
        "FOR EACH ROW EXECUTE FUNCTION aid.enforce_release_segregation()"
    )

    # The segregation triggers read the assessment and approval history.
    op.execute("GRANT USAGE ON SCHEMA aid TO sarana_app")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS enforce_segregation ON aid.disbursement")
    op.execute("DROP FUNCTION IF EXISTS aid.enforce_release_segregation()")
    op.execute("DROP TRIGGER IF EXISTS enforce_segregation ON aid.approval")
    op.execute("DROP FUNCTION IF EXISTS aid.enforce_approval_segregation()")
