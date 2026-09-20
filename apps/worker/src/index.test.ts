import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";
import type { ModelProvider, ModelResponseChunk } from "@opentalos/core-types";
import { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import { PostgresEventBus, listEventsSince } from "@opentalos/postgres-tracing";
import { TenantStore } from "@opentalos/postgres-tenancy";
import { Scheduler, Worker } from "@opentalos/scheduler";
import { createModelProviderFromEnv } from "@opentalos/model-providers";
import { insertRawMemory, listMemoriesForTenant, listRawMemoriesForTenant } from "@opentalos/postgres-memory";
import { buildWorkerRegistry, runMemoryConsolidationSweep } from "./index.js";

let container: StartedPostgreSqlContainer;
let pool: Pool;

beforeAll(() => {
  process.env.MODEL_PROVIDER = "mock";
});

beforeAll(async () => {
  container = await new PostgreSqlContainer("postgres:16-alpine").start();
  pool = new Pool({ connectionString: container.getConnectionUri() });
  await pool.query(`
    CREATE TABLE checkpoints (
      run_id TEXT PRIMARY KEY,
      graph_id TEXT NOT NULL,
      tenant_id TEXT NOT NULL,
      session_id TEXT NOT NULL,
      node_cursor JSONB NOT NULL,
      state JSONB NOT NULL,
      pending_yields JSONB NOT NULL,
      status TEXT NOT NULL,
      cancel_requested BOOLEAN NOT NULL DEFAULT false,
      steer_message TEXT,
      error TEXT,
      created_at TIMESTAMPTZ NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE tasks (
      id SERIAL PRIMARY KEY,
      run_id TEXT NOT NULL,
      graph_id TEXT NOT NULL,
      tenant_id TEXT NOT NULL,
      session_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      resume_value JSONB,
      status TEXT NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0,
      max_attempts INTEGER NOT NULL DEFAULT 3,
      timeout_ms INTEGER NOT NULL DEFAULT 30000,
      priority INTEGER NOT NULL DEFAULT 0,
      available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      locked_at TIMESTAMPTZ,
      error TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE trace_events (
      id SERIAL PRIMARY KEY,
      run_id TEXT NOT NULL,
      tenant_id TEXT NOT NULL,
      session_id TEXT NOT NULL,
      type TEXT NOT NULL,
      payload JSONB,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE tenants (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      status TEXT NOT NULL,
      max_concurrency INTEGER,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
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

describe("apps/worker registry wiring", () => {
  it("registers chat-agent and can run it to the HITL pause via a real Worker", async () => {
    const checkpointStore = new PostgresCheckpointStore(pool);
    const eventBus = new PostgresEventBus(pool);
    const registry = buildWorkerRegistry(eventBus, createModelProviderFromEnv());
    const scheduler = new Scheduler(pool, registry, checkpointStore);
    const worker = new Worker(pool, registry, checkpointStore, { globalConcurrency: 5, tenantConcurrency: 5 });

    await scheduler.enqueueStart(
      "chat-agent",
      { message: "test" },
      { tenantId: "tenant-a", sessionId: "s1" },
      "worker-app-run-1",
    );
    await worker.pollOnce();

    // PostgresEventBus.emit() is fire-and-forget (chained onto an internal write-chain promise,
    // not awaited by callers), so some events can still be in-flight in the write queue right
    // after pollOnce() resolves. Without this flush(), the assertions below could run against a
    // partially-written event set -- confirmed by reproduction: two events were observed still
    // unwritten immediately after pollOnce() returned, even after further awaited round trips.
    await eventBus.flush();

    const checkpoint = await checkpointStore.load("worker-app-run-1");
    expect(checkpoint?.status).toBe("paused");

    const events = await listEventsSince(pool, "worker-app-run-1", 0, "tenant-a");
    // Mirrors the expected event-type sequence already established in
    // packages/chat-agent/src/index.test.ts for this same graph reaching its HITL pause.
    const eventTypes = events.map((event) => event.type);
    expect(eventTypes).toContain("node_enter");
    expect(eventTypes).toContain("tool_call_start");
    expect(eventTypes).toContain("tool_call_end");
    expect(eventTypes).toContain("hitl_interrupt");
  });
});

function fakeConsolidationProvider(responseText: string): ModelProvider {
  return {
    async *complete(): AsyncIterable<ModelResponseChunk> {
      yield { type: "text_delta", textDelta: responseText };
      yield { type: "message_stop" };
    },
  };
}

describe("runMemoryConsolidationSweep", () => {
  it("consolidates a pending raw memory for a real, seeded tenant", async () => {
    const tenantStore = new TenantStore(pool);
    const tenant = await tenantStore.createTenant("sweep-tenant");
    await insertRawMemory(pool, { tenantId: tenant.id, sessionId: "s1", runId: "run-1", content: "喜欢简洁回复" });

    const provider = fakeConsolidationProvider(
      '{"add": [{"type": "preference", "title": "回复偏好", "content": "喜欢简洁回复"}], "update": [], "delete": []}',
    );
    await runMemoryConsolidationSweep(pool, provider, tenantStore);

    const memories = await listMemoriesForTenant(pool, tenant.id);
    expect(memories).toMatchObject([{ type: "preference", title: "回复偏好", content: "喜欢简洁回复" }]);
    expect(await listRawMemoriesForTenant(pool, tenant.id)).toEqual([]);
  });

  it("does not let one tenant's consolidation failure block another tenant's sweep", async () => {
    const tenantStore = new TenantStore(pool);
    const failingTenant = await tenantStore.createTenant("sweep-tenant-failing");
    const okTenant = await tenantStore.createTenant("sweep-tenant-ok");
    await insertRawMemory(pool, { tenantId: failingTenant.id, sessionId: "s1", runId: "run-2", content: "will fail" });
    await insertRawMemory(pool, { tenantId: okTenant.id, sessionId: "s1", runId: "run-3", content: "住在北京" });

    const provider: ModelProvider = {
      complete: (request) => {
        // No tenantId on ModelRequest, so distinguish which tenant's consolidation call this is
        // by the raw observation text baked into the user prompt (set up above, per tenant).
        const userPrompt = request.messages.find((m) => m.role === "user")?.content ?? "";
        if (userPrompt.includes("will fail")) throw new Error("simulated provider failure");
        return fakeConsolidationProvider(
          '{"add": [{"type": "profile", "title": "居住地", "content": "住在北京"}], "update": [], "delete": []}',
        ).complete(request);
      },
    };
    await runMemoryConsolidationSweep(pool, provider, tenantStore);

    expect(await listMemoriesForTenant(pool, okTenant.id)).toMatchObject([{ type: "profile", title: "居住地", content: "住在北京" }]);
  });
});
