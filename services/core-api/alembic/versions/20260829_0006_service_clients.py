"""machine credentials that are not a long-lived token pasted into a .env file

`SARANA_INCIDENT_SERVICE_TOKEN` was a workaround, and it is documented as one: a
never-expiring `SERVICE` token, minted by a script, sitting in an environment variable on
every host that needs it. It cannot be rotated without a redeploy, it cannot be revoked at
all, it grants every scope the SERVICE role has whether the caller needs them or not, and
anybody who reads the file holds it forever.

This table replaces it with a client-credentials grant. A service presents a client id and
a secret to `POST /api/v1/auth/token` and gets back an access token with the service's
normal fifteen-minute lifetime. Four things follow from that, and each one is the point:

**Revocable.** `active = false` and the next token request fails. The outstanding token
expires within the quarter hour.

**Least privilege.** `allowed_scopes` narrows what the client gets to a subset of the
SERVICE role. alerting-svc needs to read one household's contact hash; it has no business
holding `resilience:write` because a different service does.

**Scoped to an area.** The same `(scope_type, scope_code)` every human grant uses, so a
machine credential is subject to row-level security on exactly the same terms.

**The secret is never stored.** Argon2id, the same hasher as a password. A database dump
does not yield a working credential.

The human gates are unaffected and stay unaffected: `SERVICE` is a machine principal, and
`sarana_shared.auth` refuses `disbursement:release` and `dispatch:commit` to every machine
principal regardless of what its scopes say. There is no client configuration that can
release money.

Revision ID: core_api_0006
Revises: core_api_0005
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "core_api_0006"
down_revision: str | None = "core_api_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "admin"


def upgrade() -> None:
    op.create_table(
        "service_client",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "client_id",
            sa.String(length=64),
            nullable=False,
            comment="The public half. Named for the service that holds it, so a log line "
            "showing which credential was used names the caller.",
        ),
        sa.Column(
            "secret_hash",
            sa.Text(),
            nullable=False,
            comment="Argon2id. The secret itself is shown once at creation and never stored.",
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "allowed_scopes",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            comment="A subset of the SERVICE role's scopes. Empty is refused: a credential "
            "that grants nothing is a misconfiguration, not a safe default.",
        ),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_code", sa.String(length=16), nullable=False),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="Revocation. Checked on every grant, so turning this off stops new "
            "tokens within one request and existing ones within their TTL.",
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "scope_type IN ('NATIONAL', 'DISTRICT', 'DS', 'GN')",
            name=op.f("ck_service_client_scope_type_known"),
        ),
        # A credential with no scopes can do nothing and looks like it works. Refused so
        # the failure is at creation, where somebody is watching, rather than at 3 a.m.
        sa.CheckConstraint(
            "array_length(allowed_scopes, 1) > 0",
            name=op.f("ck_service_client_grants_something"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_client")),
        sa.UniqueConstraint("client_id", name="uq_service_client_client_id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_service_client_active",
        "service_client",
        ["client_id"],
        unique=False,
        postgresql_where=sa.text("active"),
        schema=SCHEMA,
    )

    # `sarana_app` may read a client to authenticate it and stamp `last_used_at`. It may
    # not create, delete, or change a credential's scopes: issuing machine credentials is
    # an administrative act, and the process that authenticates them is exactly the one an
    # attacker reaches first.
    op.execute(f"GRANT SELECT ON {SCHEMA}.service_client TO sarana_app")
    op.execute(f"GRANT UPDATE (last_used_at) ON {SCHEMA}.service_client TO sarana_app")

    op.execute(
        f"COMMENT ON TABLE {SCHEMA}.service_client IS "
        "'Client-credentials grants for service-to-service calls. Replaces the long-lived "
        "SARANA_*_SERVICE_TOKEN environment variables: revocable, least-privilege, "
        "area-scoped, and the secret is hashed. Human gates remain closed to every "
        "machine principal regardless of what a row here says.'"
    )


    # A refused machine credential needs its own signal. Folded into this migration
    # because a mechanism whose denials cannot be recorded is not observable, and the
    # first denial would be a 500 on the authentication path.
    op.drop_constraint(
        op.f("ck_security_event_kind_known"), "security_event", type_="check", schema=SCHEMA
    )
    op.create_check_constraint(
        op.f("ck_security_event_kind_known"),
        "security_event",
        "kind IN ('REFRESH_REUSE', 'LOCKOUT_TRIGGERED', 'REPEATED_AUTHZ_DENIAL', "
        "'LEDGER_DENIAL_BURST', 'TOTP_FAILURE_BURST', 'CAPABILITY_MISUSE', "
        "'SERVICE_CREDENTIAL_DENIED')",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_security_event_kind_known"), "security_event", type_="check", schema=SCHEMA
    )
    op.create_check_constraint(
        op.f("ck_security_event_kind_known"),
        "security_event",
        "kind IN ('REFRESH_REUSE', 'LOCKOUT_TRIGGERED', 'REPEATED_AUTHZ_DENIAL', "
        "'LEDGER_DENIAL_BURST', 'TOTP_FAILURE_BURST', 'CAPABILITY_MISUSE')",
        schema=SCHEMA,
    )

    op.drop_index("ix_service_client_active", "service_client", schema=SCHEMA)
    op.drop_table("service_client", schema=SCHEMA)
