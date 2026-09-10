import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { randomUUID } from "node:crypto";
import { Pool } from "pg";
import type { FastifyInstance } from "fastify";
import { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import { PostgresEventBus, listEventsSince } from "@opentalos/postgres-tracing";
import { GraphRegistry, Scheduler } from "@opentalos/scheduler";
import { buildChatDemoAgentGraph, createChatDemoAgentToolRegistry } from "@opentalos/example-chat-demo-agent";
import { buildServer } from "../server.js";
import { closeAllSseConnections, getActiveSseConnectionCountForTests } from "./runs.js";
import { DEV_TENANT_ID } from "../dev-tenant.js";

let container: StartedPostgreSqlContainer;
let pool: Pool;
let app: FastifyInstance;
let checkpointStore: PostgresCheckpointStore;

beforeAll(async () => {
  container = await new PostgreSqlContainer("postgres:16-alpine").start();
  pool = new Pool({ connectionString: container.getConnectionUri() });
  await pool.query(`
    CREATE TABLE checkpoints (
      run_id TEXT PRIMARY KEY, graph_id TEXT NOT NULL, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
      node_cursor JSONB NOT NULL, state JSONB NOT NULL, pending_yields JSONB NOT NULL, status TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE tasks (
      id SERIAL PRIMARY KEY, run_id TEXT NOT NULL, graph_id TEXT NOT NULL, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
      kind TEXT NOT NULL, resume_value JSONB, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
      max_attempts INTEGER NOT NULL DEFAULT 3, timeout_ms INTEGER NOT NULL DEFAULT 30000, priority INTEGER NOT NULL DEFAULT 0,
      available_at TIMESTAMPTZ NOT NULL DEFAULT now(), locked_at TIMESTAMPTZ, error TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE trace_events (
      id SERIAL PRIMARY KEY, run_id TEXT NOT NULL, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
      type TEXT NOT NULL, payload JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
  `);

  checkpointStore = new PostgresCheckpointStore(pool);
  const eventBus = new PostgresEventBus(pool);
  const registry = new GraphRegistry();
  registry.register("chat-demo-agent", {
    buildGraph: buildChatDemoAgentGraph,
    buildDeps: () => ({ toolRegistry: createChatDemoAgentToolRegistry(), eventBus }),
  });
  const scheduler = new Scheduler(pool, registry, checkpointStore);
  app = buildServer({
    pool,
    checkpointStore,
    scheduler,
    listEventsSince: (runId, afterId) => listEventsSince(pool, runId, afterId),
  });
}, 120_000);

afterAll(async () => {
  await app.close();
  await pool.end();
  await container.stop();
});

describe("POST /runs", () => {
  it("starts a run and returns a runId", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/runs?sessionId=s1",
      payload: { message: "hello" },
    });
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body.runId).toBeTypeOf("string");

    const checkpoint = await checkpointStore.load(body.runId);
    expect(checkpoint?.tenantId).toBe(DEV_TENANT_ID);
    expect(checkpoint?.sessionId).toBe("s1");
  });

  it("returns 400 when sessionId query param is missing", async () => {
    const res = await app.inject({ method: "POST", url: "/runs", payload: { message: "hello" } });
    expect(res.statusCode).toBe(400);
  });

  it("returns 400 when message body field is missing", async () => {
    const res = await app.inject({ method: "POST", url: "/runs?sessionId=s1", payload: {} });
    expect(res.statusCode).toBe(400);
  });
});

describe("GET /runs/:runId", () => {
  it("returns the current checkpoint status and state", async () => {
    const start = await app.inject({ method: "POST", url: "/runs?sessionId=s2", payload: { message: "hi" } });
    const { runId } = start.json();

    const res = await app.inject({ method: "GET", url: `/runs/${runId}?sessionId=s2` });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.runId).toBe(runId);
    expect(["running", "paused", "done"]).toContain(body.status);
  });

  it("returns 404 for an unknown runId", async () => {
    const res = await app.inject({ method: "GET", url: "/runs/does-not-exist?sessionId=s1" });
    expect(res.statusCode).toBe(404);
  });

  it("returns 403 when sessionId does not match the run's session", async () => {
    const start = await app.inject({ method: "POST", url: "/runs?sessionId=s3", payload: { message: "hi" } });
    const { runId } = start.json();

    const res = await app.inject({ method: "GET", url: `/runs/${runId}?sessionId=someone-else` });
    expect(res.statusCode).toBe(403);
  });
});

