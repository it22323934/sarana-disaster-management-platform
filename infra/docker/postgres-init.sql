-- Runs once, on first container start (docker-entrypoint-initdb.d convention).
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;

-- Narrow application role vs. the owner role, per docs/build-prompts/04-data-model.md:
-- "the app never connects as the owner. Migrations run as a separate sarana_migrator
-- role." Grants are intentionally minimal here; docs/build-prompts/04 assigns the real
-- per-schema grants once the schemas themselves exist.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'sarana_app') THEN
        CREATE ROLE sarana_app WITH LOGIN PASSWORD 'sarana_app';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'sarana_migrator') THEN
        CREATE ROLE sarana_migrator WITH LOGIN PASSWORD 'sarana_migrator' CREATEDB;
    END IF;
END
$$;
