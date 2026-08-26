-- Extensions and service schemas. Runs once, on first start of an empty data volume.
--
-- ADR-002: one PostgreSQL, schema per service. Creating the schemas here rather than in
-- a migration means every service's first migration can assume its schema exists and
-- alembic's version table has somewhere to live.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Shared platform tables: the transactional outbox and the idempotency-key store.
CREATE SCHEMA IF NOT EXISTS platform;
-- Sri Lanka administrative hierarchy and other reference data. Read by everything.
CREATE SCHEMA IF NOT EXISTS reference;
-- The Resilience Graph: typed entities, bitemporal relations, append-only observations.
CREATE SCHEMA IF NOT EXISTS resilience;

CREATE SCHEMA IF NOT EXISTS incident;
CREATE SCHEMA IF NOT EXISTS alerting;
CREATE SCHEMA IF NOT EXISTS ledger;
CREATE SCHEMA IF NOT EXISTS agent;

-- Everything is stored UTC and rendered in Asia/Colombo at the boundary.
-- :DBNAME is set by psql to the database this script is running against.
ALTER DATABASE :"DBNAME" SET timezone TO 'UTC';
