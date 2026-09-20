import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
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

  // Used only by the "orphaned save() after a timeout" regression test below: an abort-aware node
  // that, like chat-agent's real `respond` node, does NOT throw when its signal is aborted — it
  // just keeps running and finishes normally. Its delay is deliberately longer than the task's
  // timeoutMs so runWithTimeout()'s Promise.race is won by the timeout, orphaning this node's own
  // promise (and, eventually, the checkpointStore.save() GraphEngine's completeNode() makes once
  // it resolves) in the background.
  const finishesAfterTimeout: NodeFn<CounterState> = async function* (state) {
    await new Promise((resolve) => setTimeout(resolve, 200));
    return { count: state.count + 1 };
  };
  const timeoutRaceGraph: GraphDefinition<CounterState> = {
    id: "timeout-race",
    entryNode: "finish-late",
    nodes: { "finish-late": finishesAfterTimeout },
    edges: [],
    reducer: shallowMergeReducer,
  };
  registry.register("timeout-race", { buildGraph: () => timeoutRaceGraph, buildDeps: makeDeps });

  const waitAndObserveSignal: NodeFn<CounterState> = async function* (state, ctx) {
    // Long enough to comfortably outlast one 500ms cancel-poll tick with margin either side.
    await new Promise((resolve) => setTimeout(resolve, 800));
    return { count: state.count + (ctx.signal?.aborted ? 1000 : 1) };
  };
  const cancelGraph: GraphDefinition<CounterState> = {
    id: "cancel-wait",
    entryNode: "wait",
    nodes: { wait: waitAndObserveSignal },
    edges: [],
    reducer: shallowMergeReducer,
  };
  registry.register("cancel-wait", { buildGraph: () => cancelGraph, buildDeps: makeDeps });

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

  const pauseForever: NodeFn<CounterState> = async function* () {
    yield { type: "awaiting_approval", reason: "test pause, never resumed in this test" };
    return { count: 1 };
  };
  const pauseGraph: GraphDefinition<CounterState> = {
    id: "pause-forever",
    entryNode: "pause",
    nodes: { pause: pauseForever },
    edges: [],
    reducer: shallowMergeReducer,
  };
  registry.register("pause-forever", { buildGraph: () => pauseGraph, buildDeps: makeDeps });

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

    // The run's checkpoint must ALSO be marked failed with the underlying error message — not
    // just the tasks table row — otherwise GET /runs/:runId and the SSE stream never learn the
    // run failed (the checkpoint's status would otherwise stay "running" forever).
    const checkpoint = await checkpointStore.load("worker-fail-run");
    expect(checkpoint?.status).toBe("failed");
    expect(checkpoint?.error).toContain("boom");
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

  it("aborts a task's AbortSignal once cancelRequested becomes true mid-execution", async () => {
    await scheduler.enqueueStart("cancel-wait", { count: 0 }, { tenantId: "tenant-cancel", sessionId: "s1" }, "worker-cancel-run");
    const worker = new Worker(testDb.pool, registry, checkpointStore, { globalConcurrency: 10, tenantConcurrency: 10 });

    const pollPromise = worker.pollOnce();
    await new Promise((resolve) => setTimeout(resolve, 100));
    await checkpointStore.requestCancel("worker-cancel-run");
    await pollPromise;

    const checkpoint = await checkpointStore.load("worker-cancel-run");
    expect(checkpoint?.status).toBe("done");
    expect(checkpoint?.state).toEqual({ count: 1000 });
  });

  it("clears the cancel-poll interval on the runWithTimeout timeout path instead of leaking it for a genuinely hung task", async () => {
    await scheduler.enqueueStart(
      "hangs-forever",
      { count: 0 },
      { tenantId: "tenant-timeout-leak", sessionId: "s1" },
      "worker-timeout-leak-run",
      { maxAttempts: 1, timeoutMs: 50 },
    );
    const worker = new Worker(testDb.pool, registry, checkpointStore, { globalConcurrency: 10, tenantConcurrency: 10 });
    // Spies on loadForTenant, not load: the RLS migration (see
    // docs/superpowers/plans/2026-09-18-checkpoint-tracing-rls.md, Task 7) switched the
    // cancel-poll interval below to call loadForTenant instead — spying on the now-unused load()
    // would make this assertion trivially 0 === 0 regardless of whether the interval actually
    // leaks, silently defeating the whole point of this test.
    const loadSpy = vi.spyOn(checkpointStore, "loadForTenant");

    await worker.pollOnce();

    const rows = await db.select().from(tasks).where(eq(tasks.runId, "worker-timeout-leak-run"));
    expect(rows[0].status).toBe("failed");
    expect(rows[0].error).toContain("timed out");

    const callsForThisRun = () =>
      loadSpy.mock.calls.filter(([runId]) => runId === "worker-timeout-leak-run").length;
    const callsAfterSettle = callsForThisRun();

    // The cancel-poll interval ticks every 500ms and, on each tick, calls
    // checkpointStore.loadForTenant(task.runId, task.tenantId). If runWithTimeout's finally
    // didn't clear it on the timeout path (the leak this test guards against), the interval would
    // still be alive here — since the underlying "hangs-forever" node never resolves, runTask's
    // own promise is orphaned forever and its finally never runs — and it would call
    // loadForTenant() again well within this 700ms window, even though the task has already been
    // marked "failed" and nothing is polling it anymore.
    await new Promise((resolve) => setTimeout(resolve, 700));

    expect(callsForThisRun()).toBe(callsAfterSettle);
    loadSpy.mockRestore();
  });

  it("does not let an orphaned node execution that finishes normally AFTER a timeout-triggered failure silently overwrite the checkpoint's 'failed' status (race regression)", async () => {
    await scheduler.enqueueStart(
      "timeout-race",
      { count: 0 },
      { tenantId: "tenant-timeout-race", sessionId: "s1" },
      "worker-timeout-race-run",
      { maxAttempts: 1, timeoutMs: 30 },
    );
    const worker = new Worker(testDb.pool, registry, checkpointStore, { globalConcurrency: 10, tenantConcurrency: 10 });

    // The node's own delay (200ms) comfortably outlasts timeoutMs (30ms), so runWithTimeout()'s
    // Promise.race is won by the timeout: the task and checkpoint are marked "failed" here, while
    // the node's own promise keeps running, orphaned, in the background.
    await worker.pollOnce();

    const rows = await db.select().from(tasks).where(eq(tasks.runId, "worker-timeout-race-run"));
    expect(rows[0].status).toBe("failed");
    expect(rows[0].error).toContain("timed out");
    let checkpoint = await checkpointStore.load("worker-timeout-race-run");
    expect(checkpoint?.status).toBe("failed");
    expect(checkpoint?.error).toContain("timed out");

    // Give the orphaned node's promise (200ms delay, started when polling began) plenty of margin
    // to resolve and for GraphEngine's ordinary completeNode() path to call checkpointStore.save()
    // with a stale, non-failed checkpoint. Without the save() guard, this would silently flip the
    // checkpoint back to "done" with no error — reproducing the exact race the reviewer found.
    await new Promise((resolve) => setTimeout(resolve, 500));

    checkpoint = await checkpointStore.load("worker-timeout-race-run");
    expect(checkpoint?.status).toBe("failed");
    expect(checkpoint?.error).toContain("timed out");
  });

  it("delivers a pending steerMessage into the run's SteerChannel, then clears it, without ending the run", async () => {
    // Uses a graph whose single node reads ctx.steer and returns once a message arrives, proving
    // both that Worker actually threads a SteerChannel through to engine.run()/resumeFromCheckpoint()
    // and that it polls+delivers+clears steerMessage the same way it already does for cancelRequested.
    const steerRegistry = new GraphRegistry();
    const waitForSteer: NodeFn<{ received?: string }> = async function* (_state, ctx) {
      const message = await ctx.steer!.waitForNext();
      return { received: message };
    };
    const steerableGraph: GraphDefinition<{ received?: string }> = {
      id: "steerable",
      entryNode: "a",
      nodes: { a: waitForSteer },
      edges: [],
      reducer: shallowMergeReducer,
    };
    steerRegistry.register("steerable", { buildGraph: () => steerableGraph, buildDeps: makeDeps });

    const steerScheduler = new Scheduler(testDb.pool, steerRegistry, checkpointStore);
    const worker = new Worker(testDb.pool, steerRegistry, checkpointStore, { globalConcurrency: 5, tenantConcurrency: 5 });

    await steerScheduler.enqueueStart("steerable", {}, { tenantId: "tenant-a", sessionId: "s1" }, "worker-steer-run-1");

    // requestSteer BEFORE pollOnce() claims the task, so the Worker's very first poll tick (500ms
    // into runWithTimeout) finds it already pending -- avoids a timing race in this test.
    await checkpointStore.requestSteer("worker-steer-run-1", "turn left instead");

    await worker.pollOnce();
    // The poll interval is 500ms; give it two ticks' worth of margin.
    await new Promise((resolve) => setTimeout(resolve, 1200));

    const checkpoint = await checkpointStore.load("worker-steer-run-1");
    expect(checkpoint?.status).toBe("done");
    expect((checkpoint?.state as { received?: string })?.received).toBe("turn left instead");
    expect(checkpoint?.steerMessage).toBeUndefined();
  }, 10_000);

  it("calls onRunDone with the checkpoint once a task's checkpoint reaches status \"done\"", async () => {
    const onRunDone = vi.fn();
    await scheduler.enqueueStart(
      "trivial",
      { count: 0 },
      { tenantId: "tenant-done-hook", sessionId: "s1" },
      "worker-run-done-hook",
    );
    const worker = new Worker(testDb.pool, registry, checkpointStore, {
      globalConcurrency: 10,
      tenantConcurrency: 10,
      onRunDone,
    });
    await worker.pollOnce();

    expect(onRunDone).toHaveBeenCalledTimes(1);
    expect(onRunDone.mock.calls[0][0]).toMatchObject({ runId: "worker-run-done-hook", status: "done" });
  });

  it("does not call onRunDone when the checkpoint only reaches \"paused\" (mid-HITL), not truly done", async () => {
    const onRunDone = vi.fn();
    await scheduler.enqueueStart(
      "pause-forever",
      { count: 0 },
      { tenantId: "tenant-paused-hook", sessionId: "s1" },
      "worker-run-paused-hook",
    );
    const worker = new Worker(testDb.pool, registry, checkpointStore, {
      globalConcurrency: 10,
      tenantConcurrency: 10,
      onRunDone,
    });
    await worker.pollOnce();

    expect(onRunDone).not.toHaveBeenCalled();
  });
});
