import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";
import type { ModelProvider, ModelResponseChunk } from "@opentalos/core-types";
import { listRawMemoriesForTenant } from "@opentalos/postgres-memory";
import { extractMemory } from "./extraction.js";

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
  `);
}, 120_000);

afterAll(async () => {
  await pool.end();
  await container.stop();
});

/** 最小的、可控制返回内容的假 ModelProvider —— packages/model-providers 的 createMockProvider()
 * 是专门为 chat-agent 的对话/工具调用场景写的，不能定制返回任意 JSON 文本，所以这里直接手写一个
 * 满足 ModelProvider 接口的假实现，跟 packages/postgres-checkpoint 等包里"真实 Postgres，不 mock
 * 数据库"的既有约定并不冲突——这里 mock 的是模型调用，不是数据库。 */
function fakeProvider(responseText: string): ModelProvider {
  return {
    async *complete(): AsyncIterable<ModelResponseChunk> {
      yield { type: "text_delta", textDelta: responseText };
      yield { type: "message_stop" };
    },
  };
}

describe("extractMemory", () => {
  it("writes nothing when the model judges there's no durable information (no-op gate)", async () => {
    const provider = fakeProvider('{"shouldSave": false}');
    await extractMemory(pool, provider, {
      tenantId: "tenant-noop",
      sessionId: "s1",
      runId: "run-1",
      userMessage: "今天几号？",
      assistantReply: "今天是 2026 年 9 月 20 日。",
    });
    expect(await listRawMemoriesForTenant(pool, "tenant-noop")).toEqual([]);
  });

  it("writes a raw memory when the model finds durable information", async () => {
    const provider = fakeProvider('{"shouldSave": true, "content": "用户希望回复简洁，不要用列表"}');
    await extractMemory(pool, provider, {
      tenantId: "tenant-save",
      sessionId: "s1",
      runId: "run-2",
      userMessage: "以后回复别用列表，太啰嗦了",
      assistantReply: "好的，以后我会用简洁的段落回复。",
    });
    const rows = await listRawMemoriesForTenant(pool, "tenant-save");
    expect(rows.map((r) => r.content)).toEqual(["用户希望回复简洁，不要用列表"]);
  });

  it("treats malformed model output as a no-op rather than throwing", async () => {
    const provider = fakeProvider("not valid json at all");
    await expect(
      extractMemory(pool, provider, {
        tenantId: "tenant-malformed",
        sessionId: "s1",
        runId: "run-3",
        userMessage: "hi",
        assistantReply: "hello",
      }),
    ).resolves.toBeUndefined();
    expect(await listRawMemoriesForTenant(pool, "tenant-malformed")).toEqual([]);
  });
});
