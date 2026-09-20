import { Pool } from "pg";
import { TenantStore } from "@opentalos/postgres-tenancy";
import { writeFixtureApiKey } from "./fixtures.js";

// Port 5434, NOT 5433 — this is the E2E-only Postgres (apps/web/e2e/docker-compose.yml), a
// separate container/port from the regular local-dev Postgres (scripts/docker-compose.postgres.yml,
// port 5433, what .env's DATABASE_URL points at). This file DROPs and reseeds every table below on
// every run; pointing it at the dev database would destroy real tenant/API-key/chat data every
// time the E2E suite runs (this actually happened once — see git history for the fix).
const DATABASE_URL = "postgres://postgres:postgres@localhost:5434/postgres";

export default async function globalSetup(): Promise<void> {
  const pool = new Pool({ connectionString: DATABASE_URL });
  try {
    await pool.query(`
      DROP TABLE IF EXISTS users;
      DROP TABLE IF EXISTS api_keys;
      DROP TABLE IF EXISTS tenants;
      DROP TABLE IF EXISTS trace_events;
      DROP TABLE IF EXISTS tasks;
      DROP TABLE IF EXISTS checkpoints;
      DROP TABLE IF EXISTS raw_memories;
      DROP TABLE IF EXISTS memories;

      CREATE TABLE checkpoints (
        run_id TEXT PRIMARY KEY, graph_id TEXT NOT NULL, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
        node_cursor JSONB NOT NULL, state JSONB NOT NULL, pending_yields JSONB NOT NULL, status TEXT NOT NULL,
        cancel_requested BOOLEAN NOT NULL DEFAULT false, steer_message TEXT, error TEXT,
        created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
      );
      CREATE TABLE tasks (
        id SERIAL PRIMARY KEY, run_id TEXT NOT NULL, graph_id TEXT NOT NULL, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
        kind TEXT NOT NULL, resume_value JSONB, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3, timeout_ms INTEGER NOT NULL DEFAULT 30000, priority INTEGER NOT NULL DEFAULT 0,
        available_at TIMESTAMPTZ NOT NULL DEFAULT now(), locked_at TIMESTAMPTZ, error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
      );
      CREATE TABLE trace_events (
        id SERIAL PRIMARY KEY, run_id TEXT NOT NULL, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
        type TEXT NOT NULL, payload JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
      );
      CREATE TABLE tenants (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL, max_concurrency INTEGER,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
      );
      CREATE TABLE api_keys (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, key_hash TEXT NOT NULL, key_prefix TEXT NOT NULL,
        status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_used_at TIMESTAMPTZ
      );
      CREATE TABLE users (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL UNIQUE, username TEXT NOT NULL, password_hash TEXT NOT NULL,
        status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
      );
      CREATE UNIQUE INDEX users_username_lower_idx ON users (lower(username));
      CREATE TABLE raw_memories (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL, run_id TEXT NOT NULL,
        content TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
      );
      CREATE TABLE memories (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, type TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'private',
        title TEXT NOT NULL, content TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now()
      );
      CREATE UNIQUE INDEX memories_tenant_id_title_idx ON memories (tenant_id, title);

      -- apps/api and apps/worker use a single Postgres pool for everything (see their DATABASE_URL
      -- usage), not just checkpoints/trace_events -- now that playwright.config.ts points that pool
      -- at opentalos_app instead of postgres, this connection also needs plain (non-RLS) access to
      -- the tenant/auth/task-queue tables it queries directly.
      GRANT SELECT, INSERT, UPDATE, DELETE ON tenants TO opentalos_app;
      GRANT SELECT, INSERT, UPDATE, DELETE ON api_keys TO opentalos_app;
      GRANT SELECT, INSERT, UPDATE, DELETE ON users TO opentalos_app;
      GRANT SELECT, INSERT, UPDATE, DELETE ON tasks TO opentalos_app;
      GRANT USAGE, SELECT ON SEQUENCE tasks_id_seq TO opentalos_app;

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
      GRANT USAGE, SELECT ON SEQUENCE trace_events_id_seq TO opentalos_app;

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
    `);

    const tenantStore = new TenantStore(pool);
    const defaultTenant = await tenantStore.createTenant("e2e-default-tenant");
    const { rawKey } = await tenantStore.createApiKey(defaultTenant.id);
    writeFixtureApiKey(rawKey);
  } catch (error) {
    throw new Error(
      `E2E global setup failed to reach Postgres at ${DATABASE_URL}. ` +
        `Did you run "docker compose -f apps/web/e2e/docker-compose.yml up -d" first? ` +
        `Original error: ${error instanceof Error ? error.message : String(error)}`,
    );
  } finally {
    await pool.end();
  }
}
