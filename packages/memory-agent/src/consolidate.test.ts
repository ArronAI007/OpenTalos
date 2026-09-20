import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";
import type { ModelProvider, ModelResponseChunk } from "@opentalos/core-types";
import { insertRawMemory, listMemoriesForTenant, listRawMemoriesForTenant, upsertMemories } from "@opentalos/postgres-memory";
import { consolidateMemoriesForTenant } from "./consolidate.js";

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

function fakeProvider(responseText: string): ModelProvider {
  return {
    async *complete(): AsyncIterable<ModelResponseChunk> {
      yield { type: "text_delta", textDelta: responseText };
      yield { type: "message_stop" };
    },
  };
}

describe("consolidateMemoriesForTenant", () => {
  it("does nothing when there are no unconsolidated raw memories", async () => {
    const provider = fakeProvider('{"add": [], "update": [], "delete": []}');
    await consolidateMemoriesForTenant(pool, provider, "tenant-empty");
    expect(await listMemoriesForTenant(pool, "tenant-empty")).toEqual([]);
  });

  it("adds a new memory from a raw observation and clears the processed raw memory", async () => {
    await insertRawMemory(pool, { tenantId: "tenant-add", sessionId: "s1", runId: "run-1", content: "喜欢简洁回复" });
    const provider = fakeProvider('{"add": [{"type": "preference", "title": "回复偏好", "content": "喜欢简洁回复"}], "update": [], "delete": []}');
    await consolidateMemoriesForTenant(pool, provider, "tenant-add");

    const memories = await listMemoriesForTenant(pool, "tenant-add");
    expect(memories).toMatchObject([{ type: "preference", title: "回复偏好", content: "喜欢简洁回复" }]);
    expect(await listRawMemoriesForTenant(pool, "tenant-add")).toEqual([]);
  });

  it("updates an existing memory when the model says a raw observation refines it", async () => {
    await upsertMemories(pool, "tenant-update", { newEntries: [{ type: "context", title: "旅行计划", content: "9 月去上海" }], updates: [] });
    const [existing] = await listMemoriesForTenant(pool, "tenant-update");
    await insertRawMemory(pool, { tenantId: "tenant-update", sessionId: "s1", runId: "run-2", content: "旅行改成 10 月了" });

    const provider = fakeProvider(`{"add": [], "update": [{"id": "${existing.id}", "content": "10 月去上海"}], "delete": []}`);
    await consolidateMemoriesForTenant(pool, provider, "tenant-update");

    const [updated] = await listMemoriesForTenant(pool, "tenant-update");
    expect(updated.content).toBe("10 月去上海");
  });

  it("deletes a memory the model judges is no longer true", async () => {
    await upsertMemories(pool, "tenant-delete", { newEntries: [{ type: "context", title: "旧计划", content: "已经取消的计划" }], updates: [] });
    const [existing] = await listMemoriesForTenant(pool, "tenant-delete");
    await insertRawMemory(pool, { tenantId: "tenant-delete", sessionId: "s1", runId: "run-3", content: "计划取消了" });

    const provider = fakeProvider(`{"add": [], "update": [], "delete": ["${existing.id}"]}`);
    await consolidateMemoriesForTenant(pool, provider, "tenant-delete");

    expect(await listMemoriesForTenant(pool, "tenant-delete")).toEqual([]);
  });

  it("clears processed raw memories even when the model outputs no operations at all", async () => {
    await insertRawMemory(pool, { tenantId: "tenant-ignore", sessionId: "s1", runId: "run-4", content: "重复的信息" });
    const provider = fakeProvider('{"add": [], "update": [], "delete": []}');
    await consolidateMemoriesForTenant(pool, provider, "tenant-ignore");
    expect(await listRawMemoriesForTenant(pool, "tenant-ignore")).toEqual([]);
  });

  it("treats malformed model output as a no-op for add/update/delete, but still clears the processed raw memories", async () => {
    await insertRawMemory(pool, { tenantId: "tenant-malformed", sessionId: "s1", runId: "run-5", content: "some fact" });
    const provider = fakeProvider("not valid json");
    await consolidateMemoriesForTenant(pool, provider, "tenant-malformed");
    expect(await listMemoriesForTenant(pool, "tenant-malformed")).toEqual([]);
    expect(await listRawMemoriesForTenant(pool, "tenant-malformed")).toEqual([]);
  });

  it("drops an add item with a hallucinated type and creates nothing", async () => {
    await insertRawMemory(pool, { tenantId: "tenant-bad-type", sessionId: "s1", runId: "run-6", content: "some fact" });
    const provider = fakeProvider('{"add": [{"type": "bogus-type", "title": "x", "content": "y"}], "update": [], "delete": []}');
    await consolidateMemoriesForTenant(pool, provider, "tenant-bad-type");
    expect(await listMemoriesForTenant(pool, "tenant-bad-type")).toEqual([]);
    expect(await listRawMemoriesForTenant(pool, "tenant-bad-type")).toEqual([]);
  });

  it("applies only the valid item from a mixed batch of one valid and one invalid add item", async () => {
    await insertRawMemory(pool, { tenantId: "tenant-mixed", sessionId: "s1", runId: "run-7", content: "喜欢简洁回复" });
    const provider = fakeProvider(
      '{"add": [{"type": "preference", "title": "回复偏好", "content": "喜欢简洁回复"}, {"type": "profile", "title": "缺 content"}], "update": [], "delete": []}',
    );
    await consolidateMemoriesForTenant(pool, provider, "tenant-mixed");
    const memories = await listMemoriesForTenant(pool, "tenant-mixed");
    expect(memories).toMatchObject([{ type: "preference", title: "回复偏好", content: "喜欢简洁回复" }]);
  });

  it("propagates a write failure mid-consolidation and leaves the raw memory untouched (deleteRawMemories never runs)", async () => {
    await upsertMemories(pool, "tenant-conflict", { newEntries: [{ type: "profile", title: "重复标题", content: "已有内容" }], updates: [] });
    await insertRawMemory(pool, { tenantId: "tenant-conflict", sessionId: "s1", runId: "run-8", content: "新的观察" });

    // 让模型返回一个 add，其 title 跟已有记忆的 title 撞车——upsertMemories 内部的
    // (tenantId, title) 唯一约束会真实地在 Postgres 里报错，不是 mock 出来的失败。
    const provider = fakeProvider('{"add": [{"type": "profile", "title": "重复标题", "content": "冲突的新内容"}], "update": [], "delete": []}');

    await expect(consolidateMemoriesForTenant(pool, provider, "tenant-conflict")).rejects.toThrow();

    const rawAfter = await listRawMemoriesForTenant(pool, "tenant-conflict");
    expect(rawAfter.map((r) => r.content)).toEqual(["新的观察"]);
  });
});
