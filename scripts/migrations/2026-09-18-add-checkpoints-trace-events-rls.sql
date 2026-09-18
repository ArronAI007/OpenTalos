-- Adds Postgres Row-Level Security to checkpoints/trace_events, plus a dedicated, non-superuser
-- business role (opentalos_app) that apps/api and apps/worker should connect as. See
-- docs/superpowers/specs/2026-09-17-checkpoint-tracing-rls-design.md for the full rationale.
--
-- This is defense-in-depth ON TOP OF the application-layer tenant_id filtering already added to
-- PostgresCheckpointStore's *ForTenant methods and listEventsSince() — RLS only visibly differs
-- from that application-layer filtering if a future query forgets to add its own tenant_id
-- condition. A brand-new instance bootstrapped via apps/web/e2e/global-setup.ts already creates
-- these objects and does not need this file.
--
-- SECURITY NOTE: the password below ('opentalos_app') is a placeholder suitable ONLY for a local,
-- not-network-exposed dev Postgres (the same threat model as this repo's existing dev-compose,
-- which already hardcodes POSTGRES_PASSWORD=postgres). If you run this migration against any
-- shared, staging, or production database, immediately follow it with:
--   ALTER ROLE opentalos_app WITH PASSWORD '<a real generated secret>';
-- and store that secret the same way this deployment already manages DATABASE_URL/other secrets
-- (never commit it to this file or to .env in git).

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'opentalos_app') THEN
    CREATE ROLE opentalos_app WITH LOGIN PASSWORD 'opentalos_app';
  END IF;
END
$$;

GRANT CONNECT ON DATABASE postgres TO opentalos_app;
GRANT USAGE ON SCHEMA public TO opentalos_app;

ALTER TABLE checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE checkpoints FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON checkpoints;
CREATE POLICY tenant_isolation ON checkpoints
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT, UPDATE, DELETE ON checkpoints TO opentalos_app;

ALTER TABLE trace_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE trace_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON trace_events;
CREATE POLICY tenant_isolation ON trace_events
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT, UPDATE, DELETE ON trace_events TO opentalos_app;
-- trace_events.id is a SERIAL (auto-increment via a sequence) — granting table privileges alone
-- does NOT grant the ability to call nextval() on the underlying sequence. Without this, INSERTs
-- from opentalos_app fail with "permission denied for sequence trace_events_id_seq" even though
-- the table GRANT above looks sufficient.
GRANT USAGE, SELECT ON SEQUENCE trace_events_id_seq TO opentalos_app;
