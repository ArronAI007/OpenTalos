import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";
import {
  deleteMemories,
  deleteRawMemories,
  insertRawMemory,
  listMemoriesForTenant,
  listRawMemoriesForTenant,
  listTenantsWithUnconsolidatedRawMemories,
  upsertMemories,
} from "./bulk.js";

let container: StartedPostgreSqlContainer;
let pool: Pool;

beforeAll(async () => {
  container = await new PostgreSqlContainer("postgres:16-alpine").start();
  pool = new Pool({ connectionString: container.getConnectionUri() });
  await pool.query(`
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
  `);
}, 120_000);

afterAll(async () => {
  await pool.end();
  await container.stop();
});

describe("raw_memories bulk helpers", () => {
  it("insertRawMemory + listRawMemoriesForTenant round-trips, scoped to tenant", async () => {
    await insertRawMemory(pool, { tenantId: "tenant-raw-a", sessionId: "s1", runId: "run-1", content: "喜欢简洁回复" });
    await insertRawMemory(pool, { tenantId: "tenant-raw-b", sessionId: "s1", runId: "run-2", content: "住在北京" });

    const forA = await listRawMemoriesForTenant(pool, "tenant-raw-a");
    expect(forA.map((r) => r.content)).toEqual(["喜欢简洁回复"]);
  });

  it("listTenantsWithUnconsolidatedRawMemories only returns tenants that actually have pending rows", async () => {
    await insertRawMemory(pool, { tenantId: "tenant-pending", sessionId: "s1", runId: "run-3", content: "some fact" });
    const result = await listTenantsWithUnconsolidatedRawMemories(pool, ["tenant-pending", "tenant-with-no-raw-memories"]);
    expect(result).toEqual(["tenant-pending"]);
  });

  it("deleteRawMemories removes exactly the given rows, scoped to tenant", async () => {
    await insertRawMemory(pool, { tenantId: "tenant-delete-raw", sessionId: "s1", runId: "run-4", content: "to be deleted" });
    const before = await listRawMemoriesForTenant(pool, "tenant-delete-raw");
    await deleteRawMemories(pool, "tenant-delete-raw", before.map((r) => r.id));
    const after = await listRawMemoriesForTenant(pool, "tenant-delete-raw");
    expect(after).toEqual([]);
  });
});

describe("memories bulk helpers", () => {
  it("upsertMemories inserts new entries and applies updates in the same call", async () => {
    await upsertMemories(pool, "tenant-upsert-bulk", {
      newEntries: [{ type: "profile", title: "职业", content: "后端工程师" }],
      updates: [],
    });
    const [existing] = await listMemoriesForTenant(pool, "tenant-upsert-bulk");
    expect(existing).toMatchObject({ type: "profile", title: "职业", content: "后端工程师" });

    await upsertMemories(pool, "tenant-upsert-bulk", {
      newEntries: [],
      updates: [{ id: existing.id, content: "全栈工程师" }],
    });
    const [updated] = await listMemoriesForTenant(pool, "tenant-upsert-bulk");
    expect(updated.content).toBe("全栈工程师");
    expect(updated.updatedAt.getTime()).toBeGreaterThanOrEqual(existing.updatedAt.getTime());
  });

  it("deleteMemories removes exactly the given rows, scoped to tenant", async () => {
    await upsertMemories(pool, "tenant-delete-mem", { newEntries: [{ type: "context", title: "旅行计划", content: "9 月去上海" }], updates: [] });
    const [entry] = await listMemoriesForTenant(pool, "tenant-delete-mem");
    await deleteMemories(pool, "tenant-delete-mem", [entry.id]);
    expect(await listMemoriesForTenant(pool, "tenant-delete-mem")).toEqual([]);
  });

  it("listMemoriesForTenant never returns another tenant's rows", async () => {
    await upsertMemories(pool, "tenant-iso-a", { newEntries: [{ type: "profile", title: "a-fact", content: "a" }], updates: [] });
    await upsertMemories(pool, "tenant-iso-b", { newEntries: [{ type: "profile", title: "b-fact", content: "b" }], updates: [] });
    const forA = await listMemoriesForTenant(pool, "tenant-iso-a");
    expect(forA.map((m) => m.title)).toEqual(["a-fact"]);
  });
});
