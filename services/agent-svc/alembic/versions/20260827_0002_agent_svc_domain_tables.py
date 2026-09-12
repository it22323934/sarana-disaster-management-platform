"""domain tables for agent-svc

Revision ID: agent_svc_0002
Revises: agent_svc_0001
Created: 2026-08-27 12:11:42.602593
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op

from sqlalchemy.dialects import postgresql

revision: str = "agent_svc_0002"
down_revision: str | None = "agent_svc_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('hazard_event',
    sa.Column('type', sa.String(length=16), nullable=False),
    sa.Column('name', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('source', sa.String(length=24), nullable=False),
    sa.Column('source_ref', sa.String(length=128), nullable=False),
    sa.Column('declared_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('landfall_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='MONITORING', nullable=False),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTIPOLYGON', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("source IN ('DEPT_METEOROLOGY', 'NBRO', 'DMC', 'IRRIGATION_DEPT', 'SATELLITE', 'FIELD_REPORT')", name=op.f('ck_hazard_event_source_known')),
    sa.CheckConstraint("status IN ('MONITORING', 'DECLARED', 'ACTIVE', 'SUBSIDING', 'CLOSED')", name=op.f('ck_hazard_event_status_known')),
    sa.CheckConstraint("type IN ('FLOOD', 'LANDSLIDE', 'CYCLONE', 'DROUGHT', 'STORM_SURGE')", name=op.f('ck_hazard_event_type_known')),
    sa.CheckConstraint('public.all_locales_present(name)', name=op.f('ck_hazard_event_name_all_locales')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hazard_event')),
    sa.UniqueConstraint('source', 'source_ref', name='uq_hazard_event_source_ref'),
    schema='hazard'
    )
    op.create_index('ix_hazard_event_geom', 'hazard_event', ['geom'], unique=False, schema='hazard', postgresql_using='gist')
    op.create_index('ix_hazard_event_status', 'hazard_event', ['status'], unique=False, schema='hazard')
    op.create_index(op.f('ix_hazard_hazard_event_correlation_id'), 'hazard_event', ['correlation_id'], unique=False, schema='hazard')
    op.create_table('agent_svc_event',
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
    sa.PrimaryKeyConstraint('event_id', name=op.f('pk_agent_svc_event')),
    schema='outbox'
    )
    op.create_index('ix_agent_svc_event_unpublished', 'agent_svc_event', ['created_at'], unique=False, schema='outbox', postgresql_where=sa.text('published_at IS NULL'))
    op.create_index(op.f('ix_outbox_agent_svc_event_correlation_id'), 'agent_svc_event', ['correlation_id'], unique=False, schema='outbox')
    op.create_index(op.f('ix_outbox_agent_svc_event_type'), 'agent_svc_event', ['type'], unique=False, schema='outbox')
    op.create_table('hazard_feed_reading',
    sa.Column('hazard_event_id', sa.UUID(), nullable=False),
    sa.Column('source', sa.String(length=24), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('ingested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("source IN ('DEPT_METEOROLOGY', 'NBRO', 'DMC', 'IRRIGATION_DEPT', 'SATELLITE', 'FIELD_REPORT')", name=op.f('ck_hazard_feed_reading_source_known')),
    sa.ForeignKeyConstraint(['hazard_event_id'], ['hazard.hazard_event.id'], name=op.f('fk_hazard_feed_reading_hazard_event_id_hazard_event'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hazard_feed_reading')),
    schema='hazard'
    )
    op.create_index('ix_hazard_feed_reading_event_time', 'hazard_feed_reading', ['hazard_event_id', 'observed_at'], unique=False, schema='hazard')
    op.create_index('ix_hazard_feed_reading_payload', 'hazard_feed_reading', ['payload'], unique=False, schema='hazard', postgresql_using='gin')
    op.create_table('impact_forecast',
    sa.Column('hazard_event_id', sa.UUID(), nullable=False),
    sa.Column('gn_division_id', sa.UUID(), nullable=False),
    sa.Column('gn_division_code', sa.String(length=16), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=False),
    sa.Column('impact_class', sa.SmallInteger(), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('lead_time_hours', sa.Integer(), nullable=False),
    sa.Column('method', sa.String(length=16), nullable=False),
    sa.Column('model_version', sa.String(length=32), nullable=True),
    sa.Column('drivers', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('expected_households_affected', sa.Integer(), server_default='0', nullable=False),
    sa.Column('expected_road_access_loss', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("drivers <> '{}'::jsonb", name=op.f('ck_impact_forecast_drivers_not_empty')),
    sa.CheckConstraint("jsonb_typeof(drivers) = 'object'", name=op.f('ck_impact_forecast_drivers_is_object')),
    sa.CheckConstraint("method IN ('RULE_THRESHOLD', 'MODEL')", name=op.f('ck_impact_forecast_method_known')),
    sa.CheckConstraint('confidence BETWEEN 0 AND 1', name=op.f('ck_impact_forecast_confidence_range')),
    sa.CheckConstraint('expected_households_affected >= 0', name=op.f('ck_impact_forecast_households_non_negative')),
    sa.CheckConstraint('impact_class BETWEEN 0 AND 4', name=op.f('ck_impact_forecast_impact_class_range')),
    sa.CheckConstraint('lead_time_hours >= 0', name=op.f('ck_impact_forecast_lead_time_non_negative')),
    sa.CheckConstraint('valid_to > valid_from', name=op.f('ck_impact_forecast_validity_ordered')),
    sa.ForeignKeyConstraint(['hazard_event_id'], ['hazard.hazard_event.id'], name=op.f('fk_impact_forecast_hazard_event_id_hazard_event'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_impact_forecast')),
    sa.UniqueConstraint('hazard_event_id', 'gn_division_id', 'generated_at', name='uq_impact_forecast_run'),
    schema='hazard'
    )
    op.create_index(op.f('ix_hazard_impact_forecast_correlation_id'), 'impact_forecast', ['correlation_id'], unique=False, schema='hazard')
    op.create_index('ix_impact_forecast_division', 'impact_forecast', ['gn_division_code', 'generated_at'], unique=False, schema='hazard')
    op.create_index('ix_impact_forecast_severe', 'impact_forecast', ['hazard_event_id', 'impact_class'], unique=False, schema='hazard')
    op.create_table('anticipatory_trigger',
    sa.Column('hazard_event_id', sa.UUID(), nullable=False),
    sa.Column('gn_division_id', sa.UUID(), nullable=True),
    sa.Column('gn_division_code', sa.String(length=16), nullable=True),
    sa.Column('condition', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('fired_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('action_taken', sa.String(length=32), nullable=True),
    sa.Column('forecast_id', sa.UUID(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("action_taken IS NULL OR action_taken IN ('ALERT_DRAFTED', 'PREPOSITION_REQUESTED', 'SHELTER_OPENED', 'EVACUATION_ADVISED', 'NO_ACTION')", name=op.f('ck_anticipatory_trigger_action_taken_known')),
    sa.CheckConstraint("condition <> '{}'::jsonb", name=op.f('ck_anticipatory_trigger_condition_not_empty')),
    sa.CheckConstraint("jsonb_typeof(condition) = 'object'", name=op.f('ck_anticipatory_trigger_condition_is_object')),
    sa.CheckConstraint('(fired_at IS NULL AND action_taken IS NULL) OR (fired_at IS NOT NULL AND action_taken IS NOT NULL)', name=op.f('ck_anticipatory_trigger_fired_trigger_records_its_action')),
    sa.ForeignKeyConstraint(['forecast_id'], ['hazard.impact_forecast.id'], name=op.f('fk_anticipatory_trigger_forecast_id_impact_forecast'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['hazard_event_id'], ['hazard.hazard_event.id'], name=op.f('fk_anticipatory_trigger_hazard_event_id_hazard_event'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_anticipatory_trigger')),
    schema='hazard'
    )
    op.create_index('ix_anticipatory_trigger_event', 'anticipatory_trigger', ['hazard_event_id', 'fired_at'], unique=False, schema='hazard')


def downgrade() -> None:
    op.drop_index('ix_anticipatory_trigger_event', table_name='anticipatory_trigger', schema='hazard')
    op.drop_table('anticipatory_trigger', schema='hazard')
    op.drop_index('ix_impact_forecast_severe', table_name='impact_forecast', schema='hazard')
    op.drop_index('ix_impact_forecast_division', table_name='impact_forecast', schema='hazard')
    op.drop_index(op.f('ix_hazard_impact_forecast_correlation_id'), table_name='impact_forecast', schema='hazard')
    op.drop_table('impact_forecast', schema='hazard')
    op.drop_index('ix_hazard_feed_reading_payload', table_name='hazard_feed_reading', schema='hazard', postgresql_using='gin')
    op.drop_index('ix_hazard_feed_reading_event_time', table_name='hazard_feed_reading', schema='hazard')
    op.drop_table('hazard_feed_reading', schema='hazard')
    op.drop_index(op.f('ix_outbox_agent_svc_event_type'), table_name='agent_svc_event', schema='outbox')
    op.drop_index(op.f('ix_outbox_agent_svc_event_correlation_id'), table_name='agent_svc_event', schema='outbox')
    op.drop_index('ix_agent_svc_event_unpublished', table_name='agent_svc_event', schema='outbox', postgresql_where=sa.text('published_at IS NULL'))
    op.drop_table('agent_svc_event', schema='outbox')
    op.drop_index(op.f('ix_hazard_hazard_event_correlation_id'), table_name='hazard_event', schema='hazard')
    op.drop_index('ix_hazard_event_status', table_name='hazard_event', schema='hazard')
    op.drop_index('ix_hazard_event_geom', table_name='hazard_event', schema='hazard', postgresql_using='gist')
    op.drop_table('hazard_event', schema='hazard')
