import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";
import { listEventsSince, PostgresEventBus } from "./event-bus.js";

const OPENTALOS_APP_PASSWORD = "opentalos_app";

let container: StartedPostgreSqlContainer;
let superuserPool: Pool;
let appPool: Pool;

beforeAll(async () => {
  container = await new PostgreSqlContainer("postgres:16-alpine").start();
  superuserPool = new Pool({ connectionString: container.getConnectionUri() });
  await superuserPool.query(`
    CREATE TABLE trace_events (
      id SERIAL PRIMARY KEY, run_id TEXT NOT NULL, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
      type TEXT NOT NULL, payload JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE ROLE opentalos_app WITH LOGIN PASSWORD '${OPENTALOS_APP_PASSWORD}';
    GRANT CONNECT ON DATABASE postgres TO opentalos_app;
    GRANT USAGE ON SCHEMA public TO opentalos_app;

    ALTER TABLE trace_events ENABLE ROW LEVEL SECURITY;
    ALTER TABLE trace_events FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON trace_events
      USING (tenant_id = current_setting('app.tenant_id', true))
      WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON trace_events TO opentalos_app;
    GRANT USAGE, SELECT ON SEQUENCE trace_events_id_seq TO opentalos_app;
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

describe("RLS database-level backstop (trace_events)", () => {
  it("a raw query with no explicit tenant_id filter, run as opentalos_app with app.tenant_id set, still can't see another tenant's row", async () => {
    await superuserPool.query(
      `INSERT INTO trace_events (run_id, tenant_id, session_id, type) VALUES ('rls-run', 'tenant-a', 's1', 'node_enter')`,
    );
    await superuserPool.query(
      `INSERT INTO trace_events (run_id, tenant_id, session_id, type) VALUES ('rls-run', 'tenant-b', 's1', 'node_enter')`,
    );

    const client = await appPool.connect();
    try {
      await client.query("BEGIN");
      await client.query("SELECT set_config('app.tenant_id', $1, true)", ["tenant-a"]);
      const result = await client.query("SELECT tenant_id FROM trace_events WHERE run_id = 'rls-run'");
      const tenantIds = result.rows.map((row: { tenant_id: string }) => row.tenant_id);
      expect(tenantIds).toEqual(["tenant-a"]);
      await client.query("COMMIT");
    } finally {
      client.release();
    }
  });

  it("listEventsSince works correctly even when given the RLS-restricted opentalos_app pool", async () => {
    await superuserPool.query(
      `INSERT INTO trace_events (run_id, tenant_id, session_id, type) VALUES ('rls-list-run', 'tenant-a', 's1', 'node_enter')`,
    );

    const asOwner = await listEventsSince(appPool, "rls-list-run", 0, "tenant-a");
    expect(asOwner).toHaveLength(1);

    const asOther = await listEventsSince(appPool, "rls-list-run", 0, "tenant-b");
    expect(asOther).toHaveLength(0);
  });

  it("PostgresEventBus.emit() works correctly even when constructed with the RLS-restricted opentalos_app pool", async () => {
    const bus = new PostgresEventBus(appPool);
    bus.emit({
      runId: "rls-emit-run",
      tenantId: "tenant-a",
      sessionId: "s1",
      type: "node_enter",
      timestamp: new Date().toISOString(),
    });
    await bus.flush();

    const asOwner = await listEventsSince(appPool, "rls-emit-run", 0, "tenant-a");
    expect(asOwner).toHaveLength(1);
  });
});
