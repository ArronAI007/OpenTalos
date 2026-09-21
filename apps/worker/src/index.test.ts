import { createServer, type Server } from "node:http";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";
import { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import { PostgresEventBus, listEventsSince } from "@opentalos/postgres-tracing";
import { TenantStore } from "@opentalos/postgres-tenancy";
import { Scheduler, Worker } from "@opentalos/scheduler";
import { createModelProviderFromEnv } from "@opentalos/model-providers";
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
    const registry = buildWorkerRegistry(eventBus, createModelProviderFromEnv(), pool);
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

describe("runMemoryConsolidationSweep", () => {
  afterEach(() => {
    delete process.env.MEMORY_SERVICE_URL;
  });

  it("only calls /memory/consolidate for tenants the fake memory-service reports as pending", async () => {
    const tenantStore = new TenantStore(pool);
    const tenantWithWork = await tenantStore.createTenant("sweep-tenant-pending");
    await tenantStore.createTenant("sweep-tenant-idle");

    const consolidateCalls: string[] = [];
    const server = createServer((req, res) => {
      let body = "";
      req.on("data", (chunk) => (body += chunk));
      req.on("end", () => {
        if (req.url?.startsWith("/memory/tenants-with-pending")) {
          res.writeHead(200, { "content-type": "application/json" });
          res.end(JSON.stringify({ tenant_ids: [tenantWithWork.id] }));
          return;
        }
        if (req.url === "/memory/consolidate" && req.method === "POST") {
          consolidateCalls.push((JSON.parse(body) as { tenant_id: string }).tenant_id);
          res.writeHead(204);
          res.end();
          return;
        }
        res.writeHead(404);
        res.end();
      });
    });
    await new Promise<void>((resolvePromise) => server.listen(0, resolvePromise));
    const address = server.address();
    if (address === null || typeof address === "string") throw new Error("expected a bound TCP port");
    process.env.MEMORY_SERVICE_URL = `http://localhost:${address.port}`;

    try {
      await runMemoryConsolidationSweep(pool, tenantStore);
    } finally {
      await new Promise<void>((resolvePromise) => server.close(() => resolvePromise()));
    }

    expect(consolidateCalls).toEqual([tenantWithWork.id]);
  });

  it("does not let one tenant's consolidation failure block another tenant's sweep", async () => {
    const tenantStore = new TenantStore(pool);
    const failingTenant = await tenantStore.createTenant("sweep-tenant-failing");
    const okTenant = await tenantStore.createTenant("sweep-tenant-ok");

    const consolidateCalls: string[] = [];
    const server = createServer((req, res) => {
      let body = "";
      req.on("data", (chunk) => (body += chunk));
      req.on("end", () => {
        if (req.url?.startsWith("/memory/tenants-with-pending")) {
          res.writeHead(200, { "content-type": "application/json" });
          res.end(JSON.stringify({ tenant_ids: [failingTenant.id, okTenant.id] }));
          return;
        }
        if (req.url === "/memory/consolidate" && req.method === "POST") {
          const tenantId = (JSON.parse(body) as { tenant_id: string }).tenant_id;
          consolidateCalls.push(tenantId);
          res.writeHead(tenantId === failingTenant.id ? 500 : 204);
          res.end();
          return;
        }
        res.writeHead(404);
        res.end();
      });
    });
    await new Promise<void>((resolvePromise) => server.listen(0, resolvePromise));
    const address = server.address();
    if (address === null || typeof address === "string") throw new Error("expected a bound TCP port");
    process.env.MEMORY_SERVICE_URL = `http://localhost:${address.port}`;

    try {
      await expect(runMemoryConsolidationSweep(pool, tenantStore)).resolves.toBeUndefined();
    } finally {
      await new Promise<void>((resolvePromise) => server.close(() => resolvePromise()));
    }

    expect(consolidateCalls).toContain(failingTenant.id);
    expect(consolidateCalls).toContain(okTenant.id);
  });
});
