import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";
import { PostgresCheckpointStore } from "./store.js";

// This suite exists ONLY to prove the database-level backstop actually works — i.e. that even a
// query which forgets to add its own `WHERE tenant_id = ...` condition still can't read another
// tenant's row, because RLS itself blocks it. store.test.ts already covers the application-layer
// filtering (the *ForTenant methods' own explicit WHERE clauses) under the default superuser
// connection; that layer alone would pass even if RLS were completely broken, so it can't prove
// RLS itself works. This file specifically uses a non-superuser role for that reason.
const OPENTALOS_APP_PASSWORD = "opentalos_app";

let container: StartedPostgreSqlContainer;
let superuserPool: Pool;
let appPool: Pool;

beforeAll(async () => {
  container = await new PostgreSqlContainer("postgres:16-alpine").start();
  superuserPool = new Pool({ connectionString: container.getConnectionUri() });
  await superuserPool.query(`
    CREATE TABLE checkpoints (
      run_id TEXT PRIMARY KEY, graph_id TEXT NOT NULL, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
      node_cursor JSONB NOT NULL, state JSONB NOT NULL, pending_yields JSONB NOT NULL, status TEXT NOT NULL,
      cancel_requested BOOLEAN NOT NULL DEFAULT false, steer_message TEXT, error TEXT,
      created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE ROLE opentalos_app WITH LOGIN PASSWORD '${OPENTALOS_APP_PASSWORD}';
    GRANT CONNECT ON DATABASE postgres TO opentalos_app;
    GRANT USAGE ON SCHEMA public TO opentalos_app;

    ALTER TABLE checkpoints ENABLE ROW LEVEL SECURITY;
    ALTER TABLE checkpoints FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON checkpoints
      USING (tenant_id = current_setting('app.tenant_id', true))
      WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON checkpoints TO opentalos_app;
  `);

  const connectionUrl = new URL(container.getConnectionUri());
  connectionUrl.username = "opentalos_app";
  connectionUrl.password = OPENTALOS_APP_PASSWORD;
  appPool = new Pool({ connectionString: connectionUrl.toString() });
}, 120_000);

afterAll(async () => {
  await appPool.end();
  await superuserPool.end();
  await container.stop();
});

describe("RLS database-level backstop (checkpoints)", () => {
  it("a raw query with no explicit tenant_id filter, run as opentalos_app with app.tenant_id set, still can't see another tenant's row", async () => {
    // Seed two tenants' rows via the superuser connection (bypasses RLS, so this always works
    // regardless of what's under test — this is setup, not the assertion).
    await superuserPool.query(
      `INSERT INTO checkpoints (run_id, graph_id, tenant_id, session_id, node_cursor, state, pending_yields, status, created_at)
       VALUES ('rls-run-a', 'g1', 'tenant-a', 's1', '"start"', '{}', '[]', 'running', now())`,
    );
    await superuserPool.query(
      `INSERT INTO checkpoints (run_id, graph_id, tenant_id, session_id, node_cursor, state, pending_yields, status, created_at)
       VALUES ('rls-run-b', 'g1', 'tenant-b', 's1', '"start"', '{}', '[]', 'running', now())`,
    );

    const client = await appPool.connect();
    try {
      await client.query("BEGIN");
      await client.query("SELECT set_config('app.tenant_id', $1, true)", ["tenant-a"]);
      // Deliberately NOT filtering by tenant_id here — this is the "someone forgot the WHERE
      // clause" scenario the database-level policy exists to catch.
      const result = await client.query("SELECT run_id FROM checkpoints ORDER BY run_id");
      const runIds = result.rows.map((row: { run_id: string }) => row.run_id);
      expect(runIds).toContain("rls-run-a");
      expect(runIds).not.toContain("rls-run-b");
      await client.query("COMMIT");
    } finally {
      client.release();
    }
  });

  it("PostgresCheckpointStore's own loadForTenant works correctly even when constructed with the RLS-restricted opentalos_app pool", async () => {
    const store = new PostgresCheckpointStore(appPool);
    await superuserPool.query(
      `INSERT INTO checkpoints (run_id, graph_id, tenant_id, session_id, node_cursor, state, pending_yields, status, created_at)
       VALUES ('rls-store-run', 'g1', 'tenant-a', 's1', '"start"', '{}', '[]', 'running', now())`,
    );

    await expect(store.loadForTenant("rls-store-run", "tenant-a")).resolves.toMatchObject({ runId: "rls-store-run" });
    await expect(store.loadForTenant("rls-store-run", "tenant-b")).resolves.toBeUndefined();
  });

  it("PostgresCheckpointStore's own save() works correctly even when constructed with the RLS-restricted opentalos_app pool", async () => {
    const store = new PostgresCheckpointStore(appPool);
    await store.save({
      runId: "rls-save-run",
      graphId: "g1",
      tenantId: "tenant-a",
      sessionId: "s1",
      nodeCursor: "start",
      state: {},
      pendingYields: [],
      status: "running",
      createdAt: new Date().toISOString(),
      cancelRequested: false,
    });

    // Confirm it's readable back through the SAME restricted pool, scoped to its own tenant.
    await expect(store.loadForTenant("rls-save-run", "tenant-a")).resolves.toMatchObject({ runId: "rls-save-run" });
    // And genuinely invisible to a different tenant, proving the WITH CHECK constraint accepted
    // the write under the correct tenant_id rather than some other mechanism papering over this.
    await expect(store.loadForTenant("rls-save-run", "tenant-b")).resolves.toBeUndefined();
  });
});
