-- Give the application role a login for local development.
--
-- The role itself is created by the migrations, because its grants belong with the
-- tables they cover. What lives here is only the credential, and only for a laptop:
-- on AWS the password comes from Secrets Manager and this file is not used.
--
-- The application connects as sarana_app and never as the owner. That is not a
-- formality - a superuser bypasses row-level security entirely, and FORCE ROW LEVEL
-- SECURITY does not change that, so deploying with owner credentials would silently
-- disable every policy in the schema.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sarana_app') THEN
        CREATE ROLE sarana_app NOLOGIN;
    END IF;
END
$$;

ALTER ROLE sarana_app LOGIN PASSWORD 'sarana_app_local_only';
