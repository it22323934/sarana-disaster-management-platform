"""the public aggregates could not read the table they aggregate

`GET /api/v1/public/ledger-summary` has been returning an empty list to every anonymous
caller since file 10, and nothing failed. Here is the chain that produced it.

`aid.damage_assessment` carries `ENABLE` *and* `FORCE ROW LEVEL SECURITY` with one policy,
`assessment_in_scope`, over `public.sarana_scope_covers(gn_division_code)`. That function
reads the `sarana.user_scope` session variable, and an unset variable yields an empty array
which covers nothing - deliberately, so a connection that forgot to set a scope sees no
rows rather than every row. `get_public_session` has no principal to scope by, so it calls
`apply_row_security_scope(connection, None)` and the scope is empty by design.

The result is that every public query joining `damage_assessment` is filtered to zero rows.
`_PUBLIC_LEDGER` joins it to reach `gn_division_code`, so the district summary the public
dashboard is built on has always been `[]`. It looked like a district that had disbursed
nothing, which is indistinguishable from working correctly on an empty database - which is
what every test that touched it had.

Build file 21 adds three more endpoints over the same table, so the hole had to close.

**The fix is a second permissive policy, not a weaker first one.** `assessment_in_scope`
is untouched: an officer still sees their own divisions and a connection that forgot its
scope still sees nothing. Alongside it, `assessment_public_aggregate` permits `SELECT`
only, and only when the transaction has explicitly set `sarana.public_aggregate` to `on`.
Postgres ORs permissive policies, so a session that has not set the marker is exactly as
restricted as it was before this migration.

**The marker is transaction-local and set in one function.** `set_config(..., true)` means
it dies with the transaction and cannot leak to the next request that borrows the pooled
connection - the same property `apply_row_security_scope` relies on. The only caller is
`ledger_svc.api.deps.get_public_session`, which is wired to the `/api/v1/public/*` and
`/api/v1/ledger/public` handlers and to nothing else.

**What actually protects the data is the SQL, and that was always the design.** The
docstring on `get_public_session` has said so since file 10: "the public queries select
only from the aggregated, anonymised projections - the scope is a second fence, not the
first." Those queries name no household, no NIC, no phone, no officer and no coordinate,
and group no finer than DS division. This migration makes the second fence a fence rather
than a wall, and the first fence is enforced where it can actually be enforced: by the
projections, and by the PII sweep in `tests/ledger/test_public_pii.py`, which asserts every
public response against a regex battery.

`SELECT` and nothing else. `FOR SELECT` on a permissive policy cannot widen INSERT, UPDATE
or DELETE, so the single-writer property ADR-006 depends on - a GN officer owns the
assessments for their own division and nobody else may write them - is untouched.

Revision ID: ledger_svc_0011
Revises: ledger_svc_0010
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "ledger_svc_0011"
down_revision: str | None = "ledger_svc_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The transaction-local marker a public session sets. Named in SQL here and in Python in
# `sarana_shared.db.sql`; `tests/ledger/test_public_aggregate_policy.py` asserts the two
# spellings agree, because a typo in either would silently restore the empty-list bug.
PUBLIC_AGGREGATE_SETTING = "sarana.public_aggregate"

_POLICY = f"""
CREATE POLICY assessment_public_aggregate ON aid.damage_assessment
FOR SELECT
USING (coalesce(current_setting('{PUBLIC_AGGREGATE_SETTING}', true), 'off') = 'on')
"""  # noqa: S608 - DDL interpolating a module constant, not caller input


def upgrade() -> None:
    op.execute(_POLICY)
    op.execute(
        "COMMENT ON POLICY assessment_public_aggregate ON aid.damage_assessment IS "
        "'Lets the unauthenticated transparency endpoints aggregate over every division. "
        "SELECT only, and only inside a transaction that has set sarana.public_aggregate "
        "to on - which ledger_svc.api.deps.get_public_session is the sole caller of. The "
        "anonymisation is the aggregate SQL, not this policy.'"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS assessment_public_aggregate ON aid.damage_assessment")
