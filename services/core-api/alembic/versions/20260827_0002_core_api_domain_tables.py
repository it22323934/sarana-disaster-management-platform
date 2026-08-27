"""domain tables for core-api

Revision ID: core_api_0002
Revises: core_api_0001
Created: 2026-08-27 12:11:22.757939
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

from sqlalchemy.dialects import postgresql

revision: str = "core_api_0002"
down_revision: str | None = "core_api_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('app_user',
    sa.Column('email', sa.Text(), nullable=True),
    sa.Column('phone_hash', sa.Text(), nullable=True),
    sa.Column('password_hash', sa.Text(), nullable=True),
    sa.Column('full_name', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='INVITED', nullable=False),
    sa.Column('mfa_secret_encrypted', sa.LargeBinary(), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('INVITED','ACTIVE','SUSPENDED','DEACTIVATED')", name=op.f('ck_app_user_status_known')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_app_user')),
    sa.UniqueConstraint('email', name=op.f('uq_app_user_email')),
    sa.UniqueConstraint('phone_hash', name=op.f('uq_app_user_phone_hash')),
    schema='admin'
    )
    op.create_table('province',
    sa.Column('code', sa.String(length=8), nullable=False),
    sa.Column('name', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTIPOLYGON', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("code ~ '^LK-P[0-9]{2}$'", name=op.f('ck_province_code_shape')),
    sa.CheckConstraint('public.all_locales_present(name)', name=op.f('ck_province_name_all_locales')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_province')),
    sa.UniqueConstraint('code', name=op.f('uq_province_code')),
    schema='admin'
    )
    op.create_table('role',
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('name', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("code IN ('CITIZEN','GN_OFFICER','DS_APPROVER','DISTRICT_APPROVER','DMC_OPERATOR','DISPATCHER','AUDITOR','ADMIN')", name=op.f('ck_role_code_known')),
    sa.CheckConstraint('public.all_locales_present(name)', name=op.f('ck_role_name_all_locales')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_role')),
    sa.UniqueConstraint('code', name=op.f('uq_role_code')),
    schema='admin'
    )
    op.create_table('audit_entry',
    sa.Column('seq', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_type', sa.String(length=16), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('agent_name', sa.String(length=64), nullable=True),
    sa.Column('action', sa.String(length=96), nullable=False),
    sa.Column('subject_type', sa.String(length=48), nullable=False),
    sa.Column('subject_id', sa.String(length=64), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('langgraph_thread_id', sa.String(length=64), nullable=True),
    sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('prev_hash', sa.Text(), nullable=True),
    sa.Column('entry_hash', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("(actor_type = 'AGENT' AND agent_name IS NOT NULL) OR (actor_type = 'HUMAN' AND actor_id IS NOT NULL) OR actor_type = 'SYSTEM'", name=op.f('ck_audit_entry_actor_identified')),
    sa.CheckConstraint("actor_type IN ('AGENT', 'HUMAN', 'SYSTEM')", name=op.f('ck_audit_entry_actor_type_known')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_entry')),
    sa.UniqueConstraint('seq', name=op.f('uq_audit_entry_seq')),
    schema='audit'
    )
    op.create_index(op.f('ix_audit_audit_entry_action'), 'audit_entry', ['action'], unique=False, schema='audit')
    op.create_index('ix_audit_entry_correlation', 'audit_entry', ['correlation_id'], unique=False, schema='audit')
    op.create_index('ix_audit_entry_occurred_at', 'audit_entry', ['occurred_at'], unique=False, schema='audit')
    op.create_index('ix_audit_entry_subject', 'audit_entry', ['subject_type', 'subject_id'], unique=False, schema='audit')
    op.create_index('ix_audit_entry_thread', 'audit_entry', ['langgraph_thread_id'], unique=False, schema='audit')
    op.create_table('core_api_event',
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
    sa.PrimaryKeyConstraint('event_id', name=op.f('pk_core_api_event')),
    schema='outbox'
    )
    op.create_index('ix_core_api_event_unpublished', 'core_api_event', ['created_at'], unique=False, schema='outbox', postgresql_where=sa.text('published_at IS NULL'))
    op.create_index(op.f('ix_outbox_core_api_event_correlation_id'), 'core_api_event', ['correlation_id'], unique=False, schema='outbox')
    op.create_index(op.f('ix_outbox_core_api_event_type'), 'core_api_event', ['type'], unique=False, schema='outbox')
    op.create_table('rg_entity',
    sa.Column('entity_type', sa.String(length=32), nullable=False),
    sa.Column('natural_key', sa.String(length=128), nullable=False),
    sa.Column('attributes', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("entity_type IN ('gn_division', 'household', 'hazard_event', 'incident', 'asset', 'responder', 'shelter')", name=op.f('ck_rg_entity_entity_type_known')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rg_entity')),
    sa.UniqueConstraint('entity_type', 'natural_key', name='uq_rg_entity_type_key'),
    schema='resilience'
    )
    op.create_index(op.f('ix_resilience_rg_entity_entity_type'), 'rg_entity', ['entity_type'], unique=False, schema='resilience')
    op.create_index('ix_rg_entity_attributes', 'rg_entity', ['attributes'], unique=False, schema='resilience', postgresql_using='gin')
    op.create_index('ix_rg_entity_embedding', 'rg_entity', ['embedding'], unique=False, schema='resilience', postgresql_using='ivfflat', postgresql_with={'lists': 100}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_table('district',
    sa.Column('code', sa.String(length=8), nullable=False),
    sa.Column('province_id', sa.UUID(), nullable=False),
    sa.Column('name', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTIPOLYGON', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("code ~ '^LK-[0-9]{2}$'", name=op.f('ck_district_code_shape')),
    sa.CheckConstraint('public.all_locales_present(name)', name=op.f('ck_district_name_all_locales')),
    sa.ForeignKeyConstraint(['province_id'], ['admin.province.id'], name=op.f('fk_district_province_id_province'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_district')),
    sa.UniqueConstraint('code', name=op.f('uq_district_code')),
    schema='admin'
    )
    op.create_index(op.f('ix_admin_district_province_id'), 'district', ['province_id'], unique=False, schema='admin')
    op.create_index('ix_district_geom', 'district', ['geom'], unique=False, schema='admin', postgresql_using='gist')
    op.create_table('user_role',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('role_id', sa.UUID(), nullable=False),
    sa.Column('scope_type', sa.String(length=16), nullable=False),
    sa.Column('scope_code', sa.String(length=16), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(scope_type = 'NATIONAL' AND scope_code = 'LK') OR (scope_type = 'DISTRICT' AND scope_code ~ '^LK-[0-9]{2}$') OR (scope_type = 'DS' AND scope_code ~ '^LK-[0-9]{2}-[0-9]{2}$') OR (scope_type = 'GN' AND scope_code ~ '^LK-[0-9]{2}-[0-9]{2}-[0-9]{3}$')", name=op.f('ck_user_role_scope_code_matches_type')),
    sa.CheckConstraint("scope_type IN ('GN','DS','DISTRICT','NATIONAL')", name=op.f('ck_user_role_scope_type_known')),
    sa.ForeignKeyConstraint(['role_id'], ['admin.role.id'], name=op.f('fk_user_role_role_id_role'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['admin.app_user.id'], name=op.f('fk_user_role_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_role')),
    sa.UniqueConstraint('user_id', 'role_id', 'scope_code', name='uq_user_role_scope'),
    schema='admin'
    )
    op.create_index(op.f('ix_admin_user_role_role_id'), 'user_role', ['role_id'], unique=False, schema='admin')
    op.create_index(op.f('ix_admin_user_role_scope_code'), 'user_role', ['scope_code'], unique=False, schema='admin')
    op.create_index(op.f('ix_admin_user_role_user_id'), 'user_role', ['user_id'], unique=False, schema='admin')
    op.create_table('rg_observation',
    sa.Column('entity_id', sa.UUID(), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source_agent', sa.String(length=64), nullable=False),
    sa.Column('source_event_id', sa.UUID(), nullable=True),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('observation_type', sa.String(length=64), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint('confidence BETWEEN 0 AND 1', name=op.f('ck_rg_observation_confidence_range')),
    sa.ForeignKeyConstraint(['entity_id'], ['resilience.rg_entity.id'], name=op.f('fk_rg_observation_entity_id_rg_entity'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rg_observation')),
    schema='resilience'
    )
    op.create_index(op.f('ix_resilience_rg_observation_source_agent'), 'rg_observation', ['source_agent'], unique=False, schema='resilience')
    op.create_index('ix_rg_observation_correlation', 'rg_observation', ['correlation_id'], unique=False, schema='resilience')
    op.create_index('ix_rg_observation_entity_time', 'rg_observation', ['entity_id', 'observed_at'], unique=False, schema='resilience')
    op.create_table('rg_relation',
    sa.Column('from_entity_id', sa.UUID(), nullable=False),
    sa.Column('to_entity_id', sa.UUID(), nullable=False),
    sa.Column('relation_type', sa.String(length=32), nullable=False),
    sa.Column('attributes', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("relation_type IN ('located_in', 'affected_by', 'reported_by', 'assigned_to', 'shelters_at', 'depends_on', 'adjacent_to', 'supersedes')", name=op.f('ck_rg_relation_relation_type_known')),
    sa.CheckConstraint('confidence IS NULL OR confidence BETWEEN 0 AND 1', name=op.f('ck_rg_relation_confidence_range')),
    sa.CheckConstraint('from_entity_id <> to_entity_id', name=op.f('ck_rg_relation_no_self_relation')),
    sa.CheckConstraint('valid_to IS NULL OR valid_to > valid_from', name=op.f('ck_rg_relation_valid_period_ordered')),
    sa.ForeignKeyConstraint(['from_entity_id'], ['resilience.rg_entity.id'], name=op.f('fk_rg_relation_from_entity_id_rg_entity'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['to_entity_id'], ['resilience.rg_entity.id'], name=op.f('fk_rg_relation_to_entity_id_rg_entity'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rg_relation')),
    schema='resilience'
    )
    op.create_index('ix_rg_relation_from_type', 'rg_relation', ['from_entity_id', 'relation_type'], unique=False, schema='resilience')
    op.create_index('ix_rg_relation_open', 'rg_relation', ['relation_type', 'from_entity_id'], unique=False, schema='resilience', postgresql_where=sa.text('valid_to IS NULL'))
    op.create_index('ix_rg_relation_to_type', 'rg_relation', ['to_entity_id', 'relation_type'], unique=False, schema='resilience')
    op.create_table('ds_division',
    sa.Column('code', sa.String(length=12), nullable=False),
    sa.Column('district_id', sa.UUID(), nullable=False),
    sa.Column('name', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTIPOLYGON', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("code ~ '^LK-[0-9]{2}-[0-9]{2}$'", name=op.f('ck_ds_division_code_shape')),
    sa.CheckConstraint('public.all_locales_present(name)', name=op.f('ck_ds_division_name_all_locales')),
    sa.ForeignKeyConstraint(['district_id'], ['admin.district.id'], name=op.f('fk_ds_division_district_id_district'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ds_division')),
    sa.UniqueConstraint('code', name=op.f('uq_ds_division_code')),
    schema='admin'
    )
    op.create_index(op.f('ix_admin_ds_division_district_id'), 'ds_division', ['district_id'], unique=False, schema='admin')
    op.create_index('ix_ds_division_geom', 'ds_division', ['geom'], unique=False, schema='admin', postgresql_using='gist')
    op.create_table('gn_division',
    sa.Column('code', sa.String(length=16), nullable=False),
    sa.Column('ds_division_id', sa.UUID(), nullable=False),
    sa.Column('name', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTIPOLYGON', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.Column('centroid', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.Column('population', sa.Integer(), server_default='0', nullable=False),
    sa.Column('household_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('elderly_pct', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('under5_pct', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('landslide_zone', sa.SmallInteger(), nullable=True),
    sa.Column('flood_return_period_m', sa.Integer(), nullable=True),
    sa.Column('road_access_class', sa.SmallInteger(), nullable=True),
    sa.Column('cell_coverage_pct', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("code ~ '^LK-[0-9]{2}-[0-9]{2}-[0-9]{3}$'", name=op.f('ck_gn_division_code_shape')),
    sa.CheckConstraint('cell_coverage_pct IS NULL OR cell_coverage_pct BETWEEN 0 AND 100', name=op.f('ck_gn_division_cell_coverage_pct_range')),
    sa.CheckConstraint('elderly_pct IS NULL OR elderly_pct BETWEEN 0 AND 100', name=op.f('ck_gn_division_elderly_pct_range')),
    sa.CheckConstraint('household_count >= 0', name=op.f('ck_gn_division_household_count_non_negative')),
    sa.CheckConstraint('landslide_zone IS NULL OR landslide_zone BETWEEN 1 AND 4', name=op.f('ck_gn_division_landslide_zone_range')),
    sa.CheckConstraint('population >= 0', name=op.f('ck_gn_division_population_non_negative')),
    sa.CheckConstraint('public.all_locales_present(name)', name=op.f('ck_gn_division_name_all_locales')),
    sa.CheckConstraint('under5_pct IS NULL OR under5_pct BETWEEN 0 AND 100', name=op.f('ck_gn_division_under5_pct_range')),
    sa.ForeignKeyConstraint(['ds_division_id'], ['admin.ds_division.id'], name=op.f('fk_gn_division_ds_division_id_ds_division'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_gn_division')),
    sa.UniqueConstraint('code', name=op.f('uq_gn_division_code')),
    schema='admin'
    )
    op.create_index(op.f('ix_admin_gn_division_ds_division_id'), 'gn_division', ['ds_division_id'], unique=False, schema='admin')
    op.create_index('ix_gn_division_centroid', 'gn_division', ['centroid'], unique=False, schema='admin', postgresql_using='gist')
    op.create_index('ix_gn_division_geom', 'gn_division', ['geom'], unique=False, schema='admin', postgresql_using='gist')
    op.create_table('household',
    sa.Column('gn_division_id', sa.UUID(), nullable=False),
    sa.Column('reference_code', sa.String(length=32), nullable=False),
    sa.Column('head_name_encrypted', sa.LargeBinary(), nullable=True),
    sa.Column('contact_msisdn_encrypted', sa.LargeBinary(), nullable=True),
    sa.Column('contact_msisdn_hash', sa.Text(), nullable=True),
    sa.Column('member_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('has_over_70', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('has_under_5', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('has_mobility_impairment', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('location', geoalchemy2.types.Geography(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeogFromText', name='geography'), nullable=True),
    sa.Column('location_accuracy_m', sa.Integer(), nullable=True),
    sa.Column('preferred_language', sa.String(length=2), server_default='si', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("preferred_language IN ('si','ta','en')", name=op.f('ck_household_preferred_language_supported')),
    sa.CheckConstraint('location_accuracy_m IS NULL OR location_accuracy_m > 0', name=op.f('ck_household_location_accuracy_positive')),
    sa.CheckConstraint('member_count >= 0', name=op.f('ck_household_member_count_non_negative')),
    sa.ForeignKeyConstraint(['gn_division_id'], ['admin.gn_division.id'], name=op.f('fk_household_gn_division_id_gn_division'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_household')),
    sa.UniqueConstraint('reference_code', name=op.f('uq_household_reference_code')),
    schema='admin'
    )
    op.create_index(op.f('ix_admin_household_contact_msisdn_hash'), 'household', ['contact_msisdn_hash'], unique=False, schema='admin')
    op.create_index(op.f('ix_admin_household_gn_division_id'), 'household', ['gn_division_id'], unique=False, schema='admin')
    op.create_index('ix_household_location', 'household', ['location'], unique=False, schema='admin', postgresql_using='gist')


def downgrade() -> None:
    op.drop_index('ix_household_location', table_name='household', schema='admin', postgresql_using='gist')
    op.drop_index(op.f('ix_admin_household_gn_division_id'), table_name='household', schema='admin')
    op.drop_index(op.f('ix_admin_household_contact_msisdn_hash'), table_name='household', schema='admin')
    op.drop_table('household', schema='admin')
    op.drop_index('ix_gn_division_geom', table_name='gn_division', schema='admin', postgresql_using='gist')
    op.drop_index('ix_gn_division_centroid', table_name='gn_division', schema='admin', postgresql_using='gist')
    op.drop_index(op.f('ix_admin_gn_division_ds_division_id'), table_name='gn_division', schema='admin')
    op.drop_table('gn_division', schema='admin')
    op.drop_index('ix_ds_division_geom', table_name='ds_division', schema='admin', postgresql_using='gist')
    op.drop_index(op.f('ix_admin_ds_division_district_id'), table_name='ds_division', schema='admin')
    op.drop_table('ds_division', schema='admin')
    op.drop_index('ix_rg_relation_to_type', table_name='rg_relation', schema='resilience')
    op.drop_index('ix_rg_relation_open', table_name='rg_relation', schema='resilience', postgresql_where=sa.text('valid_to IS NULL'))
    op.drop_index('ix_rg_relation_from_type', table_name='rg_relation', schema='resilience')
    op.drop_table('rg_relation', schema='resilience')
    op.drop_index('ix_rg_observation_entity_time', table_name='rg_observation', schema='resilience')
    op.drop_index('ix_rg_observation_correlation', table_name='rg_observation', schema='resilience')
    op.drop_index(op.f('ix_resilience_rg_observation_source_agent'), table_name='rg_observation', schema='resilience')
    op.drop_table('rg_observation', schema='resilience')
    op.drop_index(op.f('ix_admin_user_role_user_id'), table_name='user_role', schema='admin')
    op.drop_index(op.f('ix_admin_user_role_scope_code'), table_name='user_role', schema='admin')
    op.drop_index(op.f('ix_admin_user_role_role_id'), table_name='user_role', schema='admin')
    op.drop_table('user_role', schema='admin')
    op.drop_index('ix_district_geom', table_name='district', schema='admin', postgresql_using='gist')
    op.drop_index(op.f('ix_admin_district_province_id'), table_name='district', schema='admin')
    op.drop_table('district', schema='admin')
    op.drop_index('ix_rg_entity_embedding', table_name='rg_entity', schema='resilience', postgresql_using='ivfflat', postgresql_with={'lists': 100}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_index('ix_rg_entity_attributes', table_name='rg_entity', schema='resilience', postgresql_using='gin')
    op.drop_index(op.f('ix_resilience_rg_entity_entity_type'), table_name='rg_entity', schema='resilience')
    op.drop_table('rg_entity', schema='resilience')
    op.drop_index(op.f('ix_outbox_core_api_event_type'), table_name='core_api_event', schema='outbox')
    op.drop_index(op.f('ix_outbox_core_api_event_correlation_id'), table_name='core_api_event', schema='outbox')
    op.drop_index('ix_core_api_event_unpublished', table_name='core_api_event', schema='outbox', postgresql_where=sa.text('published_at IS NULL'))
    op.drop_table('core_api_event', schema='outbox')
    op.drop_index('ix_audit_entry_thread', table_name='audit_entry', schema='audit')
    op.drop_index('ix_audit_entry_subject', table_name='audit_entry', schema='audit')
    op.drop_index('ix_audit_entry_occurred_at', table_name='audit_entry', schema='audit')
    op.drop_index('ix_audit_entry_correlation', table_name='audit_entry', schema='audit')
    op.drop_index(op.f('ix_audit_audit_entry_action'), table_name='audit_entry', schema='audit')
    op.drop_table('audit_entry', schema='audit')
    op.drop_table('role', schema='admin')
    op.drop_table('province', schema='admin')
    op.drop_table('app_user', schema='admin')
