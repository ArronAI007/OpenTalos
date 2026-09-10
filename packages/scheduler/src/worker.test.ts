import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import { eq } from "drizzle-orm";
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

  scheduler = new Scheduler(testDb.pool, registry, checkpointStore);
}, 120_000);

afterAll(async () => {
  await stopTestDatabase(testDb);
});

beforeEach(async () => {
  executionCount = 0;
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
});
