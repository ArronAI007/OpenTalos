import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import { and, eq } from "drizzle-orm";
import type { EngineDeps, NodeFn } from "@opentalos/core-graph";
import { shallowMergeReducer, type GraphDefinition } from "@opentalos/core-graph";
import { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import { GraphRegistry } from "./graph-registry.js";
import { Scheduler } from "./enqueue.js";
import { Worker } from "./worker.js";
import { tasks } from "./schema.js";
import { startTestDatabase, stopTestDatabase, type TestDatabase } from "./test-db.js";

let testDb: TestDatabase;
let db: NodePgDatabase;
let checkpointStore: PostgresCheckpointStore;
let registry: GraphRegistry;
let scheduler: Scheduler;

interface CounterState {
  count: number;
}

function makeDeps(): Omit<EngineDeps, "checkpointStore"> {
  return {
    toolRegistry: { register() {}, get: () => undefined, list: () => [], execute: async (call) => ({ id: call.id, output: null }) },
    eventBus: { emit() {}, subscribe: () => () => {} },
  };
}

let executionCount = 0;
let flakyNodeHasFailedOnce = false;

interface ApprovalCounterState {
  count: number;
  approved: boolean;
}

beforeAll(async () => {
  testDb = await startTestDatabase();
  db = drizzle(testDb.pool);
  checkpointStore = new PostgresCheckpointStore(testDb.pool);
  registry = new GraphRegistry();

  const increment: NodeFn<CounterState> = async function* (state) {
    executionCount += 1;
    return { count: state.count + 1 };
  };
  const trivialGraph: GraphDefinition<CounterState> = {
    id: "trivial",
    entryNode: "increment",
    nodes: { increment },
    edges: [],
    reducer: shallowMergeReducer,
  };
  registry.register("trivial", { buildGraph: () => trivialGraph, buildDeps: makeDeps });

  const alwaysFails: NodeFn<CounterState> = async function* () {
    throw new Error("boom");
  };
  const failingGraph: GraphDefinition<CounterState> = {
    id: "always-fails",
    entryNode: "fail",
    nodes: { fail: alwaysFails },
    edges: [],
    reducer: shallowMergeReducer,
  };
  registry.register("always-fails", { buildGraph: () => failingGraph, buildDeps: makeDeps });

  const hangsForever: NodeFn<CounterState> = async function* () {
    await new Promise(() => {
      // never resolves — used only to exercise the worker's timeout path
    });
    return {};
  };
  const hangingGraph: GraphDefinition<CounterState> = {
    id: "hangs-forever",
    entryNode: "hang",
    nodes: { hang: hangsForever },
    edges: [],
    reducer: shallowMergeReducer,
  };
  registry.register("hangs-forever", { buildGraph: () => hangingGraph, buildDeps: makeDeps });

  // Two-node graph: "ask" pauses for HITL approval; "flaky" (the node reached only AFTER a
  // resume replays "ask") throws on its first invocation and succeeds on every subsequent one.
  // Used by the Fix 1 regression test to prove a resume-task retry after the checkpoint has
  // advanced past the pause dispatches on checkpoint.status, not blindly on task.kind.
  const askApproval: NodeFn<ApprovalCounterState> = async function* (state) {
    const resume = yield { type: "awaiting_approval", reason: "please approve" };
    return { approved: resume?.type === "approval" ? resume.approved : false };
  };
  const flakyNode: NodeFn<ApprovalCounterState> = async function* (state) {
    if (!flakyNodeHasFailedOnce) {
      flakyNodeHasFailedOnce = true;
      throw new Error("boom-once");
    }
    return { count: state.count + 1 };
  };
  const resumeThenFlakyGraph: GraphDefinition<ApprovalCounterState> = {
    id: "resume-then-flaky",
    entryNode: "ask",
    nodes: { ask: askApproval, flaky: flakyNode },
    edges: [{ from: "ask", to: "flaky" }],
    reducer: shallowMergeReducer,
  };
  registry.register("resume-then-flaky", { buildGraph: () => resumeThenFlakyGraph, buildDeps: makeDeps });

  scheduler = new Scheduler(testDb.pool, registry, checkpointStore);
}, 120_000);

afterAll(async () => {
  await stopTestDatabase(testDb);
});

beforeEach(async () => {
  executionCount = 0;
  flakyNodeHasFailedOnce = false;
  // Each test enqueues and polls against the same shared testDb/tasks table; without clearing
  // it between tests, a prior test's un-claimed "queued" rows (e.g. tenant-cap's leftover 3
  // from the tenant-concurrency test) would compete for a later test's concurrency budget and
  // make assertions about exact claimed/done counts order-dependent instead of hermetic.
  await testDb.pool.query("DELETE FROM tasks");
});

describe("Worker", () => {
  it("claims a queued task and marks it done after successful execution", async () => {
    await scheduler.enqueueStart("trivial", { count: 0 }, { tenantId: "tenant-basic", sessionId: "s1" }, "worker-run-1");
    const worker = new Worker(testDb.pool, registry, checkpointStore, { globalConcurrency: 10, tenantConcurrency: 10 });

    await worker.pollOnce();

    const rows = await db.select().from(tasks).where(eq(tasks.runId, "worker-run-1"));
    expect(rows[0].status).toBe("done");
    const checkpoint = await checkpointStore.load("worker-run-1");
    expect(checkpoint?.status).toBe("done");
    expect(checkpoint?.state).toEqual({ count: 1 });
  });

  it("does not let two concurrently-polling workers both execute the same task (SKIP LOCKED)", async () => {
    await scheduler.enqueueStart("trivial", { count: 0 }, { tenantId: "tenant-race", sessionId: "s1" }, "worker-run-race");
    const workerA = new Worker(testDb.pool, registry, checkpointStore, { globalConcurrency: 10, tenantConcurrency: 10 });
    const workerB = new Worker(testDb.pool, registry, checkpointStore, { globalConcurrency: 10, tenantConcurrency: 10 });

    await Promise.all([workerA.pollOnce(), workerB.pollOnce()]);

    expect(executionCount).toBe(1);
  });

  it("respects the tenant concurrency cap within one poll cycle", async () => {
    const tenant = { tenantId: "tenant-cap", sessionId: "s1" };
    for (let i = 0; i < 5; i++) {
      await scheduler.enqueueStart("trivial", { count: 0 }, tenant, `worker-cap-run-${i}`);
    }
    const worker = new Worker(testDb.pool, registry, checkpointStore, { globalConcurrency: 10, tenantConcurrency: 2 });

    await worker.pollOnce();

    const rows = await db.select().from(tasks).where(eq(tasks.tenantId, "tenant-cap"));
    const doneCount = rows.filter((r) => r.status === "done").length;
    const queuedCount = rows.filter((r) => r.status === "queued").length;
    expect(doneCount).toBe(2);
    expect(queuedCount).toBe(3);
  });

  it("respects the global concurrency cap across multiple tenants within one poll cycle", async () => {
    for (let i = 0; i < 3; i++) {
      await scheduler.enqueueStart("trivial", { count: 0 }, { tenantId: "tenant-global-a", sessionId: "s1" }, `global-a-${i}`);
    }
    for (let i = 0; i < 3; i++) {
      await scheduler.enqueueStart("trivial", { count: 0 }, { tenantId: "tenant-global-b", sessionId: "s1" }, `global-b-${i}`);
    }
    const worker = new Worker(testDb.pool, registry, checkpointStore, { globalConcurrency: 4, tenantConcurrency: 10 });

    await worker.pollOnce();

    const rowsA = await db.select().from(tasks).where(eq(tasks.tenantId, "tenant-global-a"));
    const rowsB = await db.select().from(tasks).where(eq(tasks.tenantId, "tenant-global-b"));
    const totalDone = [...rowsA, ...rowsB].filter((r) => r.status === "done").length;
    expect(totalDone).toBe(4);
  });

  it("retries a failing task with exponential backoff, then marks it failed after max attempts", async () => {
    await scheduler.enqueueStart(
      "always-fails",
      { count: 0 },
      { tenantId: "tenant-fail", sessionId: "s1" },
      "worker-fail-run",
      { maxAttempts: 2 },
    );
    const worker = new Worker(testDb.pool, registry, checkpointStore, { globalConcurrency: 10, tenantConcurrency: 10 });

    await worker.pollOnce();
    let rows = await db.select().from(tasks).where(eq(tasks.runId, "worker-fail-run"));
    expect(rows[0].status).toBe("queued");
    expect(rows[0].attempts).toBe(1);
    expect(rows[0].error).toContain("boom");
    expect(rows[0].availableAt.getTime()).toBeGreaterThan(Date.now());

    // Simulate the backoff period elapsing, instead of really waiting for it. Set it safely in
    // the past (rather than exactly "now") because the worker compares availableAt against the
    // database server's own clock (sql`now()`), not this Node process's clock — under load, a
    // containerized Postgres's clock and the test host's clock can differ by a few milliseconds,
    // so writing an exact-boundary "now" from here would make this comparison racy.
    await db.update(tasks).set({ availableAt: new Date(Date.now() - 5_000) }).where(eq(tasks.runId, "worker-fail-run"));
    await worker.pollOnce();
    rows = await db.select().from(tasks).where(eq(tasks.runId, "worker-fail-run"));
    expect(rows[0].status).toBe("failed");
    expect(rows[0].attempts).toBe(2);
  });

  it("treats a task exceeding timeoutMs as a failed attempt and schedules a retry", async () => {
    await scheduler.enqueueStart(
      "hangs-forever",
      { count: 0 },
      { tenantId: "tenant-timeout", sessionId: "s1" },
      "worker-timeout-run",
      { maxAttempts: 2, timeoutMs: 50 },
    );
    const worker = new Worker(testDb.pool, registry, checkpointStore, { globalConcurrency: 10, tenantConcurrency: 10 });

    await worker.pollOnce();

    const rows = await db.select().from(tasks).where(eq(tasks.runId, "worker-timeout-run"));
    expect(rows[0].status).toBe("queued");
    expect(rows[0].error).toContain("timed out");
  });

  it("retries a resume task whose retry-worthy failure happens AFTER the paused node has already advanced (Fix 1)", async () => {
    await scheduler.enqueueStart(
      "resume-then-flaky",
      { count: 0, approved: false },
      { tenantId: "tenant-fix1", sessionId: "s1" },
      "fix1-run",
      { maxAttempts: 3 },
    );
    const worker = new Worker(testDb.pool, registry, checkpointStore, { globalConcurrency: 10, tenantConcurrency: 10 });

    // Reaches the HITL pause at "ask".
    await worker.pollOnce();
    let checkpoint = await checkpointStore.load("fix1-run");
    expect(checkpoint?.status).toBe("paused");

    // Resume: replays "ask" (auto-answering with the approval), advances to "flaky", which
    // throws on this first invocation. The checkpoint has already advanced past the pause
    // (status "running", nodeCursor "flaky") by the time the error propagates.
    await scheduler.enqueueResume(
      "fix1-run",
      { type: "approval", approved: true },
      { tenantId: "tenant-fix1", sessionId: "s1" },
    );
    await worker.pollOnce();

    // enqueueResume inserts a NEW task row (kind "resume") rather than updating the original
    // "start" row, so filter to the resume row specifically.
    let rows = await db.select().from(tasks).where(and(eq(tasks.runId, "fix1-run"), eq(tasks.kind, "resume")));
    expect(rows[0].status).toBe("queued");
    expect(rows[0].error).toContain("boom-once");
    checkpoint = await checkpointStore.load("fix1-run");
    expect(checkpoint?.status).toBe("running");

    // Simulate the backoff period elapsing (same pattern as the retry-backoff test above).
    await db
      .update(tasks)
      .set({ availableAt: new Date(Date.now() - 5_000) })
      .where(and(eq(tasks.runId, "fix1-run"), eq(tasks.kind, "resume")));
    await worker.pollOnce();

    // The retry must dispatch on the checkpoint's actual ("running") status rather than blindly
    // re-calling resumeFromCheckpoint (which would throw "not in a resumable paused state" and
    // destroy the real "boom-once" error) — proving the fix. The task completes successfully,
    // and the stale "boom-once" error from the earlier failed attempt is cleared (Fix 4) — a
    // task that ends "done" must not still show a previous attempt's error message.
    rows = await db.select().from(tasks).where(and(eq(tasks.runId, "fix1-run"), eq(tasks.kind, "resume")));
    expect(rows[0].status).toBe("done");
    expect(rows[0].error).toBeNull();
    checkpoint = await checkpointStore.load("fix1-run");
    expect(checkpoint?.status).toBe("done");
    expect(checkpoint?.state).toEqual({ count: 1, approved: true });
  });

  it("applies per-tenant concurrency caps resolved via resolveTenantConcurrency, differentiated per tenant", async () => {
    const tenantA = { tenantId: "tenant-quota-a", sessionId: "s1" };
    const tenantB = { tenantId: "tenant-quota-b", sessionId: "s1" };
    for (let i = 0; i < 5; i++) {
      await scheduler.enqueueStart("trivial", { count: 0 }, tenantA, `quota-a-run-${i}`);
    }
    for (let i = 0; i < 5; i++) {
      await scheduler.enqueueStart("trivial", { count: 0 }, tenantB, `quota-b-run-${i}`);
    }
    const caps: Record<string, number> = { "tenant-quota-a": 1, "tenant-quota-b": 4 };
    const worker = new Worker(testDb.pool, registry, checkpointStore, {
      globalConcurrency: 10,
      tenantConcurrency: 10, // 静态默认值，两个租户都设置了 resolver 覆盖，不应该被用到
      resolveTenantConcurrency: async (tenantId) => caps[tenantId] ?? 10,
    });

    await worker.pollOnce();

    const rowsA = await db.select().from(tasks).where(eq(tasks.tenantId, "tenant-quota-a"));
    const rowsB = await db.select().from(tasks).where(eq(tasks.tenantId, "tenant-quota-b"));
    expect(rowsA.filter((r) => r.status === "done").length).toBe(1);
    expect(rowsB.filter((r) => r.status === "done").length).toBe(4);
  });

  it("falls back to the static tenantConcurrency default when resolveTenantConcurrency throws", async () => {
    const tenant = { tenantId: "tenant-quota-error", sessionId: "s1" };
    for (let i = 0; i < 5; i++) {
      await scheduler.enqueueStart("trivial", { count: 0 }, tenant, `quota-error-run-${i}`);
    }
    const worker = new Worker(testDb.pool, registry, checkpointStore, {
      globalConcurrency: 10,
      tenantConcurrency: 3,
      resolveTenantConcurrency: async () => {
        throw new Error("quota lookup failed");
      },
    });

    await worker.pollOnce();

    const rows = await db.select().from(tasks).where(eq(tasks.tenantId, "tenant-quota-error"));
    expect(rows.filter((r) => r.status === "done").length).toBe(3);
  });
});
