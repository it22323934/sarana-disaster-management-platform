"""generated columns, hash chain, row-level security and grants for core-api

Everything Alembic autogenerate cannot express, and everything that turns a
non-negotiable from a convention into a rule the database enforces.

Revision ID: core_api_0003
Revises: core_api_0002
Created: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_api_0003"
down_revision: str | None = "core_api_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables carrying updated_at, which the touch trigger maintains.
TOUCHED_TABLES: tuple[tuple[str, str], ...] = (
    ("admin", "province"),
    ("admin", "district"),
    ("admin", "ds_division"),
    ("admin", "gn_division"),
    ("admin", "household"),
    ("admin", "app_user"),
    ("admin", "role"),
    ("admin", "user_role"),
    ("resilience", "rg_entity"),
    ("resilience", "rg_relation"),
)

READ_WRITE_TABLES: tuple[tuple[str, str], ...] = (
    *TOUCHED_TABLES,
    ("resilience", "rg_observation"),
    ("outbox", "core_api_event"),
)


def upgrade() -> None:
    # --- gn_division.centroid is derived, never written -----------------------------
    # A centroid that disagrees with its own boundary sends responders to the wrong
    # place, so the database computes it rather than trusting whoever inserted the row.
    op.execute('ALTER TABLE admin.gn_division DROP COLUMN centroid')
    op.execute(
        "ALTER TABLE admin.gn_division "
        "ADD COLUMN centroid geometry(Point, 4326) "
        "GENERATED ALWAYS AS (ST_Centroid(geom)) STORED"
    )
    op.execute(
        "CREATE INDEX ix_gn_division_centroid ON admin.gn_division USING gist (centroid)"
    )

    # --- updated_at maintenance -----------------------------------------------------
    for schema, table in TOUCHED_TABLES:
        op.execute(
            f"CREATE TRIGGER touch_updated_at BEFORE UPDATE ON {schema}.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.sarana_touch_updated_at()"
        )

    # --- the audit log is append-only and hash-chained -------------------------------
    # Non-negotiable #4. An audit log the operator can quietly edit is not an audit log.
    op.execute(
        "CREATE TRIGGER hash_chain BEFORE INSERT ON audit.audit_entry "
        "FOR EACH ROW EXECUTE FUNCTION public.sarana_hash_chain()"
    )
    op.execute(
        "CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON audit.audit_entry "
        "FOR EACH ROW EXECUTE FUNCTION public.sarana_append_only()"
    )

    # --- observations are append-only too --------------------------------------------
    # Agents append and a projection job folds; nobody edits an observation in place.
    op.execute(
        "CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON resilience.rg_observation "
        "FOR EACH ROW EXECUTE FUNCTION public.sarana_append_only()"
    )

    # --- row-level security on household ---------------------------------------------
    # Application-level checks are the first line. RLS is the one that holds when the
    # application is wrong: a handler that forgets its scope filter returns nothing
    # rather than returning every household in the country.
    op.execute("ALTER TABLE admin.household ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE admin.household FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY household_in_scope ON admin.household "
        "USING (gn_division_id IN ("
        "  SELECT id FROM admin.gn_division WHERE public.sarana_scope_covers(code)"
        "))"
    )

    # --- grants ----------------------------------------------------------------------
    for schema, table in READ_WRITE_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {schema}.{table} TO sarana_app"
        )

    # Append-only tables: insert and read, never change or remove. The revoked grant is
    # the primary control; the trigger above is the backstop for anyone connected as the
    # table owner.
    op.execute("GRANT SELECT, INSERT ON audit.audit_entry TO sarana_app")
    op.execute("REVOKE UPDATE, DELETE ON audit.audit_entry FROM sarana_app")
    op.execute("GRANT SELECT, INSERT ON resilience.rg_observation TO sarana_app")
    op.execute("REVOKE UPDATE, DELETE ON resilience.rg_observation FROM sarana_app")

    # bigserial sequences the application inserts against.
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA audit TO sarana_app")
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA admin TO sarana_app")
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA resilience TO sarana_app")
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA outbox TO sarana_app")


def downgrade() -> None:
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA audit FROM sarana_app")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA admin FROM sarana_app")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA resilience FROM sarana_app")
    op.execute("REVOKE ALL ON outbox.core_api_event FROM sarana_app")

    op.execute("DROP POLICY IF EXISTS household_in_scope ON admin.household")
    op.execute("ALTER TABLE admin.household DISABLE ROW LEVEL SECURITY")

    op.execute("DROP TRIGGER IF EXISTS append_only ON resilience.rg_observation")
    op.execute("DROP TRIGGER IF EXISTS append_only ON audit.audit_entry")
    op.execute("DROP TRIGGER IF EXISTS hash_chain ON audit.audit_entry")

    for schema, table in TOUCHED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS touch_updated_at ON {schema}.{table}")

    op.execute("DROP INDEX IF EXISTS admin.ix_gn_division_centroid")
    op.execute("ALTER TABLE admin.gn_division DROP COLUMN centroid")
    op.execute("ALTER TABLE admin.gn_division ADD COLUMN centroid geometry(Point, 4326)")
    op.execute(
        "CREATE INDEX ix_gn_division_centroid ON admin.gn_division USING gist (centroid)"
    )
