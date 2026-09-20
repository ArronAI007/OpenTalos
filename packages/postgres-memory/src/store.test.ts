import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";
import { PostgresMemoryStore } from "./store.js";

let container: StartedPostgreSqlContainer;
let pool: Pool;
let store: PostgresMemoryStore;

beforeAll(async () => {
  container = await new PostgreSqlContainer("postgres:16-alpine").start();
  pool = new Pool({ connectionString: container.getConnectionUri() });
  await pool.query(`
    CREATE TABLE memories (
      id TEXT PRIMARY KEY,
      tenant_id TEXT NOT NULL,
      type TEXT NOT NULL,
      scope TEXT NOT NULL DEFAULT 'private',
      title TEXT NOT NULL,
      content TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      last_confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
  `);
  store = new PostgresMemoryStore(pool);
}, 120_000);

afterAll(async () => {
  await pool.end();
  await container.stop();
});

describe("PostgresMemoryStore", () => {
  it("write() then read() round-trips a value scoped to a tenant", async () => {
    await store.write("greeting", "hello", { tenantId: "tenant-a", sessionId: "s1" });
    await expect(store.read("greeting", { tenantId: "tenant-a", sessionId: "s1" })).resolves.toBe("hello");
  });

  it("read() ignores sessionId — the whole point is cross-session recall", async () => {
    await store.write("cross-session", "still here", { tenantId: "tenant-cross", sessionId: "session-1" });
    await expect(store.read("cross-session", { tenantId: "tenant-cross", sessionId: "session-2" })).resolves.toBe(
      "still here",
    );
  });

  it("read() returns undefined for a key never written", async () => {
    await expect(store.read("missing", { tenantId: "tenant-a", sessionId: "s1" })).resolves.toBeUndefined();
  });

  it("write() called twice with the same key upserts rather than duplicating", async () => {
    const ctx = { tenantId: "tenant-upsert", sessionId: "s1" };
    await store.write("preference", "first version", ctx);
    await store.write("preference", "second version", ctx);
    await expect(store.read("preference", ctx)).resolves.toBe("second version");

    const results = await store.search("version", ctx);
    expect(results).toHaveLength(1);
  });

  it("search() finds a memory by substring in title or content, scoped to tenant", async () => {
    await store.write("回复偏好", "喜欢简洁的回复", { tenantId: "tenant-search-a", sessionId: "s1" });
    await store.write("回复偏好", "喜欢简洁的回复", { tenantId: "tenant-search-b", sessionId: "s1" });

    const resultsA = await store.search("简洁", { tenantId: "tenant-search-a", sessionId: "s1" });
    expect(resultsA).toEqual([{ key: "回复偏好", value: "喜欢简洁的回复" }]);

    // Cross-tenant isolation: tenant-b's identical content must not leak into tenant-a's search,
    // and vice versa via a different tenantId in ctx.
    const resultsOtherTenant = await store.search("简洁", { tenantId: "tenant-search-nonexistent", sessionId: "s1" });
    expect(resultsOtherTenant).toEqual([]);
  });
});
