"""updated_at maintenance and grants for agent-svc

Revision ID: agent_svc_0003
Revises: agent_svc_0002
Created: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "agent_svc_0003"
down_revision: str | None = "agent_svc_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "hazard"

TOUCHED_TABLES: tuple[str, ...] = ("hazard_event", "anticipatory_trigger")

READ_WRITE_TABLES: tuple[str, ...] = ("hazard_event", "anticipatory_trigger")

APPEND_ONLY_TABLES: tuple[str, ...] = ("hazard_feed_reading", "impact_forecast")


def upgrade() -> None:
    for table in TOUCHED_TABLES:
        op.execute(
            f"CREATE TRIGGER touch_updated_at BEFORE UPDATE ON {SCHEMA}.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.sarana_touch_updated_at()"
        )

    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON {SCHEMA}.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.sarana_append_only()"
        )

    for table in READ_WRITE_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.{table} TO sarana_app"
        )

    for table in APPEND_ONLY_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.{table} TO sarana_app")
        op.execute(f"REVOKE UPDATE, DELETE ON {SCHEMA}.{table} FROM sarana_app")

    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON outbox.agent_svc_event TO sarana_app"
    )
    op.execute(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA {SCHEMA} TO sarana_app")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM sarana_app")
    op.execute("REVOKE ALL ON outbox.agent_svc_event FROM sarana_app")

    for table in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS append_only ON {SCHEMA}.{table}")
    for table in TOUCHED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS touch_updated_at ON {SCHEMA}.{table}")
