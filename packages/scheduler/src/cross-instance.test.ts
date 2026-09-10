import { afterAll, beforeAll, describe, expect, it } from "vitest";
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

interface ApprovalState {
  count: number;
  approved: boolean;
}

function makeDeps(): Omit<EngineDeps, "checkpointStore"> {
  return {
    toolRegistry: { register() {}, get: () => undefined, list: () => [], execute: async (call) => ({ id: call.id, output: null }) },
    eventBus: { emit() {}, subscribe: () => () => {} },
  };
}

// Registers the SAME graphId ("approval-flow") from scratch, with newly-constructed node
// closures — simulating a fresh process that just started up and registered its graphs,
// with no shared object identity to the graph used by the "first process".
function buildFreshRegistry(): GraphRegistry {
  const registry = new GraphRegistry();
  const askApproval: NodeFn<ApprovalState> = async function* (state) {
    const resume = yield { type: "awaiting_approval", reason: "please approve" };
    return { count: state.count + 1, approved: resume?.type === "approval" ? resume.approved : false };
  };
  const graph: GraphDefinition<ApprovalState> = {
    id: "approval-flow",
    entryNode: "ask",
    nodes: { ask: askApproval },
    edges: [],
    reducer: shallowMergeReducer,
  };
  registry.register("approval-flow", { buildGraph: () => graph, buildDeps: makeDeps });
  return registry;
}

beforeAll(async () => {
  testDb = await startTestDatabase();
  db = drizzle(testDb.pool);
  checkpointStore = new PostgresCheckpointStore(testDb.pool);
}, 120_000);

afterAll(async () => {
  await stopTestDatabase(testDb);
});

describe("cross-instance durable resume", () => {
  it("resumes a run paused by one 'process' using a completely separate 'process' instance", async () => {
    // "Process 1": registers the graph, enqueues a start task, and runs a worker that
    // processes it up to the HITL pause.
    const registryProcess1 = buildFreshRegistry();
    const schedulerProcess1 = new Scheduler(testDb.pool, registryProcess1, checkpointStore);
    const workerProcess1 = new Worker(testDb.pool, registryProcess1, checkpointStore, {
      globalConcurrency: 10,
      tenantConcurrency: 10,
    });

    await schedulerProcess1.enqueueStart(
      "approval-flow",
      { count: 0, approved: false },
      { tenantId: "tenant-cross", sessionId: "s1" },
      "cross-instance-run-1",
    );
    await workerProcess1.pollOnce();

    const pausedCheckpoint = await checkpointStore.load("cross-instance-run-1");
    expect(pausedCheckpoint?.status).toBe("paused");

    const taskAfterStart = await db.select().from(tasks).where(eq(tasks.runId, "cross-instance-run-1"));
    expect(taskAfterStart[0].status).toBe("done"); // the START task itself completed; the RUN paused

    // "Process 2": a brand-new GraphRegistry (freshly re-registers "approval-flow" with new
    // node closures), a brand-new Scheduler, and a brand-new Worker — none of them share any
    // object with process 1's instances. This is what proves durable, cross-process resume,
    // not just "two variables in the same test pointing at the same in-memory object".
    const registryProcess2 = buildFreshRegistry();
    const schedulerProcess2 = new Scheduler(testDb.pool, registryProcess2, checkpointStore);
    const workerProcess2 = new Worker(testDb.pool, registryProcess2, checkpointStore, {
      globalConcurrency: 10,
      tenantConcurrency: 10,
    });

    await schedulerProcess2.enqueueResume("cross-instance-run-1", { type: "approval", approved: true });
    await workerProcess2.pollOnce();

    const finalCheckpoint = await checkpointStore.load("cross-instance-run-1");
    expect(finalCheckpoint?.status).toBe("done");
    expect(finalCheckpoint?.state).toEqual({ count: 1, approved: true });
  });
});
