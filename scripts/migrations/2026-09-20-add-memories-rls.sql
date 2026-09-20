-- Adds Postgres Row-Level Security to raw_memories/memories, mirroring the same policy shape as
-- scripts/migrations/2026-09-18-add-checkpoints-trace-events-rls.sql. That earlier migration
-- already created the opentalos_app role and the plain grants on tenants/api_keys/users/tasks —
-- this file assumes opentalos_app already exists and only adds what's new for these two tables.
-- See docs/superpowers/specs/2026-09-20-user-memory-module-design.md for the full rationale.
--
-- Mirrored by apps/web/e2e/global-setup.ts (same DDL, applied fresh to the ephemeral e2e Postgres
-- on every test run) and packages/postgres-memory/src/rls.test.ts (which hand-rolls an independent
-- copy against its own testcontainer, deliberately not reading this file) — if this policy's shape
-- ever changes, update all three, or the others will keep validating stale behavior.
--
-- FORCE matters even though opentalos_app is neither superuser nor table owner (see the longer
-- explanation in scripts/migrations/2026-09-18-add-checkpoints-trace-events-rls.sql): it protects
-- against a managed-Postgres deployment where the migration-running admin account is the table
-- OWNER without being a true superuser, in which case ENABLE alone would let that account silently
-- bypass RLS on any ad hoc query.
ALTER TABLE raw_memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_memories FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON raw_memories;
CREATE POLICY tenant_isolation ON raw_memories
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT, UPDATE, DELETE ON raw_memories TO opentalos_app;

ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE memories FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON memories;
CREATE POLICY tenant_isolation ON memories
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT, UPDATE, DELETE ON memories TO opentalos_app;
