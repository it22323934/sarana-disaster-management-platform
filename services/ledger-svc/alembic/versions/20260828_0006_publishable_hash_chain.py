"""the ledger chain uses the published hash, not PostgreSQL's jsonb form

Entries written before this migration cannot be verified by `tools/sarana-verify`, which
makes the ledger's central claim - that a journalist can check the numbers independently -
untrue.

Build file 10 specifies:

    entry_hash = SHA256( canonical_json(entry_without_hashes) || prev_hash )   # RFC 8785

`public.sarana_hash_chain()` computes `sha256((to_jsonb(NEW) - 'entry_hash')::text)`
instead, which differs three ways, each fatal on its own:

    key order    postgres sorts by (length, bytes), RFC 8785 by UTF-16 code unit
                     postgres:  {"z": 1, "aa": 2}
                     RFC 8785:  {"aa":2,"z":1}
    whitespace   postgres emits `{"a": 2}`, RFC 8785 emits `{"a":2}`
    prev_hash    postgres folds it into the payload; the scheme appends it after

Rather than reimplement RFC 8785 in plpgsql - a lot of delicate SQL to reproduce a
standard that already has a tested implementation in `sarana_shared.crypto.chain` - the
responsibilities are split:

  - the application reads the current tail, computes `prev_hash` and `entry_hash`, and
    supplies both on insert;
  - this trigger enforces what only the database can, namely that the supplied `prev_hash`
    really is the current tail and that a well-formed hash came with it.

The trigger deliberately does **not** fill `prev_hash` when it is missing. That value is an
input to `entry_hash`, so filling it afterwards would leave a stored hash describing a
predecessor the row does not claim. A racing writer is refused and retries against the new
tail, which is the correct outcome: the alternative is two entries claiming one
predecessor.

The guarantee is unchanged. No writer can break the chain, because a row whose `prev_hash`
does not match the tail is refused - by the database, regardless of which application
wrote it. What changes is that the stored hash is now the one anybody can recompute.

`audit.audit_entry` keeps the original trigger deliberately. That chain is verified by
core-api's `/audit/verify`, which recomputes with the same SQL expression, so the two
agree; it is never published for outside verification and does not need RFC 8785.

Revision ID: ledger_svc_0006
Revises: ledger_svc_0005
Created: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "ledger_svc_0006"
down_revision: str | None = "ledger_svc_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHAINED_TABLES: tuple[str, ...] = ("approval", "disbursement")

# Enforces the chain without computing it. Everything here is something the application
# cannot guarantee for itself: only the database sees the true current tail under
# concurrency, and only the database can refuse every writer at once.
ENFORCE_CHAIN = """
CREATE OR REPLACE FUNCTION public.sarana_enforce_supplied_chain()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    latest_hash text;
BEGIN
    -- Serialise appends. Two concurrent inserts would otherwise both read the same tail
    -- and produce two entries claiming the same predecessor, splitting the chain in a way
    -- that looks identical to tampering.
    PERFORM pg_advisory_xact_lock(TG_RELID::bigint);

    EXECUTE format(
        'SELECT entry_hash FROM %I.%I ORDER BY seq DESC LIMIT 1',
        TG_TABLE_SCHEMA, TG_TABLE_NAME
    ) INTO latest_hash;

    latest_hash := COALESCE(latest_hash, repeat('0', 64));

    -- prev_hash must be supplied, not filled in here. The application needs it to
    -- compute entry_hash, so a value invented at this point would leave the stored hash
    -- describing a predecessor the row does not claim - verifiable by nobody.
    --
    -- The caller therefore reads the tail, computes, and inserts. If another writer got
    -- there first this refuses and the caller retries against the new tail. Refusing a
    -- racing writer is right: the alternative is two entries claiming one predecessor.
    IF NEW.prev_hash IS NULL THEN
        RAISE EXCEPTION
            'prev_hash must be supplied on %.%: it is an input to entry_hash, so it '
            'cannot be filled in after the hash was computed. Read the current tail '
            '(%), compute the hash against it, and retry.',
            TG_TABLE_SCHEMA, TG_TABLE_NAME, latest_hash
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF NEW.prev_hash <> latest_hash THEN
        RAISE EXCEPTION
            'hash chain break on %.%: prev_hash % does not match the current tail %',
            TG_TABLE_SCHEMA, TG_TABLE_NAME, NEW.prev_hash, latest_hash
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    -- The application computes this with the published RFC 8785 scheme. An entry without
    -- one is refused rather than given a locally-computed hash, because a hash nobody can
    -- reproduce is worse than none: it looks verifiable and is not.
    IF NEW.entry_hash IS NULL OR NEW.entry_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION
            'entry_hash must be supplied as 64 lowercase hex characters, computed with '
            'the published RFC 8785 scheme (sarana_shared.crypto.chain). Got %',
            COALESCE(NEW.entry_hash, 'NULL')
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$function$;
"""

COMMENT = """
COMMENT ON FUNCTION public.sarana_enforce_supplied_chain() IS
'BEFORE INSERT trigger for the published aid ledger. Requires the caller to supply both '
'prev_hash (which must equal the current tail) and entry_hash (computed with RFC 8785 '
'canonicalisation, the scheme tools/sarana-verify recomputes). Deliberately computes '
'neither: prev_hash is an input to entry_hash so it cannot be filled in afterwards, and '
'PostgreSQL jsonb text is not RFC 8785 - a chain hashed with it verifies for nobody '
'outside.';
"""


def upgrade() -> None:
    op.execute(ENFORCE_CHAIN)
    op.execute(COMMENT)

    for table in CHAINED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS hash_chain ON aid.{table}")
        op.execute(
            f"CREATE TRIGGER hash_chain BEFORE INSERT ON aid.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.sarana_enforce_supplied_chain()"
        )


def downgrade() -> None:
    # Rows written under the published scheme will not verify against the trigger-computed
    # one, so a downgrade leaves a chain that no longer checks out. That is inherent to
    # reverting a hashing change, and it is better to be loud about it than to rewrite
    # history to make the old verifier happy.
    for table in CHAINED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS hash_chain ON aid.{table}")
        op.execute(
            f"CREATE TRIGGER hash_chain BEFORE INSERT ON aid.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.sarana_hash_chain()"
        )

    op.execute("DROP FUNCTION IF EXISTS public.sarana_enforce_supplied_chain()")
