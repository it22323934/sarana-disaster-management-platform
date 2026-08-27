"""Shared SQL objects that more than one service's migrations depend on.

Every statement here is idempotent (`CREATE OR REPLACE`, `IF NOT EXISTS`), and every
service's first migration applies the whole set. That removes the ordering dependency
between service migration chains: whichever service migrates first creates them, and the
rest are no-ops. One source of truth, no cross-service `depends_on`.

These are deliberately database objects rather than application checks. Application-level
validation is the first line; a constraint in the database is the one that still holds
when the application is wrong, when someone runs a fix-up script by hand, or when a
future service writes to a table its authors did not read the rules for.
"""

from __future__ import annotations

import re
from typing import Final

# Every hash chain starts from a fixed, publicly known genesis value rather than NULL.
# A verifier can then check the first entry the same way it checks every other one.
GENESIS_HASH: Final = "0" * 64

# Keys that must never appear anywhere in an anomaly rationale (ADR-009). A flag is
# advisory and must never name an individual officer, at any nesting depth.
FORBIDDEN_RATIONALE_KEYS: Final[tuple[str, ...]] = (
    "officer_id",
    "assessed_by",
    "user_id",
    "approver_id",
    "released_by",
    "gn_officer",
)


ALL_LOCALES_PRESENT: Final = """
CREATE OR REPLACE FUNCTION public.all_locales_present(value jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $function$
    SELECT value IS NOT NULL
       AND jsonb_typeof(value) = 'object'
       AND value ? 'si' AND value ? 'ta' AND value ? 'en'
       AND jsonb_typeof(value -> 'si') = 'string'
       AND jsonb_typeof(value -> 'ta') = 'string'
       AND jsonb_typeof(value -> 'en') = 'string'
       AND length(btrim(value ->> 'si')) > 0
       AND length(btrim(value ->> 'ta')) > 0
       AND length(btrim(value ->> 'en')) > 0;
$function$;

COMMENT ON FUNCTION public.all_locales_present(jsonb) IS
'True when a localised text value carries a non-blank si, ta and en. Applied as a CHECK '
'to every citizen-facing text column in every schema. During Cyclone Ditwah the 28 Nov '
'2025 DMC press conference went out in Sinhala and English only; this constraint is why '
'a record like that cannot be written here.';
"""


JSONB_CONTAINS_ANY_KEY: Final = """
CREATE OR REPLACE FUNCTION public.jsonb_contains_any_key(value jsonb, keys text[])
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $function$
    WITH RECURSIVE walk(node) AS (
        SELECT value
        UNION ALL
        SELECT child.value
        FROM walk
        CROSS JOIN LATERAL (
            SELECT v.value
            FROM jsonb_each(walk.node) AS v
            WHERE jsonb_typeof(walk.node) = 'object'
            UNION ALL
            SELECT a.value
            FROM jsonb_array_elements(walk.node) AS a
            WHERE jsonb_typeof(walk.node) = 'array'
        ) AS child
    )
    SELECT EXISTS (
        SELECT 1
        FROM walk
        WHERE jsonb_typeof(walk.node) = 'object'
          AND EXISTS (
              SELECT 1 FROM unnest(keys) AS k WHERE walk.node ? k
          )
    );
$function$;

COMMENT ON FUNCTION public.jsonb_contains_any_key(jsonb, text[]) IS
'True when any of the named keys appears anywhere in the document, at any depth. Used to '
'keep individual identities out of anomaly rationales (ADR-009): flagging a GN officer on '
'a statistical artifact can end a career, so a rationale may describe a pattern but may '
'never name a person.';
"""


HASH_CHAIN_TRIGGER: Final = f"""
CREATE OR REPLACE FUNCTION public.sarana_hash_chain()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    latest_hash text;
    payload     text;
BEGIN
    -- Serialise appends to this table. Two concurrent inserts would otherwise both read
    -- the same tail and produce two entries claiming the same predecessor, which breaks
    -- the chain silently. The lock is transaction-scoped and released on commit.
    PERFORM pg_advisory_xact_lock(TG_RELID::bigint);

    EXECUTE format(
        'SELECT entry_hash FROM %I.%I ORDER BY seq DESC LIMIT 1',
        TG_TABLE_SCHEMA, TG_TABLE_NAME
    ) INTO latest_hash;

    latest_hash := COALESCE(latest_hash, '{GENESIS_HASH}');

    IF NEW.prev_hash IS NULL THEN
        NEW.prev_hash := latest_hash;
    ELSIF NEW.prev_hash <> latest_hash THEN
        RAISE EXCEPTION
            'hash chain break on %.%: prev_hash % does not match the current tail %',
            TG_TABLE_SCHEMA, TG_TABLE_NAME, NEW.prev_hash, latest_hash
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    -- jsonb sorts its keys, so this serialisation is canonical without extra work.
    -- entry_hash is excluded because it is what we are about to compute; anything a
    -- caller put there is discarded rather than trusted.
    payload := (to_jsonb(NEW) - 'entry_hash')::text;
    NEW.entry_hash := encode(sha256(convert_to(payload, 'UTF8')), 'hex');

    RETURN NEW;
END;
$function$;

COMMENT ON FUNCTION public.sarana_hash_chain() IS
'BEFORE INSERT trigger for append-only hash-chained tables. Fills prev_hash from the '
'current tail, rejects a supplied prev_hash that does not match it, and computes '
'entry_hash over the canonical jsonb form of the row. ADR-005: the chain alone proves '
'nothing without the daily Merkle root anchored outside this database.';
"""  # noqa: S608 - DDL interpolating GENESIS_HASH, a module constant, not caller input


