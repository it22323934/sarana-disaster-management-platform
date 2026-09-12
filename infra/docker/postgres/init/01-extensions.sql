-- Extensions only. Runs once, on first start of an empty data volume.
--
-- Schemas are NOT created here. They are created by the Alembic migration of the service
-- that owns them, so that a database built by `make migrate` against an empty cluster -
-- CI, a test container, a fresh RDS instance - is identical to one built by compose.
-- Anything created here and nowhere else would silently exist only on a developer laptop.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Everything is stored UTC and rendered in Asia/Colombo at the boundary.
-- :DBNAME is set by psql to the database this script is running against.
ALTER DATABASE :"DBNAME" SET timezone TO 'UTC';
