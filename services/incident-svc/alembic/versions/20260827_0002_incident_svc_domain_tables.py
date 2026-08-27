"""domain tables for incident-svc

Revision ID: incident_svc_0002
Revises: incident_svc_0001
Created: 2026-08-27 12:11:27.253682
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

from sqlalchemy.dialects import postgresql

revision: str = "incident_svc_0002"
down_revision: str | None = "incident_svc_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('dispatch_plan',
    sa.Column('incident_ids', postgresql.ARRAY(sa.UUID()), nullable=False),
    sa.Column('responder_ids', postgresql.ARRAY(sa.UUID()), server_default='{}', nullable=False),
    sa.Column('route', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('estimated_duration_min', sa.Integer(), nullable=True),
    sa.Column('proposed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('proposed_by_agent', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='PROPOSED', nullable=False),
    sa.Column('signed_off_by', sa.UUID(), nullable=True),
    sa.Column('signed_off_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rejection_reason', sa.Text(), nullable=True),
    sa.Column('langgraph_thread_id', sa.String(length=64), nullable=True),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status <> 'REJECTED' OR rejection_reason IS NOT NULL", name=op.f('ck_dispatch_plan_rejection_has_a_reason')),
    sa.CheckConstraint("status IN ('PROPOSED', 'AWAITING_SIGNOFF', 'APPROVED', 'REJECTED', 'RELEASED', 'COMPLETED')", name=op.f('ck_dispatch_plan_status_known')),
    sa.CheckConstraint("status NOT IN ('RELEASED','COMPLETED') OR (signed_off_by IS NOT NULL AND signed_off_at IS NOT NULL)", name=op.f('ck_dispatch_plan_released_requires_signoff')),
    sa.CheckConstraint('cardinality(incident_ids) > 0', name=op.f('ck_dispatch_plan_plan_covers_an_incident')),
    sa.CheckConstraint('estimated_duration_min IS NULL OR estimated_duration_min > 0', name=op.f('ck_dispatch_plan_duration_positive')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dispatch_plan')),
    schema='incident'
    )
    op.create_index('ix_dispatch_plan_status', 'dispatch_plan', ['status'], unique=False, schema='incident')
    op.create_index('ix_dispatch_plan_thread', 'dispatch_plan', ['langgraph_thread_id'], unique=False, schema='incident')
    op.create_index(op.f('ix_incident_dispatch_plan_correlation_id'), 'dispatch_plan', ['correlation_id'], unique=False, schema='incident')
    op.create_table('incident',
    sa.Column('public_ref', sa.String(length=24), nullable=False),
    sa.Column('gn_division_id', sa.UUID(), nullable=False),
    sa.Column('gn_division_code', sa.String(length=16), nullable=False),
    sa.Column('type', sa.String(length=32), nullable=False),
    sa.Column('subtype', sa.String(length=48), nullable=True),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('location', geoalchemy2.types.Geography(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeogFromText', name='geography'), nullable=True),
    sa.Column('location_confidence', sa.Numeric(precision=4, scale=3), nullable=True),
    sa.Column('people_at_risk', sa.Integer(), server_default='0', nullable=False),
    sa.Column('severity', sa.SmallInteger(), server_default='3', nullable=False),
    sa.Column('status', sa.String(length=16), server_default='REPORTED', nullable=False),
    sa.Column('first_reported_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cluster_id', sa.UUID(), nullable=True),
    sa.Column('is_cluster_primary', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("public_ref ~ '^INC-[0-9]{6}-[0-9A-HJKMNP-TV-Z]{6}$'", name=op.f('ck_incident_public_ref_shape')),
    sa.CheckConstraint("status IN ('REPORTED', 'VERIFIED', 'TRIAGED', 'DISPATCHED', 'IN_PROGRESS', 'RESOLVED', 'DUPLICATE', 'REJECTED')", name=op.f('ck_incident_status_known')),
    sa.CheckConstraint("type IN ('FLOOD', 'LANDSLIDE', 'STRUCTURAL_COLLAPSE', 'MEDICAL', 'MISSING_PERSON', 'TRAPPED', 'EVACUATION_NEEDED', 'SUPPLIES_NEEDED', 'INFRASTRUCTURE', 'OTHER')", name=op.f('ck_incident_type_known')),
    sa.CheckConstraint('location_confidence IS NULL OR location_confidence BETWEEN 0 AND 1', name=op.f('ck_incident_location_confidence_range')),
    sa.CheckConstraint('people_at_risk >= 0', name=op.f('ck_incident_people_at_risk_non_negative')),
    sa.CheckConstraint('resolved_at IS NULL OR resolved_at >= first_reported_at', name=op.f('ck_incident_resolved_after_reported')),
    sa.CheckConstraint('severity BETWEEN 1 AND 5', name=op.f('ck_incident_severity_range')),
    sa.CheckConstraint('summary IS NULL OR public.all_locales_present(summary)', name=op.f('ck_incident_summary_all_locales')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_incident')),
    sa.UniqueConstraint('public_ref', name=op.f('uq_incident_public_ref')),
    schema='incident'
    )
    op.create_index('ix_incident_cluster', 'incident', ['cluster_id'], unique=False, schema='incident')
    op.create_index(op.f('ix_incident_incident_correlation_id'), 'incident', ['correlation_id'], unique=False, schema='incident')
    op.create_index(op.f('ix_incident_incident_gn_division_code'), 'incident', ['gn_division_code'], unique=False, schema='incident')
    op.create_index(op.f('ix_incident_incident_gn_division_id'), 'incident', ['gn_division_id'], unique=False, schema='incident')
    op.create_index(op.f('ix_incident_incident_status'), 'incident', ['status'], unique=False, schema='incident')
    op.create_index('ix_incident_location', 'incident', ['location'], unique=False, schema='incident', postgresql_using='gist')
    op.create_index('ix_incident_open', 'incident', ['gn_division_id', 'severity'], unique=False, schema='incident', postgresql_where=sa.text("status <> 'RESOLVED'"))
    op.create_table('raw_report',
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('channel', sa.String(length=16), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('sender_msisdn_hash', sa.Text(), nullable=True),
    sa.Column('sender_household_id', sa.UUID(), nullable=True),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('raw_audio_uri', sa.Text(), nullable=True),
    sa.Column('raw_image_uris', postgresql.ARRAY(sa.Text()), nullable=True),
    sa.Column('reported_language', sa.String(length=2), nullable=True),
    sa.Column('reported_location', geoalchemy2.types.Geography(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeogFromText', name='geography'), nullable=True),
    sa.Column('location_accuracy_m', sa.Integer(), nullable=True),
    sa.Column('location_source', sa.String(length=16), nullable=True),
    sa.Column('processing_status', sa.String(length=16), server_default='RECEIVED', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("channel IN ('SMS', 'USSD', 'VOICE', 'APP', 'WEB', 'LORA', 'FIELD_OFFICER', 'PARTNER_API')", name=op.f('ck_raw_report_channel_known')),
    sa.CheckConstraint("location_source IS NULL OR location_source IN ('gps', 'cell', 'manual', 'inferred')", name=op.f('ck_raw_report_location_source_known')),
    sa.CheckConstraint("processing_status IN ('RECEIVED', 'TRANSCRIBING', 'VERIFYING', 'LINKED', 'REJECTED', 'HUMAN_REVIEW')", name=op.f('ck_raw_report_processing_status_known')),
    sa.CheckConstraint("reported_language IS NULL OR reported_language IN ('si','ta','en')", name=op.f('ck_raw_report_reported_language_supported')),
    sa.CheckConstraint('location_accuracy_m IS NULL OR location_accuracy_m > 0', name=op.f('ck_raw_report_location_accuracy_positive')),
    sa.CheckConstraint('reported_location IS NULL OR location_accuracy_m IS NOT NULL', name=op.f('ck_raw_report_location_has_accuracy')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_raw_report')),
    schema='incident'
    )
    op.create_index(op.f('ix_incident_raw_report_correlation_id'), 'raw_report', ['correlation_id'], unique=False, schema='incident')
    op.create_index(op.f('ix_incident_raw_report_processing_status'), 'raw_report', ['processing_status'], unique=False, schema='incident')
    op.create_index(op.f('ix_incident_raw_report_sender_household_id'), 'raw_report', ['sender_household_id'], unique=False, schema='incident')
    op.create_index('ix_raw_report_location', 'raw_report', ['reported_location'], unique=False, schema='incident', postgresql_using='gist')
    op.create_index('ix_raw_report_received_at', 'raw_report', ['received_at'], unique=False, schema='incident')
    op.create_index('ix_raw_report_sender', 'raw_report', ['sender_msisdn_hash'], unique=False, schema='incident')
    op.create_table('responder',
    sa.Column('org', sa.String(length=96), nullable=False),
    sa.Column('type', sa.String(length=24), nullable=False),
    sa.Column('capacity', sa.Integer(), server_default='0', nullable=False),
    sa.Column('home_gn_division_id', sa.UUID(), nullable=True),
    sa.Column('current_location', geoalchemy2.types.Geography(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeogFromText', name='geography'), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='AVAILABLE', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('AVAILABLE', 'ASSIGNED', 'EN_ROUTE', 'ON_SCENE', 'OFFLINE')", name=op.f('ck_responder_status_known')),
    sa.CheckConstraint("type IN ('AMBULANCE', 'FIRE', 'POLICE', 'MILITARY', 'NAVY', 'COAST_GUARD', 'VOLUNTEER', 'NGO', 'MEDICAL_TEAM', 'ENGINEERING')", name=op.f('ck_responder_type_known')),
    sa.CheckConstraint('capacity >= 0', name=op.f('ck_responder_capacity_non_negative')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_responder')),
    schema='incident'
    )
    op.create_index(op.f('ix_incident_responder_home_gn_division_id'), 'responder', ['home_gn_division_id'], unique=False, schema='incident')
    op.create_index(op.f('ix_incident_responder_status'), 'responder', ['status'], unique=False, schema='incident')
    op.create_index('ix_responder_current_location', 'responder', ['current_location'], unique=False, schema='incident', postgresql_using='gist')
    op.create_table('incident_svc_event',
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
    sa.PrimaryKeyConstraint('event_id', name=op.f('pk_incident_svc_event')),
    schema='outbox'
    )
    op.create_index('ix_incident_svc_event_unpublished', 'incident_svc_event', ['created_at'], unique=False, schema='outbox', postgresql_where=sa.text('published_at IS NULL'))
    op.create_index(op.f('ix_outbox_incident_svc_event_correlation_id'), 'incident_svc_event', ['correlation_id'], unique=False, schema='outbox')
    op.create_index(op.f('ix_outbox_incident_svc_event_type'), 'incident_svc_event', ['type'], unique=False, schema='outbox')
    op.create_table('report_embedding',
    sa.Column('raw_report_id', sa.UUID(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['raw_report_id'], ['incident.raw_report.id'], name=op.f('fk_report_embedding_raw_report_id_raw_report'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('raw_report_id', name=op.f('pk_report_embedding')),
    schema='incident'
    )
    op.create_index('ix_report_embedding_vector', 'report_embedding', ['embedding'], unique=False, schema='incident', postgresql_using='ivfflat', postgresql_with={'lists': 100}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_table('report_incident_link',
    sa.Column('raw_report_id', sa.UUID(), nullable=False),
    sa.Column('incident_id', sa.UUID(), nullable=False),
    sa.Column('similarity', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.Column('linked_by', sa.String(length=64), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('similarity BETWEEN 0 AND 1', name=op.f('ck_report_incident_link_similarity_range')),
    sa.ForeignKeyConstraint(['incident_id'], ['incident.incident.id'], name=op.f('fk_report_incident_link_incident_id_incident'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['raw_report_id'], ['incident.raw_report.id'], name=op.f('fk_report_incident_link_raw_report_id_raw_report'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_report_incident_link')),
    sa.UniqueConstraint('raw_report_id', 'incident_id', name='uq_report_incident'),
    schema='incident'
    )
    op.create_index(op.f('ix_incident_report_incident_link_incident_id'), 'report_incident_link', ['incident_id'], unique=False, schema='incident')
    op.create_index(op.f('ix_incident_report_incident_link_raw_report_id'), 'report_incident_link', ['raw_report_id'], unique=False, schema='incident')
    op.create_table('report_transcription',
    sa.Column('raw_report_id', sa.UUID(), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('detected_language', sa.String(length=2), nullable=True),
    sa.Column('text_original', sa.Text(), nullable=True),
    sa.Column('text_en', sa.Text(), nullable=True),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('needs_human_review', sa.Boolean(), nullable=False),
    sa.Column('reviewed_by', sa.UUID(), nullable=True),
    sa.Column('reviewed_text', sa.Text(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("detected_language IS NULL OR detected_language IN ('si','ta','en')", name=op.f('ck_report_transcription_detected_language_supported')),
    sa.CheckConstraint('(reviewed_text IS NULL) = (reviewed_by IS NULL)', name=op.f('ck_report_transcription_review_is_attributed')),
    sa.CheckConstraint('confidence BETWEEN 0 AND 1', name=op.f('ck_report_transcription_confidence_range')),
    sa.ForeignKeyConstraint(['raw_report_id'], ['incident.raw_report.id'], name=op.f('fk_report_transcription_raw_report_id_raw_report'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_report_transcription')),
    schema='incident'
    )
    op.create_index(op.f('ix_incident_report_transcription_raw_report_id'), 'report_transcription', ['raw_report_id'], unique=False, schema='incident')
    op.create_index('ix_report_transcription_review', 'report_transcription', ['needs_human_review'], unique=False, schema='incident')
    op.create_table('triage_score',
    sa.Column('incident_id', sa.UUID(), nullable=False),
    sa.Column('scored_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('score', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.Column('model_version', sa.String(length=32), nullable=False),
    sa.Column('factors', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('rank_in_queue', sa.Integer(), nullable=True),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("factors <> '{}'::jsonb", name=op.f('ck_triage_score_factors_not_empty')),
    sa.CheckConstraint("jsonb_typeof(factors) = 'object'", name=op.f('ck_triage_score_factors_is_object')),
    sa.CheckConstraint('rank_in_queue IS NULL OR rank_in_queue > 0', name=op.f('ck_triage_score_rank_positive')),
    sa.CheckConstraint('score BETWEEN 0 AND 1', name=op.f('ck_triage_score_score_range')),
    sa.ForeignKeyConstraint(['incident_id'], ['incident.incident.id'], name=op.f('fk_triage_score_incident_id_incident'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_triage_score')),
    schema='incident'
    )
    op.create_index('ix_triage_score_incident_time', 'triage_score', ['incident_id', 'scored_at'], unique=False, schema='incident')


def downgrade() -> None:
    op.drop_index('ix_triage_score_incident_time', table_name='triage_score', schema='incident')
    op.drop_table('triage_score', schema='incident')
    op.drop_index('ix_report_transcription_review', table_name='report_transcription', schema='incident')
    op.drop_index(op.f('ix_incident_report_transcription_raw_report_id'), table_name='report_transcription', schema='incident')
    op.drop_table('report_transcription', schema='incident')
    op.drop_index(op.f('ix_incident_report_incident_link_raw_report_id'), table_name='report_incident_link', schema='incident')
    op.drop_index(op.f('ix_incident_report_incident_link_incident_id'), table_name='report_incident_link', schema='incident')
    op.drop_table('report_incident_link', schema='incident')
    op.drop_index('ix_report_embedding_vector', table_name='report_embedding', schema='incident', postgresql_using='ivfflat', postgresql_with={'lists': 100}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_table('report_embedding', schema='incident')
    op.drop_index(op.f('ix_outbox_incident_svc_event_type'), table_name='incident_svc_event', schema='outbox')
    op.drop_index(op.f('ix_outbox_incident_svc_event_correlation_id'), table_name='incident_svc_event', schema='outbox')
    op.drop_index('ix_incident_svc_event_unpublished', table_name='incident_svc_event', schema='outbox', postgresql_where=sa.text('published_at IS NULL'))
    op.drop_table('incident_svc_event', schema='outbox')
    op.drop_index('ix_responder_current_location', table_name='responder', schema='incident', postgresql_using='gist')
    op.drop_index(op.f('ix_incident_responder_status'), table_name='responder', schema='incident')
    op.drop_index(op.f('ix_incident_responder_home_gn_division_id'), table_name='responder', schema='incident')
    op.drop_table('responder', schema='incident')
    op.drop_index('ix_raw_report_sender', table_name='raw_report', schema='incident')
    op.drop_index('ix_raw_report_received_at', table_name='raw_report', schema='incident')
    op.drop_index('ix_raw_report_location', table_name='raw_report', schema='incident', postgresql_using='gist')
    op.drop_index(op.f('ix_incident_raw_report_sender_household_id'), table_name='raw_report', schema='incident')
    op.drop_index(op.f('ix_incident_raw_report_processing_status'), table_name='raw_report', schema='incident')
    op.drop_index(op.f('ix_incident_raw_report_correlation_id'), table_name='raw_report', schema='incident')
    op.drop_table('raw_report', schema='incident')
    op.drop_index('ix_incident_open', table_name='incident', schema='incident', postgresql_where=sa.text("status <> 'RESOLVED'"))
    op.drop_index('ix_incident_location', table_name='incident', schema='incident', postgresql_using='gist')
    op.drop_index(op.f('ix_incident_incident_status'), table_name='incident', schema='incident')
    op.drop_index(op.f('ix_incident_incident_gn_division_id'), table_name='incident', schema='incident')
    op.drop_index(op.f('ix_incident_incident_gn_division_code'), table_name='incident', schema='incident')
    op.drop_index('ix_incident_cluster', table_name='incident', schema='incident')
    op.drop_table('incident', schema='incident')
    op.drop_index(op.f('ix_incident_dispatch_plan_correlation_id'), table_name='dispatch_plan', schema='incident')
    op.drop_index('ix_dispatch_plan_thread', table_name='dispatch_plan', schema='incident')
    op.drop_index('ix_dispatch_plan_status', table_name='dispatch_plan', schema='incident')
    op.drop_table('dispatch_plan', schema='incident')
