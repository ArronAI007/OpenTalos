import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";
import { insertRawMemory, listRawMemoriesForTenant, upsertMemories, listMemoriesForTenant } from "./bulk.js";

// 跟 packages/postgres-checkpoint/src/rls.test.ts 同一个模式：独立 testcontainer + 手搓策略 SQL，
// 用非超级用户角色证明数据库层的 RLS 本身真的挡住了跨租户读取，而不是只验证了应用层的显式过滤。
const OPENTALOS_APP_PASSWORD = "opentalos_app";

let container: StartedPostgreSqlContainer;
let superuserPool: Pool;
let appPool: Pool;

beforeAll(async () => {
  container = await new PostgreSqlContainer("postgres:16-alpine").start();
  superuserPool = new Pool({ connectionString: container.getConnectionUri() });
  await superuserPool.query(`
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

    CREATE ROLE opentalos_app WITH LOGIN PASSWORD '${OPENTALOS_APP_PASSWORD}';
    GRANT CONNECT ON DATABASE postgres TO opentalos_app;
    GRANT USAGE ON SCHEMA public TO opentalos_app;

    ALTER TABLE raw_memories ENABLE ROW LEVEL SECURITY;
    ALTER TABLE raw_memories FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON raw_memories
      USING (tenant_id = current_setting('app.tenant_id', true))
      WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON raw_memories TO opentalos_app;

    ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
    ALTER TABLE memories FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON memories
      USING (tenant_id = current_setting('app.tenant_id', true))
      WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON memories TO opentalos_app;
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

describe("RLS database-level backstop (raw_memories, memories)", () => {
  it("a raw query with no explicit tenant_id filter, run as opentalos_app, still can't see another tenant's memories row", async () => {
    await superuserPool.query(
      `INSERT INTO memories (id, tenant_id, type, title, content) VALUES ('rls-mem-a', 'tenant-a', 'profile', 't', 'content-a')`,
    );
    await superuserPool.query(
      `INSERT INTO memories (id, tenant_id, type, title, content) VALUES ('rls-mem-b', 'tenant-b', 'profile', 't', 'content-b')`,
    );

    const client = await appPool.connect();
    try {
      await client.query("BEGIN");
      await client.query("SELECT set_config('app.tenant_id', $1, true)", ["tenant-a"]);
      const result = await client.query("SELECT id FROM memories ORDER BY id");
      const ids = result.rows.map((row: { id: string }) => row.id);
      expect(ids).toContain("rls-mem-a");
      expect(ids).not.toContain("rls-mem-b");
      await client.query("COMMIT");
    } finally {
      client.release();
    }
  });

  it("insertRawMemory/listRawMemoriesForTenant work correctly even when constructed with the RLS-restricted opentalos_app pool", async () => {
    await insertRawMemory(appPool, { tenantId: "tenant-rls-raw", sessionId: "s1", runId: "run-1", content: "喜欢简洁回复" });
    const rows = await listRawMemoriesForTenant(appPool, "tenant-rls-raw");
    expect(rows.map((r) => r.content)).toEqual(["喜欢简洁回复"]);
    expect(await listRawMemoriesForTenant(appPool, "tenant-other")).toEqual([]);
  });

  it("upsertMemories/listMemoriesForTenant work correctly even when constructed with the RLS-restricted opentalos_app pool", async () => {
    await upsertMemories(appPool, "tenant-rls-mem", { newEntries: [{ type: "profile", title: "职业", content: "工程师" }], updates: [] });
    const rows = await listMemoriesForTenant(appPool, "tenant-rls-mem");
    expect(rows).toMatchObject([{ title: "职业", content: "工程师" }]);
    expect(await listMemoriesForTenant(appPool, "tenant-other")).toEqual([]);
  });
});