APPEND_ONLY_TRIGGER: Final = """
CREATE OR REPLACE FUNCTION public.sarana_append_only()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION
        '%.% is append-only: % is not permitted. Corrections are new compensating '
        'entries, never edits.',
        TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$function$;

COMMENT ON FUNCTION public.sarana_append_only() IS
'Rejects UPDATE and DELETE. Belt and braces alongside the revoked grants: the grants stop '
'the application role, this stops anyone connected as the owner, including a migration '
'that did not mean to.';
"""


TOUCH_UPDATED_AT_TRIGGER: Final = """
CREATE OR REPLACE FUNCTION public.sarana_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$function$;
"""


# The session variable the auth middleware sets, once per request, inside the transaction.
# `SET LOCAL` means it cannot leak to the next request on a pooled connection.
SCOPE_SETTING: Final = "sarana.user_scope"


ROW_SECURITY_HELPERS: Final = f"""
CREATE OR REPLACE FUNCTION public.sarana_current_scopes()
RETURNS text[]
LANGUAGE sql
STABLE
AS $function$
    SELECT CASE
        WHEN coalesce(current_setting('{SCOPE_SETTING}', true), '') = ''
            THEN ARRAY[]::text[]
        ELSE string_to_array(current_setting('{SCOPE_SETTING}', true), ',')
    END;
$function$;

COMMENT ON FUNCTION public.sarana_current_scopes() IS
'Administrative area codes the current session may act within, from the '
'{SCOPE_SETTING} session variable set by the auth middleware. An unset variable yields an '
'empty array, which covers nothing - a connection that forgot to set a scope sees no '
'rows rather than every row.';

CREATE OR REPLACE FUNCTION public.sarana_scope_covers(target_code text)
RETURNS boolean
LANGUAGE sql
STABLE
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM unnest(public.sarana_current_scopes()) AS s(scope)
        WHERE scope = 'LK'
           OR scope = target_code
           OR target_code LIKE scope || '-%'
    );
$function$;

COMMENT ON FUNCTION public.sarana_scope_covers(text) IS
'Segment-aware containment over official admin codes, matching contains() in '
'sarana_shared.domain.admin and covers() in @sarana/ts-shared. The trailing hyphen in the '
'LIKE is what stops LK-11-0 from matching LK-11-03.';
"""  # noqa: S608 - DDL interpolating SCOPE_SETTING, a module constant, not caller input


ROLES: Final = """
DO $do$
BEGIN
    -- Owns nothing, reads and writes through the grants each schema migration hands it.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sarana_app') THEN
        CREATE ROLE sarana_app NOLOGIN;
    END IF;

    -- Owns the schemas and runs migrations. The application never connects as this role.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sarana_migrator') THEN
        CREATE ROLE sarana_migrator NOLOGIN;
    END IF;
END
$do$;

COMMENT ON ROLE sarana_app IS
'The application role. Holds only the grants each schema migration gives it, never owner '
'rights, and has no UPDATE or DELETE on any append-only table.';

COMMENT ON ROLE sarana_migrator IS
'Schema owner. Runs Alembic. Separate from sarana_app so a compromised service cannot '
'drop a constraint that a non-negotiable depends on.';
"""


def _split_statements(script: str) -> list[str]:
    """Split a DDL script into individual statements.

    asyncpg prepares every statement it is given and refuses a string containing more
    than one, so migrations have to hand them over one at a time. Dollar-quoted
    function bodies are full of semicolons, so the split tracks whether it is inside
    one rather than splitting on every semicolon it sees.
    """
    statements: list[str] = []
    open_tag: str | None = None
    current: list[str] = []

    for line in script.splitlines():
        current.append(line)

        for tag in re.findall(r"\$[a-zA-Z_]*\$", line):
            if open_tag is None:
                open_tag = tag
            elif open_tag == tag:
                open_tag = None

        if open_tag is None and line.strip().endswith(";"):
            statement = "\n".join(current).strip()
            if statement:
                statements.append(statement)
            current = []

    tail = "\n".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


# Applied in order by every service's first migration, one statement at a time. Each is
# idempotent, so whichever service migrates first creates them and the rest are no-ops.
SHARED_OBJECTS: Final[tuple[str, ...]] = tuple(
    statement
    for script in (
        ROLES,
        ALL_LOCALES_PRESENT,
        JSONB_CONTAINS_ANY_KEY,
        HASH_CHAIN_TRIGGER,
        APPEND_ONLY_TRIGGER,
        TOUCH_UPDATED_AT_TRIGGER,
        ROW_SECURITY_HELPERS,
    )
    for statement in _split_statements(script)
)

# Extensions the schema depends on. `sha256()` is built in since PostgreSQL 11, so the
# hash chain needs no extension; pgcrypto is here for field-level PII encryption.
REQUIRED_EXTENSIONS: Final[tuple[str, ...]] = (
    "postgis",
    "vector",
    "pgcrypto",
    "pg_trgm",
)


def localised_check(column: str) -> str:
    """SQL for a CHECK constraint requiring si, ta and en on a localised column."""
    return f"public.all_locales_present({column})"


def rationale_privacy_check(column: str) -> str:
    """SQL for a CHECK constraint keeping individual identities out of a JSONB column."""
    keys = ", ".join(f"'{key}'" for key in FORBIDDEN_RATIONALE_KEYS)
    return f"NOT public.jsonb_contains_any_key({column}, ARRAY[{keys}]::text[])"
