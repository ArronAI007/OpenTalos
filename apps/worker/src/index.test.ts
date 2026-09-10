import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";
import { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import { PostgresEventBus, listEventsSince } from "@opentalos/postgres-tracing";
import { Scheduler, Worker } from "@opentalos/scheduler";
import { buildWorkerRegistry } from "./index.js";

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
    const registry = buildWorkerRegistry(eventBus);
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

    const events = await listEventsSince(pool, "worker-app-run-1", 0);
    // Mirrors the expected event-type sequence already established in
    // packages/chat-agent/src/index.test.ts for this same graph reaching its HITL pause.
    const eventTypes = events.map((event) => event.type);
    expect(eventTypes).toContain("node_enter");
    expect(eventTypes).toContain("tool_call_start");
    expect(eventTypes).toContain("tool_call_end");
    expect(eventTypes).toContain("hitl_interrupt");
  });
});
