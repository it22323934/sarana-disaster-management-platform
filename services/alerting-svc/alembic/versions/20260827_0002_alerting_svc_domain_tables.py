"""domain tables for alerting-svc

Revision ID: alerting_svc_0002
Revises: alerting_svc_0001
Created: 2026-08-27 12:11:32.424517
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op

from sqlalchemy.dialects import postgresql

revision: str = "alerting_svc_0002"
down_revision: str | None = "alerting_svc_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('alert_template',
    sa.Column('code', sa.String(length=48), nullable=False),
    sa.Column('hazard_type', sa.String(length=16), nullable=False),
    sa.Column('severity', sa.String(length=12), nullable=False),
    sa.Column('urgency', sa.String(length=12), nullable=False),
    sa.Column('certainty', sa.String(length=12), nullable=False),
    sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('reviewed_by_si', sa.UUID(), nullable=True),
    sa.Column('reviewed_by_ta', sa.UUID(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('status', sa.String(length=16), server_default='DRAFT', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("certainty IN ('OBSERVED', 'LIKELY', 'POSSIBLE', 'UNLIKELY', 'UNKNOWN')", name=op.f('ck_alert_template_certainty_known')),
    sa.CheckConstraint("hazard_type IN ('FLOOD', 'LANDSLIDE', 'CYCLONE', 'DROUGHT', 'STORM_SURGE')", name=op.f('ck_alert_template_hazard_type_known')),
    sa.CheckConstraint("severity IN ('EXTREME', 'SEVERE', 'MODERATE', 'MINOR', 'UNKNOWN')", name=op.f('ck_alert_template_severity_known')),
    sa.CheckConstraint("status IN ('DRAFT', 'NATIVE_REVIEWED', 'PUBLISHED', 'RETIRED')", name=op.f('ck_alert_template_status_known')),
    sa.CheckConstraint("status NOT IN ('NATIVE_REVIEWED','PUBLISHED') OR (reviewed_by_si IS NOT NULL AND reviewed_by_ta IS NOT NULL     AND reviewed_at IS NOT NULL)", name=op.f('ck_alert_template_review_requires_native_speakers')),
    sa.CheckConstraint("urgency IN ('IMMEDIATE', 'EXPECTED', 'FUTURE', 'PAST', 'UNKNOWN')", name=op.f('ck_alert_template_urgency_known')),
    sa.CheckConstraint('public.all_locales_present(body)', name=op.f('ck_alert_template_body_all_locales')),
    sa.CheckConstraint('version > 0', name=op.f('ck_alert_template_version_positive')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alert_template')),
    sa.UniqueConstraint('code', 'version', name='uq_alert_template_code_version'),
    schema='alerting'
    )
    op.create_index(op.f('ix_alerting_alert_template_code'), 'alert_template', ['code'], unique=False, schema='alerting')
    op.create_table('alerting_svc_event',
    sa.Column('event_id', sa.UUID(), nullable=False),
    sa.Column('type', sa.String(length=200), nullable=False),
    sa.Column('schema_version', sa.Integer(), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('causation_id', sa.UUID(), nullable=True),
    sa.Column('source', sa.String(length=64), nullable=False),
    sa.Column('subject', sa.String(length=128), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('event_id', name=op.f('pk_alerting_svc_event')),
    schema='outbox'
    )
    op.create_index('ix_alerting_svc_event_unpublished', 'alerting_svc_event', ['created_at'], unique=False, schema='outbox', postgresql_where=sa.text('published_at IS NULL'))
    op.create_index(op.f('ix_outbox_alerting_svc_event_correlation_id'), 'alerting_svc_event', ['correlation_id'], unique=False, schema='outbox')
    op.create_index(op.f('ix_outbox_alerting_svc_event_type'), 'alerting_svc_event', ['type'], unique=False, schema='outbox')
    op.create_table('alert',
    sa.Column('hazard_event_id', sa.UUID(), nullable=False),
    sa.Column('template_id', sa.UUID(), nullable=True),
    sa.Column('cap_identifier', sa.String(length=128), nullable=False),
    sa.Column('cap_xml', sa.Text(), nullable=True),
    sa.Column('headline', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('description', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('instruction', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('severity', sa.String(length=12), nullable=False),
    sa.Column('urgency', sa.String(length=12), nullable=False),
    sa.Column('certainty', sa.String(length=12), nullable=False),
    sa.Column('effective_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('area_gn_division_ids', postgresql.ARRAY(sa.UUID()), nullable=False),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTIPOLYGON', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.Column('requires_human_signoff', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('signed_off_by', sa.UUID(), nullable=True),
    sa.Column('signed_off_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='DRAFT', nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("certainty IN ('OBSERVED', 'LIKELY', 'POSSIBLE', 'UNLIKELY', 'UNKNOWN')", name=op.f('ck_alert_certainty_known')),
    sa.CheckConstraint("severity IN ('EXTREME', 'SEVERE', 'MODERATE', 'MINOR', 'UNKNOWN')", name=op.f('ck_alert_severity_known')),
    sa.CheckConstraint("status IN ('DRAFT', 'PENDING_SIGNOFF', 'DISPATCHING', 'DISPATCHED', 'CANCELLED')", name=op.f('ck_alert_status_known')),
    sa.CheckConstraint("status NOT IN ('DISPATCHING','DISPATCHED') OR requires_human_signoff = false OR (signed_off_by IS NOT NULL AND signed_off_at IS NOT NULL)", name=op.f('ck_alert_free_text_requires_signoff')),
    sa.CheckConstraint("urgency IN ('IMMEDIATE', 'EXPECTED', 'FUTURE', 'PAST', 'UNKNOWN')", name=op.f('ck_alert_urgency_known')),
    sa.CheckConstraint('cardinality(area_gn_division_ids) > 0', name=op.f('ck_alert_alert_covers_an_area')),
    sa.CheckConstraint('expires_at > effective_at', name=op.f('ck_alert_expiry_after_effective')),
    sa.CheckConstraint('public.all_locales_present(description)', name=op.f('ck_alert_description_all_locales')),
    sa.CheckConstraint('public.all_locales_present(headline)', name=op.f('ck_alert_headline_all_locales')),
    sa.CheckConstraint('public.all_locales_present(instruction)', name=op.f('ck_alert_instruction_all_locales')),
    sa.CheckConstraint('template_id IS NOT NULL OR requires_human_signoff = true', name=op.f('ck_alert_untemplated_alert_is_gated')),
    sa.ForeignKeyConstraint(['template_id'], ['alerting.alert_template.id'], name=op.f('fk_alert_template_id_alert_template'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alert')),
    sa.UniqueConstraint('cap_identifier', name=op.f('uq_alert_cap_identifier')),
    schema='alerting'
    )
    op.create_index('ix_alert_effective', 'alert', ['effective_at'], unique=False, schema='alerting')
    op.create_index('ix_alert_geom', 'alert', ['geom'], unique=False, schema='alerting', postgresql_using='gist')
    op.create_index(op.f('ix_alerting_alert_correlation_id'), 'alert', ['correlation_id'], unique=False, schema='alerting')
    op.create_index(op.f('ix_alerting_alert_hazard_event_id'), 'alert', ['hazard_event_id'], unique=False, schema='alerting')
    op.create_index(op.f('ix_alerting_alert_status'), 'alert', ['status'], unique=False, schema='alerting')
    op.create_table('alert_dispatch',
    sa.Column('alert_id', sa.UUID(), nullable=False),
    sa.Column('channel', sa.String(length=12), nullable=False),
    sa.Column('target_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=12), server_default='QUEUED', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("channel IN ('SMS', 'USSD', 'PUSH', 'APP', 'LORA', 'RADIO', 'PAPER_QR')", name=op.f('ck_alert_dispatch_channel_known')),
    sa.CheckConstraint("status IN ('QUEUED', 'SENDING', 'COMPLETED', 'PARTIAL', 'FAILED')", name=op.f('ck_alert_dispatch_status_known')),
    sa.CheckConstraint('completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at', name=op.f('ck_alert_dispatch_completed_after_started')),
    sa.CheckConstraint('target_count >= 0', name=op.f('ck_alert_dispatch_target_count_non_negative')),
    sa.ForeignKeyConstraint(['alert_id'], ['alerting.alert.id'], name=op.f('fk_alert_dispatch_alert_id_alert'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alert_dispatch')),
    sa.UniqueConstraint('alert_id', 'channel', name='uq_alert_dispatch_channel'),
    schema='alerting'
    )
    op.create_index(op.f('ix_alerting_alert_dispatch_alert_id'), 'alert_dispatch', ['alert_id'], unique=False, schema='alerting')
    op.create_table('delivery_receipt',
    sa.Column('dispatch_id', sa.UUID(), nullable=False),
    sa.Column('channel', sa.String(length=12), nullable=False),
    sa.Column('target_ref_hash', sa.Text(), nullable=False),
    sa.Column('language', sa.String(length=2), nullable=False),
    sa.Column('status', sa.String(length=12), server_default='QUEUED', nullable=False),
    sa.Column('status_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('provider_ref', sa.String(length=128), nullable=True),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("channel IN ('SMS', 'USSD', 'PUSH', 'APP', 'LORA', 'RADIO', 'PAPER_QR')", name=op.f('ck_delivery_receipt_channel_known')),
    sa.CheckConstraint("language IN ('si','ta','en')", name=op.f('ck_delivery_receipt_language_supported')),
    sa.CheckConstraint("status <> 'FAILED' OR failure_reason IS NOT NULL", name=op.f('ck_delivery_receipt_failure_has_a_reason')),
    sa.CheckConstraint("status IN ('QUEUED', 'SENT', 'DELIVERED', 'READ', 'FAILED', 'EXPIRED')", name=op.f('ck_delivery_receipt_status_known')),
    sa.ForeignKeyConstraint(['dispatch_id'], ['alerting.alert_dispatch.id'], name=op.f('fk_delivery_receipt_dispatch_id_alert_dispatch'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_delivery_receipt')),
    schema='alerting'
    )
    op.create_index('ix_delivery_receipt_dispatch_status', 'delivery_receipt', ['dispatch_id', 'status'], unique=False, schema='alerting')
    op.create_index('ix_delivery_receipt_target', 'delivery_receipt', ['target_ref_hash'], unique=False, schema='alerting')


def downgrade() -> None:
    op.drop_index('ix_delivery_receipt_target', table_name='delivery_receipt', schema='alerting')
    op.drop_index('ix_delivery_receipt_dispatch_status', table_name='delivery_receipt', schema='alerting')
    op.drop_table('delivery_receipt', schema='alerting')
    op.drop_index(op.f('ix_alerting_alert_dispatch_alert_id'), table_name='alert_dispatch', schema='alerting')
    op.drop_table('alert_dispatch', schema='alerting')
    op.drop_index(op.f('ix_alerting_alert_status'), table_name='alert', schema='alerting')
    op.drop_index(op.f('ix_alerting_alert_hazard_event_id'), table_name='alert', schema='alerting')
    op.drop_index(op.f('ix_alerting_alert_correlation_id'), table_name='alert', schema='alerting')
    op.drop_index('ix_alert_geom', table_name='alert', schema='alerting', postgresql_using='gist')
    op.drop_index('ix_alert_effective', table_name='alert', schema='alerting')
    op.drop_table('alert', schema='alerting')
    op.drop_index(op.f('ix_outbox_alerting_svc_event_type'), table_name='alerting_svc_event', schema='outbox')
    op.drop_index(op.f('ix_outbox_alerting_svc_event_correlation_id'), table_name='alerting_svc_event', schema='outbox')
    op.drop_index('ix_alerting_svc_event_unpublished', table_name='alerting_svc_event', schema='outbox', postgresql_where=sa.text('published_at IS NULL'))
    op.drop_table('alerting_svc_event', schema='outbox')
    op.drop_index(op.f('ix_alerting_alert_template_code'), table_name='alert_template', schema='alerting')
    op.drop_table('alert_template', schema='alerting')
