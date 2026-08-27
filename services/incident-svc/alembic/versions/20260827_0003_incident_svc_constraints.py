"""the dispatch human gate, the review gate, row-level security and grants

The dispatch gate is the one that matters here: a plan may not reach RELEASED without a
recorded human decision. That is enforced by a BEFORE UPDATE trigger, not only by
application code, because the application is exactly what a "just this once" change would
edit at three in the morning during a cyclone.

Revision ID: incident_svc_0003
Revises: incident_svc_0002
Created: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from incident_svc.repo.reports import HUMAN_REVIEW_CONFIDENCE_THRESHOLD

revision: str = "incident_svc_0003"
down_revision: str | None = "incident_svc_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TOUCHED_TABLES: tuple[str, ...] = (
    "raw_report",
    "report_transcription",
    "incident",
    "report_incident_link",
    "dispatch_plan",
    "responder",
)

READ_WRITE_TABLES: tuple[tuple[str, str], ...] = (
    ("incident", "raw_report"),
    ("incident", "report_transcription"),
    ("incident", "report_embedding"),
    ("incident", "incident"),
    ("incident", "report_incident_link"),
    ("incident", "dispatch_plan"),
    ("incident", "responder"),
    ("outbox", "incident_svc_event"),
)

DISPATCH_GATE = """
CREATE OR REPLACE FUNCTION incident.enforce_dispatch_human_gate()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF NEW.status IN ('RELEASED', 'COMPLETED')
       AND (NEW.signed_off_by IS NULL OR NEW.signed_off_at IS NULL) THEN
        RAISE EXCEPTION
            'dispatch plan % cannot move to % without a recorded human sign-off. '
            'Committing a life-safety dispatch action is one of the two mandatory '
            'human gates and there is no bypass.',
            NEW.id, NEW.status
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    -- A sign-off, once recorded, is not reassigned to someone else. If the wrong
    -- person is on the record, the plan is rejected and a new one is raised.
    IF OLD.signed_off_by IS NOT NULL AND NEW.signed_off_by <> OLD.signed_off_by THEN
        RAISE EXCEPTION
            'dispatch plan % already carries a sign-off by %; it cannot be reassigned',
            NEW.id, OLD.signed_off_by
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$function$;
"""


def upgrade() -> None:
    # --- the review gate is derived, not asserted ------------------------------------
    # ADR-007: Sinhala and Tamil are low-resource languages and ASR accuracy on them is
    # materially worse than English. The confidence gate to human review is the headline
    # safety property, so the database derives it rather than trusting a caller to set
    # it - a gate the calling code can forget to apply is not a gate.
    op.execute("ALTER TABLE incident.report_transcription DROP COLUMN needs_human_review")
    op.execute(
        "ALTER TABLE incident.report_transcription "
        "ADD COLUMN needs_human_review boolean "
        f"GENERATED ALWAYS AS (confidence < {HUMAN_REVIEW_CONFIDENCE_THRESHOLD}) STORED"
    )
    op.execute(
        "CREATE INDEX ix_report_transcription_review "
        "ON incident.report_transcription (needs_human_review)"
    )

    for table in TOUCHED_TABLES:
        op.execute(
            f"CREATE TRIGGER touch_updated_at BEFORE UPDATE ON incident.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.sarana_touch_updated_at()"
        )

    # --- HUMAN GATE: committing a life-safety dispatch action -------------------------
    op.execute(DISPATCH_GATE)
    op.execute(
        "CREATE TRIGGER enforce_human_gate BEFORE UPDATE ON incident.dispatch_plan "
        "FOR EACH ROW EXECUTE FUNCTION incident.enforce_dispatch_human_gate()"
    )

    # --- row-level security on incidents ---------------------------------------------
    op.execute("ALTER TABLE incident.incident ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE incident.incident FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY incident_in_scope ON incident.incident "
        "USING (public.sarana_scope_covers(gn_division_code))"
    )

    # --- grants ----------------------------------------------------------------------
    for schema, table in READ_WRITE_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {schema}.{table} TO sarana_app"
        )

    # Triage scores are a history, not a mutable current value. Rescoring appends.
    op.execute("GRANT SELECT, INSERT ON incident.triage_score TO sarana_app")
    op.execute("REVOKE UPDATE, DELETE ON incident.triage_score FROM sarana_app")

    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA incident TO sarana_app")


def downgrade() -> None:
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA incident FROM sarana_app")
    op.execute("REVOKE ALL ON outbox.incident_svc_event FROM sarana_app")

    op.execute("DROP POLICY IF EXISTS incident_in_scope ON incident.incident")
    op.execute("ALTER TABLE incident.incident DISABLE ROW LEVEL SECURITY")

    op.execute("DROP TRIGGER IF EXISTS enforce_human_gate ON incident.dispatch_plan")
    op.execute("DROP FUNCTION IF EXISTS incident.enforce_dispatch_human_gate()")

    for table in TOUCHED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS touch_updated_at ON incident.{table}")

    op.execute("DROP INDEX IF EXISTS incident.ix_report_transcription_review")
    op.execute("ALTER TABLE incident.report_transcription DROP COLUMN needs_human_review")
    op.execute(
        "ALTER TABLE incident.report_transcription "
        "ADD COLUMN needs_human_review boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "CREATE INDEX ix_report_transcription_review "
        "ON incident.report_transcription (needs_human_review)"
    )
