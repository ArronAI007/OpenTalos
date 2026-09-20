-- Adds Postgres Row-Level Security to raw_memories/memories, mirroring the same policy shape as
-- scripts/migrations/2026-09-18-add-checkpoints-trace-events-rls.sql. That earlier migration
-- already created the opentalos_app role and the plain grants on tenants/api_keys/users/tasks —
-- this file assumes opentalos_app already exists and only adds what's new for these two tables.
-- See docs/superpowers/specs/2026-09-20-user-memory-module-design.md for the full rationale.

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
