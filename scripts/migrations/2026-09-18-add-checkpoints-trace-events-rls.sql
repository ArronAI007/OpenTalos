-- Adds Postgres Row-Level Security to checkpoints/trace_events, plus a dedicated, non-superuser
-- business role (opentalos_app) that apps/api and apps/worker should connect as. See
-- docs/superpowers/specs/2026-09-17-checkpoint-tracing-rls-design.md for the full rationale.
--
-- This is defense-in-depth ON TOP OF the application-layer tenant_id filtering already added to
-- PostgresCheckpointStore's *ForTenant methods and listEventsSince() — RLS only visibly differs
-- from that application-layer filtering if a future query forgets to add its own tenant_id
-- condition. apps/web/e2e/global-setup.ts does NOT yet create these objects as of this commit —
-- that wiring lands in a later task of the same plan (see
-- docs/superpowers/plans/2026-09-18-checkpoint-tracing-rls.md, Task 9). Until that task lands,
-- this migration has only been applied to the local dev Postgres (manually — see THIS task's own
-- Step 2, Task 5, not Task 9's) — apps/api/apps/worker still connect as the plain `postgres`
-- superuser everywhere (including local dev) until DATABASE_URL is switched over, a deliberately
-- manual step (see the same plan's Task 10).
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

-- FORCE matters even though opentalos_app is neither superuser nor table owner (for whom ENABLE
-- alone already applies RLS): it protects against a DIFFERENT, realistic scenario — many managed
-- Postgres providers (RDS, Cloud SQL, Supabase, ...) have the migration-running admin account be
-- the table OWNER without being a true superuser. Without FORCE, that owner account would
-- silently bypass RLS on any ad hoc query (e.g. a manual psql debugging session), which is exactly
-- the kind of "someone forgot to filter" gap this whole feature exists to close.
ALTER TABLE checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE checkpoints FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON checkpoints;
-- The `true` here is current_setting's "missing_ok" parameter (returns NULL instead of erroring
-- when app.tenant_id was never set) — a completely different boolean from set_config's `is_local`
-- parameter used elsewhere in this codebase (PostgresCheckpointStore, PostgresEventBus), despite
-- the same literal token. An unset app.tenant_id therefore becomes `tenant_id = NULL`, which is
-- never TRUE under SQL's three-valued logic — the policy fails CLOSED (denies every row) rather
-- than erroring, which is the safer default for a session variable a caller forgot to set.
CREATE POLICY tenant_isolation ON checkpoints
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT, UPDATE, DELETE ON checkpoints TO opentalos_app;

-- Mirrored by packages/postgres-checkpoint/src/rls.test.ts and packages/postgres-tracing/src/rls.test.ts,
-- which each hand-roll an independent copy of this same policy DDL against their own testcontainer
-- (deliberately not reading this file, so those tests stay self-contained for CI/fresh clones) —
-- if this policy's shape ever changes, update both test files' setup SQL to match, or the tests
-- will keep validating stale behavior while claiming to guard the current migration.
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