describe("POST /runs/:runId/resume", () => {
  it("returns 409 when the run is not yet paused", async () => {
    const start = await app.inject({ method: "POST", url: "/runs?sessionId=s4", payload: { message: "hi" } });
    const { runId } = start.json();

    const res = await app.inject({
      method: "POST",
      url: `/runs/${runId}/resume?sessionId=s4`,
      payload: { approved: true },
    });
    expect(res.statusCode).toBe(409);
  });

  it("returns 404 for an unknown runId", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/runs/does-not-exist/resume?sessionId=s1",
      payload: { approved: true },
    });
    expect(res.statusCode).toBe(404);
  });

  it("returns 400 when approved body field is missing", async () => {
    const start = await app.inject({ method: "POST", url: "/runs?sessionId=s5", payload: { message: "hi" } });
    const { runId } = start.json();

    const res = await app.inject({ method: "POST", url: `/runs/${runId}/resume?sessionId=s5`, payload: {} });
    expect(res.statusCode).toBe(400);
  });

  it("returns 403 when sessionId does not match the run's session", async () => {
    // Scheduler.enqueueResume checks checkpoint.status !== "paused" *before* it checks
    // tenant/session match (see packages/scheduler/src/enqueue.ts) — a freshly-started run is
    // still "running" (nothing drains the task queue in this test suite), so posting to
    // /resume on it always 409s before the tenant check is ever reached. To actually exercise
    // the tenant-mismatch 403 path through the HTTP layer, the checkpoint has to already be
    // "paused" when /resume is called, so it's written directly here rather than produced by a
    // real graph run (no Worker is wired into these tests).
    const runId = randomUUID();
    await checkpointStore.save({
      runId,
      graphId: "chat-demo-agent",
      tenantId: DEV_TENANT_ID,
      sessionId: "s7",
      nodeCursor: "confirm",
      state: { message: "hi" },
      pendingYields: [{ type: "awaiting_approval", reason: "test" }],
      status: "paused",
      createdAt: new Date().toISOString(),
    });

    const res = await app.inject({
      method: "POST",
      url: `/runs/${runId}/resume?sessionId=someone-else`,
      payload: { approved: true },
    });
    expect(res.statusCode).toBe(403);
  });
});

describe("GET /runs/:runId/events", () => {
  it("returns 404 for an unknown runId before upgrading to SSE", async () => {
    const res = await app.inject({ method: "GET", url: "/runs/does-not-exist/events?sessionId=s1" });
    expect(res.statusCode).toBe(404);
  });

  it("returns 403 when sessionId does not match", async () => {
    const start = await app.inject({ method: "POST", url: "/runs?sessionId=s6", payload: { message: "hi" } });
    const { runId } = start.json();
    const res = await app.inject({ method: "GET", url: `/runs/${runId}/events?sessionId=wrong` });
    expect(res.statusCode).toBe(403);
  });
});

describe("GET /runs/:runId/events (real SSE connection lifecycle)", () => {
  // `.inject()` never opens a real socket, so `reply.hijack()` can't be exercised faithfully
  // through it — a hijacked SSE response only behaves like a real long-lived connection over an
  // actual TCP listener. This suite starts one just for these tests and reuses the same `app`
  // instance (the outer `afterAll` above already closes it, which also tears down this listener).
  let baseUrl: string;

  beforeAll(async () => {
    await app.listen({ port: 0, host: "127.0.0.1" });
    const address = app.server.address();
    if (address === null || typeof address === "string") {
      throw new Error("expected app.listen() to bind a real TCP address");
    }
    baseUrl = `http://127.0.0.1:${address.port}`;
  });

  it("registers the connection in the tracking set and closeAllSseConnections() ends it", async () => {
    // Nothing drains the task queue in this test suite (no Worker is wired in — see the
    // tenant-mismatch test above), so this run's status stays "running" forever: the SSE stream
    // will not reach its own "done" branch on its own, which is exactly what's needed to prove
    // closeAllSseConnections() is what ended it, not the run finishing naturally.
    const start = await app.inject({ method: "POST", url: "/runs?sessionId=sse1", payload: { message: "hi" } });
    const { runId } = start.json();

    const countBefore = getActiveSseConnectionCountForTests();

    const response = await fetch(`${baseUrl}/runs/${runId}/events?sessionId=sse1`);
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("text/event-stream");
    expect(response.body).not.toBeNull();

    // Proves the handler registered `reply.raw` in the tracking set right after hijacking.
    expect(getActiveSseConnectionCountForTests()).toBe(countBefore + 1);

    const reader = response.body!.getReader();
    closeAllSseConnections();

    // Proves closeAllSseConnections() actually cleared the set (not just called .end() on stale
    // entries left over from another test).
    expect(getActiveSseConnectionCountForTests()).toBe(0);

    const streamClosed = await Promise.race([
      (async () => {
        // Drain whatever was already buffered (e.g. an initial status_changed frame written by
        // the first poll() tick, which can race ahead of closeAllSseConnections()) until the
        // response body itself ends.
        for (;;) {
          const result = await reader.read();
          if (result.done) return true;
        }
      })(),
      new Promise<boolean>((resolve) => setTimeout(() => resolve(false), 3000)),
    ]);

    // Proves closeAllSseConnections() genuinely terminated the underlying connection, not just
    // the bookkeeping Set.
    expect(streamClosed).toBe(true);
  }, 10_000);

  it("unregisters the connection when the client disconnects", async () => {
    const start = await app.inject({ method: "POST", url: "/runs?sessionId=sse2", payload: { message: "hi" } });
    const { runId } = start.json();

    const countBefore = getActiveSseConnectionCountForTests();

    const controller = new AbortController();
    const response = await fetch(`${baseUrl}/runs/${runId}/events?sessionId=sse2`, { signal: controller.signal });
    expect(response.status).toBe(200);
    expect(getActiveSseConnectionCountForTests()).toBe(countBefore + 1);

    // Exercises the `request.raw.on("close", ...)` handler from the client side.
    controller.abort();

    const deadline = Date.now() + 3000;
    while (getActiveSseConnectionCountForTests() > countBefore && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 25));
    }

    expect(getActiveSseConnectionCountForTests()).toBe(countBefore);
  }, 10_000);
});
