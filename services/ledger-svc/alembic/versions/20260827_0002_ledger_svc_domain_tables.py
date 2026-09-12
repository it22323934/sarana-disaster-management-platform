"""domain tables for ledger-svc

Revision ID: ledger_svc_0002
Revises: ledger_svc_0001
Created: 2026-08-27 12:11:37.442807
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op

from sqlalchemy.dialects import postgresql

revision: str = "ledger_svc_0002"
down_revision: str | None = "ledger_svc_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('anomaly_flag',
    sa.Column('subject_type', sa.String(length=24), nullable=False),
    sa.Column('subject_id', sa.UUID(), nullable=False),
    sa.Column('detector', sa.String(length=64), nullable=False),
    sa.Column('detector_version', sa.String(length=32), nullable=False),
    sa.Column('score', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.Column('rationale', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('raised_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('disposition', sa.String(length=24), server_default='OPEN', nullable=False),
    sa.Column('disposed_by', sa.UUID(), nullable=True),
    sa.Column('disposed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('disposition_note', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(disposition = 'OPEN' AND disposed_by IS NULL AND disposed_at IS NULL) OR (disposition <> 'OPEN' AND disposed_by IS NOT NULL     AND disposed_at IS NOT NULL AND disposition_note IS NOT NULL)", name=op.f('ck_anomaly_flag_disposition_is_attributed')),
    sa.CheckConstraint("NOT public.jsonb_contains_any_key(rationale, ARRAY['officer_id', 'assessed_by', 'user_id', 'approver_id', 'released_by', 'gn_officer']::text[])", name=op.f('ck_anomaly_flag_rationale_names_no_one')),
    sa.CheckConstraint("disposition IN ('OPEN', 'REVIEWED_NO_ACTION', 'REVIEWED_ESCALATED', 'FALSE_POSITIVE')", name=op.f('ck_anomaly_flag_disposition_known')),
    sa.CheckConstraint("jsonb_typeof(rationale) = 'object'", name=op.f('ck_anomaly_flag_rationale_is_object')),
    sa.CheckConstraint("rationale <> '{}'::jsonb", name=op.f('ck_anomaly_flag_rationale_not_empty')),
    sa.CheckConstraint("subject_type IN ('ASSESSMENT', 'ENTITLEMENT', 'DISBURSEMENT', 'GN_DIVISION', 'COST_SCHEDULE')", name=op.f('ck_anomaly_flag_subject_type_known')),
    sa.CheckConstraint('score BETWEEN 0 AND 1', name=op.f('ck_anomaly_flag_score_range')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_anomaly_flag')),
    schema='aid'
    )
    op.create_index(op.f('ix_aid_anomaly_flag_detector'), 'anomaly_flag', ['detector'], unique=False, schema='aid')
    op.create_index('ix_anomaly_flag_open', 'anomaly_flag', ['disposition'], unique=False, schema='aid')
    op.create_index('ix_anomaly_flag_subject', 'anomaly_flag', ['subject_type', 'subject_id'], unique=False, schema='aid')
    op.create_table('cost_schedule',
    sa.Column('version', sa.String(length=16), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source_ref', sa.Text(), nullable=True),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("version ~ '^\\d{4}\\.\\d{2}(\\.\\d+)?$'", name=op.f('ck_cost_schedule_version_shape')),
    sa.CheckConstraint('effective_to IS NULL OR effective_to > effective_from', name=op.f('ck_cost_schedule_effective_period_ordered')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cost_schedule')),
    sa.UniqueConstraint('version', name='uq_cost_schedule_version'),
    schema='aid'
    )
    op.create_table('damage_assessment',
    sa.Column('public_ref', sa.String(length=24), nullable=False),
    sa.Column('household_id', sa.UUID(), nullable=False),
    sa.Column('gn_division_id', sa.UUID(), nullable=False),
    sa.Column('gn_division_code', sa.String(length=16), nullable=False),
    sa.Column('hazard_event_id', sa.UUID(), nullable=False),
    sa.Column('assessed_by', sa.UUID(), nullable=False),
    sa.Column('assessed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('subcategory', sa.String(length=48), server_default='', nullable=False),
    sa.Column('cost_estimate_lkr_cents', sa.BigInteger(), nullable=False),
    sa.Column('evidence_photo_uris', postgresql.ARRAY(sa.Text()), nullable=True),
    sa.Column('evidence_hash', sa.Text(), nullable=True),
    sa.Column('gps_at_assessment', geoalchemy2.types.Geography(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeogFromText', name='geography'), nullable=True),
    sa.Column('gps_accuracy_m', sa.Integer(), nullable=True),
    sa.Column('client_operation_id', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='DRAFT', nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("category IN ('HOUSE_FULL', 'HOUSE_PARTIAL', 'HOUSEHOLD_GOODS', 'LIVELIHOOD_TOOLS', 'CROP', 'LIVESTOCK', 'FISHING_GEAR', 'DEATH', 'INJURY')", name=op.f('ck_damage_assessment_category_known')),
    sa.CheckConstraint("public_ref ~ '^DMG-[0-9]{6}-[0-9A-HJKMNP-TV-Z]{6}$'", name=op.f('ck_damage_assessment_public_ref_shape')),
    sa.CheckConstraint("status <> 'ACCEPTED' OR evidence_hash IS NOT NULL", name=op.f('ck_damage_assessment_accepted_assessment_has_evidence')),
    sa.CheckConstraint("status IN ('DRAFT', 'SUBMITTED', 'UNDER_REVIEW', 'ACCEPTED', 'REJECTED', 'SUPERSEDED')", name=op.f('ck_damage_assessment_status_known')),
    sa.CheckConstraint('cost_estimate_lkr_cents >= 0', name=op.f('ck_damage_assessment_cost_estimate_non_negative')),
    sa.CheckConstraint('gps_accuracy_m IS NULL OR gps_accuracy_m > 0', name=op.f('ck_damage_assessment_gps_accuracy_positive')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_damage_assessment')),
    sa.UniqueConstraint('client_operation_id', name='uq_assessment_client_operation'),
    sa.UniqueConstraint('public_ref', name=op.f('uq_damage_assessment_public_ref')),
    schema='aid'
    )
    op.create_index(op.f('ix_aid_damage_assessment_assessed_by'), 'damage_assessment', ['assessed_by'], unique=False, schema='aid')
    op.create_index(op.f('ix_aid_damage_assessment_correlation_id'), 'damage_assessment', ['correlation_id'], unique=False, schema='aid')
    op.create_index(op.f('ix_aid_damage_assessment_gn_division_id'), 'damage_assessment', ['gn_division_id'], unique=False, schema='aid')
    op.create_index(op.f('ix_aid_damage_assessment_hazard_event_id'), 'damage_assessment', ['hazard_event_id'], unique=False, schema='aid')
    op.create_index(op.f('ix_aid_damage_assessment_status'), 'damage_assessment', ['status'], unique=False, schema='aid')
    op.create_index('ix_damage_assessment_division_status', 'damage_assessment', ['gn_division_code', 'status'], unique=False, schema='aid')
    op.create_index('ix_damage_assessment_gps', 'damage_assessment', ['gps_at_assessment'], unique=False, schema='aid', postgresql_using='gist')
    op.create_index('ix_damage_assessment_household', 'damage_assessment', ['household_id'], unique=False, schema='aid')
    op.create_table('grievance',
    sa.Column('public_ref', sa.String(length=24), nullable=False),
    sa.Column('household_id', sa.UUID(), nullable=False),
    sa.Column('subject_type', sa.String(length=24), nullable=False),
    sa.Column('subject_id', sa.UUID(), nullable=True),
    sa.Column('channel', sa.String(length=16), nullable=False),
    sa.Column('raised_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('description', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='RECEIVED', nullable=False),
    sa.Column('assigned_ds_division_id', sa.UUID(), nullable=True),
    sa.Column('assigned_ds_division_code', sa.String(length=16), nullable=True),
    sa.Column('sla_due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolution', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("channel IN ('SMS', 'USSD', 'APP', 'IN_PERSON', 'PHONE', 'WEB')", name=op.f('ck_grievance_channel_known')),
    sa.CheckConstraint("public_ref ~ '^GRV-[0-9]{6}-[0-9A-HJKMNP-TV-Z]{6}$'", name=op.f('ck_grievance_public_ref_shape')),
    sa.CheckConstraint("status IN ('RECEIVED', 'ACKNOWLEDGED', 'UNDER_REVIEW', 'RESOLVED', 'REJECTED', 'ESCALATED')", name=op.f('ck_grievance_status_known')),
    sa.CheckConstraint("status NOT IN ('RESOLVED','REJECTED') OR (resolved_at IS NOT NULL AND resolution IS NOT NULL)", name=op.f('ck_grievance_resolution_is_explained')),
    sa.CheckConstraint("subject_type IN ('ASSESSMENT', 'ENTITLEMENT', 'DISBURSEMENT', 'EXCLUSION')", name=op.f('ck_grievance_subject_type_known')),
    sa.CheckConstraint('public.all_locales_present(description)', name=op.f('ck_grievance_description_all_locales')),
    sa.CheckConstraint('resolution IS NULL OR public.all_locales_present(resolution)', name=op.f('ck_grievance_resolution_all_locales')),
    sa.CheckConstraint('sla_due_at > raised_at', name=op.f('ck_grievance_sla_is_in_the_future')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_grievance')),
    sa.UniqueConstraint('public_ref', name=op.f('uq_grievance_public_ref')),
    schema='aid'
    )
    op.create_index(op.f('ix_aid_grievance_correlation_id'), 'grievance', ['correlation_id'], unique=False, schema='aid')
    op.create_index(op.f('ix_aid_grievance_household_id'), 'grievance', ['household_id'], unique=False, schema='aid')
    op.create_index(op.f('ix_aid_grievance_status'), 'grievance', ['status'], unique=False, schema='aid')
    op.create_index('ix_grievance_ds_status', 'grievance', ['assigned_ds_division_code', 'status'], unique=False, schema='aid')
    op.create_index('ix_grievance_sla', 'grievance', ['sla_due_at'], unique=False, schema='aid')
    op.create_index('ix_grievance_subject', 'grievance', ['subject_type', 'subject_id'], unique=False, schema='aid')
    op.create_table('ledger_anchor',
    sa.Column('anchor_date', sa.Date(), nullable=False),
    sa.Column('merkle_root', sa.Text(), nullable=False),
    sa.Column('entry_count', sa.Integer(), nullable=False),
    sa.Column('first_seq', sa.BigInteger(), nullable=False),
    sa.Column('last_seq', sa.BigInteger(), nullable=False),
    sa.Column('s3_object_lock_uri', sa.Text(), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("merkle_root ~ '^[0-9a-f]{64}$'", name=op.f('ck_ledger_anchor_merkle_root_is_sha256')),
    sa.CheckConstraint('entry_count > 0', name=op.f('ck_ledger_anchor_anchor_covers_entries')),
    sa.CheckConstraint('last_seq >= first_seq', name=op.f('ck_ledger_anchor_seq_range_ordered')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ledger_anchor')),
    sa.UniqueConstraint('anchor_date', name='uq_ledger_anchor_date'),
    schema='aid'
    )
    op.create_table('ledger_svc_event',
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
    sa.PrimaryKeyConstraint('event_id', name=op.f('pk_ledger_svc_event')),
    schema='outbox'
    )
    op.create_index('ix_ledger_svc_event_unpublished', 'ledger_svc_event', ['created_at'], unique=False, schema='outbox', postgresql_where=sa.text('published_at IS NULL'))
    op.create_index(op.f('ix_outbox_ledger_svc_event_correlation_id'), 'ledger_svc_event', ['correlation_id'], unique=False, schema='outbox')
    op.create_index(op.f('ix_outbox_ledger_svc_event_type'), 'ledger_svc_event', ['type'], unique=False, schema='outbox')
    op.create_table('cost_schedule_line',
    sa.Column('cost_schedule_id', sa.UUID(), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('subcategory', sa.String(length=48), server_default='', nullable=False),
    sa.Column('description', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('unit', sa.String(length=24), nullable=False),
    sa.Column('rate_lkr_cents', sa.BigInteger(), nullable=False),
    sa.Column('cap_lkr_cents', sa.BigInteger(), nullable=True),
    sa.Column('formula', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("category IN ('HOUSE_FULL', 'HOUSE_PARTIAL', 'HOUSEHOLD_GOODS', 'LIVELIHOOD_TOOLS', 'CROP', 'LIVESTOCK', 'FISHING_GEAR', 'DEATH', 'INJURY')", name=op.f('ck_cost_schedule_line_category_known')),
    sa.CheckConstraint('cap_lkr_cents IS NULL OR cap_lkr_cents >= rate_lkr_cents', name=op.f('ck_cost_schedule_line_cap_above_rate')),
    sa.CheckConstraint('public.all_locales_present(description)', name=op.f('ck_cost_schedule_line_description_all_locales')),
    sa.CheckConstraint('rate_lkr_cents >= 0', name=op.f('ck_cost_schedule_line_rate_non_negative')),
    sa.ForeignKeyConstraint(['cost_schedule_id'], ['aid.cost_schedule.id'], name=op.f('fk_cost_schedule_line_cost_schedule_id_cost_schedule'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cost_schedule_line')),
    sa.UniqueConstraint('cost_schedule_id', 'category', 'subcategory', name='uq_cost_schedule_line'),
    schema='aid'
    )
    op.create_index(op.f('ix_aid_cost_schedule_line_cost_schedule_id'), 'cost_schedule_line', ['cost_schedule_id'], unique=False, schema='aid')
    op.create_table('entitlement',
    sa.Column('assessment_id', sa.UUID(), nullable=False),
    sa.Column('cost_schedule_id', sa.UUID(), nullable=False),
    sa.Column('cost_schedule_version', sa.String(length=16), nullable=False),
    sa.Column('calculated_lkr_cents', sa.BigInteger(), nullable=False),
    sa.Column('calculation_trace', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('calculated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='CALCULATED', nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("calculation_trace <> '{}'::jsonb", name=op.f('ck_entitlement_trace_not_empty')),
    sa.CheckConstraint("cost_schedule_version ~ '^\\d{4}\\.\\d{2}(\\.\\d+)?$'", name=op.f('ck_entitlement_version_shape')),
    sa.CheckConstraint("jsonb_typeof(calculation_trace) = 'object'", name=op.f('ck_entitlement_trace_is_object')),
    sa.CheckConstraint("status IN ('CALCULATED', 'AWAITING_DS', 'AWAITING_DISTRICT', 'APPROVED', 'REJECTED', 'DISBURSED')", name=op.f('ck_entitlement_status_known')),
    sa.CheckConstraint('calculated_lkr_cents >= 0', name=op.f('ck_entitlement_amount_non_negative')),
    sa.ForeignKeyConstraint(['assessment_id'], ['aid.damage_assessment.id'], name=op.f('fk_entitlement_assessment_id_damage_assessment'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['cost_schedule_id'], ['aid.cost_schedule.id'], name=op.f('fk_entitlement_cost_schedule_id_cost_schedule'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_entitlement')),
    sa.UniqueConstraint('assessment_id', name='uq_entitlement_assessment'),
    schema='aid'
    )
    op.create_index(op.f('ix_aid_entitlement_correlation_id'), 'entitlement', ['correlation_id'], unique=False, schema='aid')
    op.create_index(op.f('ix_aid_entitlement_cost_schedule_id'), 'entitlement', ['cost_schedule_id'], unique=False, schema='aid')
    op.create_index(op.f('ix_aid_entitlement_status'), 'entitlement', ['status'], unique=False, schema='aid')
    op.create_table('approval',
    sa.Column('seq', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('entitlement_id', sa.UUID(), nullable=False),
    sa.Column('level', sa.String(length=12), nullable=False),
    sa.Column('approver_id', sa.UUID(), nullable=False),
    sa.Column('decision', sa.String(length=12), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('prev_hash', sa.Text(), nullable=True),
    sa.Column('entry_hash', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("decision = 'APPROVED' OR reason IS NOT NULL", name=op.f('ck_approval_refusal_has_a_reason')),
    sa.CheckConstraint("decision IN ('APPROVED', 'REJECTED', 'RETURNED')", name=op.f('ck_approval_decision_known')),
    sa.CheckConstraint("level IN ('DS', 'DISTRICT')", name=op.f('ck_approval_level_known')),
    sa.ForeignKeyConstraint(['entitlement_id'], ['aid.entitlement.id'], name=op.f('fk_approval_entitlement_id_entitlement'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approval')),
    sa.UniqueConstraint('entitlement_id', 'level', name='uq_approval_entitlement_level'),
    sa.UniqueConstraint('seq', name=op.f('uq_approval_seq')),
    schema='aid'
    )
    op.create_index(op.f('ix_aid_approval_approver_id'), 'approval', ['approver_id'], unique=False, schema='aid')
    op.create_index(op.f('ix_aid_approval_entitlement_id'), 'approval', ['entitlement_id'], unique=False, schema='aid')
    op.create_index('ix_approval_seq', 'approval', ['seq'], unique=False, schema='aid')
    op.create_table('disbursement',
    sa.Column('seq', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('entitlement_id', sa.UUID(), nullable=False),
    sa.Column('amount_lkr_cents', sa.BigInteger(), nullable=False),
    sa.Column('released_by', sa.UUID(), nullable=False),
    sa.Column('released_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('payment_rail', sa.String(length=20), nullable=False),
    sa.Column('payment_ref', sa.String(length=128), nullable=True),
    sa.Column('prev_hash', sa.Text(), nullable=True),
    sa.Column('entry_hash', sa.Text(), nullable=True),
    sa.Column('citizen_confirmed', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('citizen_confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('citizen_confirm_channel', sa.String(length=16), nullable=True),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("payment_rail IN ('BANK_TRANSFER', 'MOBILE_MONEY', 'POST_OFFICE', 'CASH')", name=op.f('ck_disbursement_payment_rail_known')),
    sa.CheckConstraint('amount_lkr_cents > 0', name=op.f('ck_disbursement_amount_positive')),
    sa.CheckConstraint('citizen_confirmed = false OR citizen_confirmed_at IS NOT NULL', name=op.f('ck_disbursement_confirmation_is_timestamped')),
    sa.ForeignKeyConstraint(['entitlement_id'], ['aid.entitlement.id'], name=op.f('fk_disbursement_entitlement_id_entitlement'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_disbursement')),
    sa.UniqueConstraint('entitlement_id', name='uq_disbursement_entitlement'),
    sa.UniqueConstraint('seq', name=op.f('uq_disbursement_seq')),
    schema='aid'
    )
    op.create_index(op.f('ix_aid_disbursement_correlation_id'), 'disbursement', ['correlation_id'], unique=False, schema='aid')
    op.create_index(op.f('ix_aid_disbursement_released_by'), 'disbursement', ['released_by'], unique=False, schema='aid')
    op.create_index('ix_disbursement_released_at', 'disbursement', ['released_at'], unique=False, schema='aid')
    op.create_index('ix_disbursement_seq', 'disbursement', ['seq'], unique=False, schema='aid')


def downgrade() -> None:
    op.drop_index('ix_disbursement_seq', table_name='disbursement', schema='aid')
    op.drop_index('ix_disbursement_released_at', table_name='disbursement', schema='aid')
    op.drop_index(op.f('ix_aid_disbursement_released_by'), table_name='disbursement', schema='aid')
    op.drop_index(op.f('ix_aid_disbursement_correlation_id'), table_name='disbursement', schema='aid')
    op.drop_table('disbursement', schema='aid')
    op.drop_index('ix_approval_seq', table_name='approval', schema='aid')
    op.drop_index(op.f('ix_aid_approval_entitlement_id'), table_name='approval', schema='aid')
    op.drop_index(op.f('ix_aid_approval_approver_id'), table_name='approval', schema='aid')
    op.drop_table('approval', schema='aid')
    op.drop_index(op.f('ix_aid_entitlement_status'), table_name='entitlement', schema='aid')
    op.drop_index(op.f('ix_aid_entitlement_cost_schedule_id'), table_name='entitlement', schema='aid')
    op.drop_index(op.f('ix_aid_entitlement_correlation_id'), table_name='entitlement', schema='aid')
    op.drop_table('entitlement', schema='aid')
    op.drop_index(op.f('ix_aid_cost_schedule_line_cost_schedule_id'), table_name='cost_schedule_line', schema='aid')
    op.drop_table('cost_schedule_line', schema='aid')
    op.drop_index(op.f('ix_outbox_ledger_svc_event_type'), table_name='ledger_svc_event', schema='outbox')
    op.drop_index(op.f('ix_outbox_ledger_svc_event_correlation_id'), table_name='ledger_svc_event', schema='outbox')
    op.drop_index('ix_ledger_svc_event_unpublished', table_name='ledger_svc_event', schema='outbox', postgresql_where=sa.text('published_at IS NULL'))
    op.drop_table('ledger_svc_event', schema='outbox')
    op.drop_table('ledger_anchor', schema='aid')
    op.drop_index('ix_grievance_subject', table_name='grievance', schema='aid')
    op.drop_index('ix_grievance_sla', table_name='grievance', schema='aid')
    op.drop_index('ix_grievance_ds_status', table_name='grievance', schema='aid')
    op.drop_index(op.f('ix_aid_grievance_status'), table_name='grievance', schema='aid')
    op.drop_index(op.f('ix_aid_grievance_household_id'), table_name='grievance', schema='aid')
    op.drop_index(op.f('ix_aid_grievance_correlation_id'), table_name='grievance', schema='aid')
    op.drop_table('grievance', schema='aid')
    op.drop_index('ix_damage_assessment_household', table_name='damage_assessment', schema='aid')
    op.drop_index('ix_damage_assessment_gps', table_name='damage_assessment', schema='aid', postgresql_using='gist')
    op.drop_index('ix_damage_assessment_division_status', table_name='damage_assessment', schema='aid')
    op.drop_index(op.f('ix_aid_damage_assessment_status'), table_name='damage_assessment', schema='aid')
    op.drop_index(op.f('ix_aid_damage_assessment_hazard_event_id'), table_name='damage_assessment', schema='aid')
    op.drop_index(op.f('ix_aid_damage_assessment_gn_division_id'), table_name='damage_assessment', schema='aid')
    op.drop_index(op.f('ix_aid_damage_assessment_correlation_id'), table_name='damage_assessment', schema='aid')
    op.drop_index(op.f('ix_aid_damage_assessment_assessed_by'), table_name='damage_assessment', schema='aid')
    op.drop_table('damage_assessment', schema='aid')
    op.drop_table('cost_schedule', schema='aid')
    op.drop_index('ix_anomaly_flag_subject', table_name='anomaly_flag', schema='aid')
    op.drop_index('ix_anomaly_flag_open', table_name='anomaly_flag', schema='aid')
    op.drop_index(op.f('ix_aid_anomaly_flag_detector'), table_name='anomaly_flag', schema='aid')
    op.drop_table('anomaly_flag', schema='aid')
