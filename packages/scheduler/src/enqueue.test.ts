import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import { eq } from "drizzle-orm";
import type { EngineDeps, NodeFn } from "@opentalos/core-graph";
import { shallowMergeReducer, type GraphDefinition } from "@opentalos/core-graph";
import { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import { GraphRegistry } from "./graph-registry.js";
import { Scheduler } from "./enqueue.js";
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

beforeAll(async () => {
  testDb = await startTestDatabase();
  db = drizzle(testDb.pool);
  checkpointStore = new PostgresCheckpointStore(testDb.pool);
  registry = new GraphRegistry();
  const increment: NodeFn<CounterState> = async function* (state) {
    return { count: state.count + 1 };
  };
  const graph: GraphDefinition<CounterState> = {
    id: "counter",
    entryNode: "increment",
    nodes: { increment },
    edges: [],
    reducer: shallowMergeReducer,
  };
  registry.register("counter", { buildGraph: () => graph, buildDeps: makeDeps });
  scheduler = new Scheduler(testDb.pool, registry, checkpointStore);
}, 120_000);

afterAll(async () => {
  await stopTestDatabase(testDb);
});

describe("Scheduler.enqueueStart", () => {
  it("creates an initial checkpoint and a queued 'start' task", async () => {
    await scheduler.enqueueStart("counter", { count: 0 }, { tenantId: "tenant-a", sessionId: "s1" }, "enqueue-run-1");

    const checkpoint = await checkpointStore.load("enqueue-run-1");
    expect(checkpoint?.status).toBe("running");
    expect(checkpoint?.state).toEqual({ count: 0 });

    const rows = await db.select().from(tasks).where(eq(tasks.runId, "enqueue-run-1"));
    expect(rows).toHaveLength(1);
    expect(rows[0].kind).toBe("start");
    expect(rows[0].status).toBe("queued");
    expect(rows[0].graphId).toBe("counter");
    expect(rows[0].tenantId).toBe("tenant-a");
  });

  it("throws a clear error for an unregistered graphId", async () => {
    await expect(
      scheduler.enqueueStart("does-not-exist", { count: 0 }, { tenantId: "tenant-a", sessionId: "s1" }, "enqueue-run-bad"),
    ).rejects.toThrow(/Unknown graphId/);
  });
});

describe("Scheduler.enqueueResume", () => {
  it("creates a queued 'resume' task for a paused run", async () => {
    // Manually seed a paused checkpoint (Task 4/5 will exercise real pausing end-to-end).
    await checkpointStore.save({
      graphId: "counter",
      runId: "resume-seed-run",
      tenantId: "tenant-b",
      sessionId: "s1",
      nodeCursor: "increment",
      state: { count: 0 },
      pendingYields: [{ type: "awaiting_approval", reason: "confirm" }],
      status: "paused",
      createdAt: new Date().toISOString(),
    });

    await scheduler.enqueueResume("resume-seed-run", { type: "approval", approved: true });

    const rows = await db.select().from(tasks).where(eq(tasks.runId, "resume-seed-run"));
    expect(rows).toHaveLength(1);
    expect(rows[0].kind).toBe("resume");
    expect(rows[0].status).toBe("queued");
    expect(rows[0].resumeValue).toEqual({ type: "approval", approved: true });
  });

  it("throws when no checkpoint exists for the runId", async () => {
    await expect(scheduler.enqueueResume("no-such-run", { type: "approval", approved: true })).rejects.toThrow(
      /no checkpoint found/,
    );
  });

  it("throws when the checkpoint is not paused", async () => {
    await scheduler.enqueueStart("counter", { count: 0 }, { tenantId: "tenant-a", sessionId: "s1" }, "not-paused-run");
    await expect(scheduler.enqueueResume("not-paused-run", { type: "approval", approved: true })).rejects.toThrow(
      /is not paused/,
    );
  });
});
