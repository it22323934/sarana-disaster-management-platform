"""auth tables: devices, refresh families, OTP, lockout, security events

Revision ID: core_api_0004
Revises: core_api_0003
Created: 2026-08-27 12:49:53.051694
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from sqlalchemy.dialects import postgresql

revision: str = "core_api_0004"
down_revision: str | None = "core_api_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TOUCHED_TABLES: tuple[str, ...] = ("device", "mfa_enrolment")

READ_WRITE_TABLES: tuple[str, ...] = (
    "device",
    "refresh_token",
    "otp_challenge",
    "mfa_enrolment",
)

# Append-only: a login attempt and a security event are evidence. Rewriting either is
# exactly what an attacker who reached the database would want to do.
APPEND_ONLY_TABLES: tuple[str, ...] = ("login_attempt", "security_event")

AUDITOR_READABLE_SCHEMAS: tuple[str, ...] = (
    "admin",
    "aid",
    "incident",
    "alerting",
    "hazard",
    "resilience",
    "audit",
)


def upgrade() -> None:
    op.create_table('login_attempt',
    sa.Column('account_hash', sa.Text(), nullable=False),
    sa.Column('source_hash', sa.Text(), nullable=False),
    sa.Column('attempted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('succeeded', sa.Boolean(), nullable=False),
    sa.Column('failure_reason', sa.String(length=32), nullable=True),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_login_attempt')),
    schema='admin'
    )
    op.create_index('ix_login_attempt_account_time', 'login_attempt', ['account_hash', 'attempted_at'], unique=False, schema='admin')
    op.create_index('ix_login_attempt_source_time', 'login_attempt', ['source_hash', 'attempted_at'], unique=False, schema='admin')
    op.create_table('otp_challenge',
    sa.Column('msisdn_hash', sa.Text(), nullable=False),
    sa.Column('code_hash', sa.Text(), nullable=False),
    sa.Column('language', sa.String(length=2), server_default='si', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('max_attempts', sa.Integer(), server_default='3', nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("language IN ('si','ta','en')", name=op.f('ck_otp_challenge_language_supported')),
    sa.CheckConstraint('attempts >= 0', name=op.f('ck_otp_challenge_attempts_non_negative')),
    sa.CheckConstraint('expires_at > created_at', name=op.f('ck_otp_challenge_expiry_after_creation')),
    sa.CheckConstraint('max_attempts > 0', name=op.f('ck_otp_challenge_max_attempts_positive')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_otp_challenge')),
    schema='admin'
    )
    op.create_index('ix_otp_challenge_created', 'otp_challenge', ['created_at'], unique=False, schema='admin')
    op.create_index('ix_otp_challenge_live', 'otp_challenge', ['msisdn_hash'], unique=False, schema='admin', postgresql_where=sa.text('consumed_at IS NULL'))
    op.create_table('security_event',
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('subject_id', sa.UUID(), nullable=True),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("jsonb_typeof(detail) = 'object'", name=op.f('ck_security_event_detail_is_object')),
    sa.CheckConstraint("kind IN ('REFRESH_REUSE', 'LOCKOUT_TRIGGERED', 'REPEATED_AUTHZ_DENIAL', 'LEDGER_DENIAL_BURST', 'TOTP_FAILURE_BURST', 'CAPABILITY_MISUSE')", name=op.f('ck_security_event_kind_known')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_security_event')),
    schema='admin'
    )
    op.create_index(op.f('ix_admin_security_event_subject_id'), 'security_event', ['subject_id'], unique=False, schema='admin')
    op.create_index('ix_security_event_kind_time', 'security_event', ['kind', 'occurred_at'], unique=False, schema='admin')
    op.create_table('device',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('platform', sa.String(length=20), nullable=False),
    sa.Column('display_name', sa.String(length=96), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_reason', sa.String(length=24), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("platform IN ('ios', 'android', 'web', 'field_companion')", name=op.f('ck_device_platform_known')),
    sa.ForeignKeyConstraint(['user_id'], ['admin.app_user.id'], name=op.f('fk_device_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_device')),
    schema='admin'
    )
    op.create_index(op.f('ix_admin_device_user_id'), 'device', ['user_id'], unique=False, schema='admin')
    op.create_index('ix_device_user_active', 'device', ['user_id'], unique=False, schema='admin', postgresql_where=sa.text('revoked_at IS NULL'))
    op.create_table('mfa_enrolment',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('secret_encrypted', sa.LargeBinary(), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('recovery_code_hashes', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False),
    sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('confirmed_at IS NULL OR confirmed_at >= created_at', name=op.f('ck_mfa_enrolment_confirmed_after_created')),
    sa.ForeignKeyConstraint(['user_id'], ['admin.app_user.id'], name=op.f('fk_mfa_enrolment_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mfa_enrolment')),
    sa.UniqueConstraint('user_id', name=op.f('uq_mfa_enrolment_user_id')),
    schema='admin'
    )
    op.create_table('refresh_token',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('device_id', sa.UUID(), nullable=False),
    sa.Column('family_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rotated_to', sa.UUID(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_reason', sa.String(length=24), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("revoked_reason IS NULL OR revoked_reason IN ('LOGOUT', 'ROTATED', 'REUSE_DETECTED', 'DEVICE_LOST', 'ADMIN_REVOKED', 'ROLE_CHANGED')", name=op.f('ck_refresh_token_revoked_reason_known')),
    sa.CheckConstraint('expires_at > issued_at', name=op.f('ck_refresh_token_expiry_after_issue')),
    sa.CheckConstraint('revoked_at IS NULL OR revoked_reason IS NOT NULL', name=op.f('ck_refresh_token_revocation_has_a_reason')),
    sa.ForeignKeyConstraint(['device_id'], ['admin.device.id'], name=op.f('fk_refresh_token_device_id_device'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['admin.app_user.id'], name=op.f('fk_refresh_token_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_token')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_refresh_token_token_hash')),
    schema='admin'
    )
    op.create_index(op.f('ix_admin_refresh_token_device_id'), 'refresh_token', ['device_id'], unique=False, schema='admin')
    op.create_index(op.f('ix_admin_refresh_token_user_id'), 'refresh_token', ['user_id'], unique=False, schema='admin')
    op.create_index('ix_refresh_token_live', 'refresh_token', ['family_id'], unique=False, schema='admin', postgresql_where=sa.text('revoked_at IS NULL AND used_at IS NULL'))


    for table in TOUCHED_TABLES:
        op.execute(
            f"CREATE TRIGGER touch_updated_at BEFORE UPDATE ON admin.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.sarana_touch_updated_at()"
        )

    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON admin.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.sarana_append_only()"
        )

    for table in READ_WRITE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON admin.{table} TO sarana_app")

    for table in APPEND_ONLY_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON admin.{table} TO sarana_app")
        op.execute(f"REVOKE UPDATE, DELETE ON admin.{table} FROM sarana_app")

    # --- the auditor is read-only structurally, not by an application flag ------------
    # An auditor whose read-only-ness is a boolean in the application is read-only until
    # someone writes a handler that forgets to check it. This is a database grant: there
    # is no INSERT for the role to lose.
    op.execute(
        "DO $do$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sarana_auditor') THEN "
        "CREATE ROLE sarana_auditor NOLOGIN; END IF; END $do$"
    )
    op.execute(
        "COMMENT ON ROLE sarana_auditor IS "
        "'Read-only across every schema. Holds SELECT and nothing else, so an auditor "
        "session cannot write however the application behaves.'"
    )
    for schema in AUDITOR_READABLE_SCHEMAS:
        op.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO sarana_auditor')
        op.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO sarana_auditor')
        op.execute(
            f'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA "{schema}" '
            "FROM sarana_auditor"
        )
        # Tables created after this migration inherit the same shape.
        op.execute(
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
            "GRANT SELECT ON TABLES TO sarana_auditor"
        )

    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA admin TO sarana_app")


def downgrade() -> None:
    for schema in AUDITOR_READABLE_SCHEMAS:
        op.execute(
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
            "REVOKE SELECT ON TABLES FROM sarana_auditor"
        )
        op.execute(f'REVOKE ALL ON ALL TABLES IN SCHEMA "{schema}" FROM sarana_auditor')
        op.execute(f'REVOKE USAGE ON SCHEMA "{schema}" FROM sarana_auditor')

    for table in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS append_only ON admin.{table}")
    for table in TOUCHED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS touch_updated_at ON admin.{table}")

    op.drop_index('ix_refresh_token_live', table_name='refresh_token', schema='admin', postgresql_where=sa.text('revoked_at IS NULL AND used_at IS NULL'))
    op.drop_index(op.f('ix_admin_refresh_token_user_id'), table_name='refresh_token', schema='admin')
    op.drop_index(op.f('ix_admin_refresh_token_device_id'), table_name='refresh_token', schema='admin')
    op.drop_table('refresh_token', schema='admin')
    op.drop_table('mfa_enrolment', schema='admin')
    op.drop_index('ix_device_user_active', table_name='device', schema='admin', postgresql_where=sa.text('revoked_at IS NULL'))
    op.drop_index(op.f('ix_admin_device_user_id'), table_name='device', schema='admin')
    op.drop_table('device', schema='admin')
    op.drop_index('ix_security_event_kind_time', table_name='security_event', schema='admin')
    op.drop_index(op.f('ix_admin_security_event_subject_id'), table_name='security_event', schema='admin')
    op.drop_table('security_event', schema='admin')
    op.drop_index('ix_otp_challenge_live', table_name='otp_challenge', schema='admin', postgresql_where=sa.text('consumed_at IS NULL'))
    op.drop_index('ix_otp_challenge_created', table_name='otp_challenge', schema='admin')
    op.drop_table('otp_challenge', schema='admin')
    op.drop_index('ix_login_attempt_source_time', table_name='login_attempt', schema='admin')
    op.drop_index('ix_login_attempt_account_time', table_name='login_attempt', schema='admin')
    op.drop_table('login_attempt', schema='admin')
