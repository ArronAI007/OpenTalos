# Task Scheduling Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the already-approved `@opentalos/core-graph` engine genuine cross-process durable execution — a real PostgreSQL-backed `CheckpointStore`, and a task queue + single-process async-concurrent worker that can start and resume graph runs across process restarts, enforcing per-tenant and global concurrency caps plus timeout/retry.

**Architecture:** A pure-addition extension to `GraphEngine` (`resumeFromCheckpoint`) lets a paused node be resumed by replaying its function from the checkpoint's saved (pre-node) state, rather than requiring the original in-memory generator — this is the one piece that makes cross-process resume possible at all. On top of that: `@opentalos/postgres-checkpoint` implements `CheckpointStore` against a real Postgres table via Drizzle ORM; `@opentalos/scheduler` adds a `tasks` table, a `GraphRegistry` (mapping a `graphId` string to a constructor for the real `GraphDefinition`/`EngineDeps`, since those contain closures that can't live in a database row), an `enqueueStart`/`enqueueResume` API, and a `Worker` that claims queued tasks via `SELECT ... FOR UPDATE SKIP LOCKED` inside a single transaction (so the claim and the lock are atomic), then runs or resumes the corresponding graph.

**Tech Stack:** TypeScript (Node >= 20, ESM), `drizzle-orm` + `pg` for PostgreSQL access, `testcontainers`/`@testcontainers/postgresql` for real-Postgres integration tests (Docker required), Vitest.

Reference spec: `docs/superpowers/specs/2026-09-09-task-scheduling-infrastructure-design.md`

This plan builds on the already-completed core agent runtime engine plan (`docs/superpowers/plans/2026-09-09-core-agent-runtime-engine.md`). Tasks 1-13 there are done, reviewed, and merged to `main`. Work from the repo root: `/Users/arron/Desktop/ArronAI/OpenTalos`.

---

## Task 1: `core-graph` — Add `resumeFromCheckpoint` (replay-based cross-process resume)

This is a **pure-addition** extension to the already-approved `packages/core-graph/src/engine.ts`. No existing method's behavior or signature changes; a new optional parameter is added to one private method, and one new public method is added. All 17 existing tests in this package must continue to pass unchanged.

**Files:**
- Modify: `packages/core-graph/src/engine.ts`
- Modify: `packages/core-graph/src/index.ts`
- Test: `packages/core-graph/src/resume-from-checkpoint.test.ts`

- [ ] **Step 1: Write the failing tests — `packages/core-graph/src/resume-from-checkpoint.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { TenantContext } from "@opentalos/core-types";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryToolRegistry } from "@opentalos/tool-registry";
import { GraphEngine } from "./engine.js";
import { shallowMergeReducer } from "./reducer.js";
import type { GraphDefinition, NodeFn } from "./types.js";

interface CounterState {
  count: number;
  approved?: boolean;
}

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

function makeDeps() {
  const toolRegistry = new InMemoryToolRegistry();
  toolRegistry.register({
    definition: { name: "increment", description: "returns +1", inputSchema: {} },
    async execute() {
      return { id: "tool-1", output: 1 };
    },
  });
  return { toolRegistry, eventBus: new InMemoryEventBus(), checkpointStore: new InMemoryCheckpointStore() };
}

describe("GraphEngine.resumeFromCheckpoint", () => {
  it("resumes a paused checkpoint on a brand-new engine instance (no in-memory generator)", async () => {
    const askApproval: NodeFn<CounterState> = async function* (state) {
      const resume = yield { type: "awaiting_approval", reason: "please confirm" };
      return { count: state.count + 1, approved: resume?.type === "approval" ? resume.approved : false };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g1",
      entryNode: "ask",
      nodes: { ask: askApproval },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engineA = new GraphEngine(graph, deps);
    let checkpoint = engineA.start({ count: 0 }, tenant, "run-1");
    checkpoint = await engineA.run(checkpoint);
    expect(checkpoint.status).toBe("paused");

    // A fresh GraphEngine instance, sharing only the checkpoint object and deps — simulating
    // a completely different process that has no knowledge of engineA's in-memory `paused` map.
    const engineB = new GraphEngine(graph, deps);
    const resumed = await engineB.resumeFromCheckpoint(checkpoint, { type: "approval", approved: true });
    expect(resumed.status).toBe("done");
    expect(resumed.state).toEqual({ count: 1, approved: true });
  });

  it("replays and re-resolves a tool call that happened before the approval yield", async () => {
    const callToolThenAsk: NodeFn<CounterState> = async function* (state) {
      const toolResume = yield { type: "awaiting_tool", toolCall: { id: "t1", name: "increment", input: {} } };
      const delta = toolResume?.type === "tool_result" ? (toolResume.result.output as number) : 0;
      const approvalResume = yield { type: "awaiting_approval", reason: "confirm the increment" };
      const approved = approvalResume?.type === "approval" ? approvalResume.approved : false;
      return { count: state.count + delta, approved };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g2",
      entryNode: "node",
      nodes: { node: callToolThenAsk },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engineA = new GraphEngine(graph, deps);
    let checkpoint = engineA.start({ count: 0 }, tenant, "run-2");
    checkpoint = await engineA.run(checkpoint);
    expect(checkpoint.status).toBe("paused");
    const eventsBeforeResume = deps.eventBus.getEvents().filter((e) => e.type === "tool_call_end").length;
    expect(eventsBeforeResume).toBe(1);

    const engineB = new GraphEngine(graph, deps);
    const resumed = await engineB.resumeFromCheckpoint(checkpoint, { type: "approval", approved: true });
    expect(resumed.status).toBe("done");
    expect(resumed.state).toEqual({ count: 1, approved: true });
    // Replay re-drives the node from the top, so the tool yield is auto-resolved a second time.
    const eventsAfterResume = deps.eventBus.getEvents().filter((e) => e.type === "tool_call_end").length;
    expect(eventsAfterResume).toBe(2);
  });

  it("pauses again (with a fresh reason) if the node yields a second approval during replay", async () => {
    const increment: NodeFn<CounterState> = async function* (state) {
      return { count: state.count + 1 };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g3",
      entryNode: "increment",
      nodes: { increment },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const alwaysRequireApproval = { check: async () => "require_approval" as const };
    const engineA = new GraphEngine(graph, { ...deps, guardrails: [alwaysRequireApproval] });
    let checkpoint = engineA.start({ count: 0 }, tenant, "run-3");
    checkpoint = await engineA.run(checkpoint); // before-phase pause

    const engineB = new GraphEngine(graph, { ...deps, guardrails: [alwaysRequireApproval] });
    const afterFirstResume = await engineB.resumeFromCheckpoint(checkpoint, { type: "approval", approved: true });
    expect(afterFirstResume.status).toBe("paused"); // after-phase pause, hit during replay

    const engineC = new GraphEngine(graph, { ...deps, guardrails: [alwaysRequireApproval] });
    const afterSecondResume = await engineC.resumeFromCheckpoint(afterFirstResume, { type: "approval", approved: true });
    expect(afterSecondResume.status).toBe("done");
    expect(afterSecondResume.state.count).toBe(1);
  });

  it("throws a clear error when the checkpoint is not paused", async () => {
    const increment: NodeFn<CounterState> = async function* (state) {
      return { count: state.count + 1 };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g4",
      entryNode: "increment",
      nodes: { increment },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engine = new GraphEngine(graph, deps);
    const doneCheckpoint = await engine.run(engine.start({ count: 0 }, tenant, "run-4"));
    expect(doneCheckpoint.status).toBe("done");

    await expect(engine.resumeFromCheckpoint(doneCheckpoint, { type: "approval", approved: true })).rejects.toThrow(
      /not in a resumable paused state/,
    );
  });

  it("throws a clear error when nodeCursor references an unknown node", async () => {
    const increment: NodeFn<CounterState> = async function* (state) {
      return { count: state.count + 1 };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g5",
      entryNode: "increment",
      nodes: { increment },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engine = new GraphEngine(graph, deps);
    let checkpoint = engine.start({ count: 0 }, tenant, "run-5");
    checkpoint = await engine.run(checkpoint);
    const corrupted = { ...checkpoint, status: "paused" as const, nodeCursor: "does-not-exist" };
    await expect(engine.resumeFromCheckpoint(corrupted, { type: "approval", approved: true })).rejects.toThrow(
      /Unknown node/,
    );
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --filter @opentalos/core-graph test -- resume-from-checkpoint`
Expected: FAIL — `resumeFromCheckpoint` is not a function.

- [ ] **Step 3: Add a `replayQueue` parameter to `runNodeToCompletion` in `packages/core-graph/src/engine.ts`**

**Why a queue, not a single value:** a node can pause more than once per execution (e.g. a guardrail requiring approval both before and after the node body runs — already supported by `resume()` since Task 8 of the core engine plan). Feeding a *single* replay value to whichever `awaiting_approval` yield replay happens to reach first would silently answer the *wrong* pending question whenever a checkpoint was actually paused at a *later* yield within the same node execution. A queue, drained one value per yield in order, replays every previously-resolved yield faithfully before the truly new value is applied at the current pending yield.

Replace:
```ts
  private async runNodeToCompletion(
    nodeId: string,
    generator: NodeGenerator<TState>,
    tenant: TenantContext,
    runId: string,
    initialResume: NodeResumeValue,
    onApprovalPause: (generator: NodeGenerator<TState>) => void,
  ): Promise<NodeOutcome<TState>> {
    const advance = async (value: NodeResumeValue) => {
      try {
        return await generator.next(value);
      } catch (cause) {
        const error = new NodeError(nodeId, cause, false);
        this.emitTrace("error", runId, tenant, { nodeId, message: error.message });
        throw error;
      }
    };

    let result = await advance(initialResume);
    while (!result.done) {
      const yielded = result.value;
      if (yielded.type === "awaiting_tool") {
        this.emitTrace("tool_call_start", runId, tenant, { toolCall: yielded.toolCall });
        const toolResult = await this.deps.toolRegistry.execute(yielded.toolCall, tenant);
        this.emitTrace("tool_call_end", runId, tenant, { toolResult });
        result = await advance({ type: "tool_result", result: toolResult });
        continue;
      }
      onApprovalPause(generator);
      return { status: "paused", reason: yielded.reason };
    }
    return { status: "done", partial: result.value };
  }
```
with:
```ts
  private async runNodeToCompletion(
    nodeId: string,
    generator: NodeGenerator<TState>,
    tenant: TenantContext,
    runId: string,
    initialResume: NodeResumeValue,
    onApprovalPause: (generator: NodeGenerator<TState>) => void,
    replayQueue?: NodeResumeValue[],
  ): Promise<NodeOutcome<TState>> {
    // Copy so draining it here never mutates the caller's array — resumeFromCheckpoint still
    // needs its own original replayQueue afterwards, to build the next checkpoint's pendingYields.
    const queue = replayQueue ? [...replayQueue] : undefined;

    const advance = async (value: NodeResumeValue) => {
      try {
        return await generator.next(value);
      } catch (cause) {
        const error = new NodeError(nodeId, cause, false);
        this.emitTrace("error", runId, tenant, { nodeId, message: error.message });
        throw error;
      }
    };

    let result = await advance(initialResume);
    while (!result.done) {
      const yielded = result.value;
      if (yielded.type === "awaiting_tool") {
        this.emitTrace("tool_call_start", runId, tenant, { toolCall: yielded.toolCall });
        const toolResult = await this.deps.toolRegistry.execute(yielded.toolCall, tenant);
        this.emitTrace("tool_call_end", runId, tenant, { toolResult });
        result = await advance({ type: "tool_result", result: toolResult });
        continue;
      }
      // On replay, each awaiting_approval yield consumes the next queued value in order — this
      // is what makes cross-process resume possible: the node is being re-driven from scratch
      // (see resumeFromCheckpoint), and everything already resolved in an earlier replay pass
      // must be faithfully re-answered before the genuinely new value is applied. Once the queue
      // is empty, the next awaiting_approval yield pauses for real, exactly like a first-time pause.
      if (queue && queue.length > 0) {
        const seeded = queue.shift() as NodeResumeValue;
        result = await advance(seeded);
        continue;
      }
      onApprovalPause(generator);
      return { status: "paused", reason: yielded.reason };
    }
    return { status: "done", partial: result.value };
  }
```

- [ ] **Step 4: Add `resumeFromCheckpoint` method to `GraphEngine` in `packages/core-graph/src/engine.ts`**

Add this new public method to the `GraphEngine` class, right after the existing `resume` method:

```ts
  /**
   * Resumes a paused checkpoint WITHOUT requiring the original in-memory generator — instead
   * it reconstructs a fresh generator from the checkpoint's saved (pre-node) state and replays
   * the node function from the top, in order feeding back every previously-resolved approval
   * (recorded in `checkpoint.pendingYields`, everything but the last element) before applying
   * the newly-supplied `resumeValue` at the current pending yield. This is what makes durable,
   * cross-process resume possible (see resume() for the same-process, in-memory-generator
   * alternative, which is faster but only works within one process's lifetime).
   * Relies on node functions AND guardrails being replay-safe: no non-idempotent side effects
   * before their first yield each time they're replayed.
   * Unlike resume(), this does NOT itself validate checkpoint.tenantId/sessionId against a
   * caller-asserted tenant — there is no shared in-memory state keyed loosely by runId for a
   * mismatched tenant to collide with here, since the full Checkpoint object is passed in
   * directly. Tenant authorization for who may trigger a resume for a given runId is the
   * responsibility of whoever loads the checkpoint and calls this method (the scheduler's
   * enqueueResume, built in a later task).
   */
  async resumeFromCheckpoint(checkpoint: Checkpoint<TState>, resumeValue: NodeResumeValue): Promise<Checkpoint<TState>> {
    if (checkpoint.status !== "paused" || typeof checkpoint.nodeCursor !== "string") {
      throw new Error(`Run ${checkpoint.runId} is not in a resumable paused state`);
    }
    const nodeId = checkpoint.nodeCursor;
    const nodeFn = this.graph.nodes[nodeId];
    if (!nodeFn) {
      throw new Error(`Unknown node: ${nodeId}`);
    }
    const tenant: TenantContext = { tenantId: checkpoint.tenantId, sessionId: checkpoint.sessionId };
    const guardedNodeFn = this.wrapWithGuardrails(nodeId, nodeFn);
    const generator = guardedNodeFn(checkpoint.state, { tenant, eventBus: this.deps.eventBus });

    // pendingYields is either length 1 (a "fresh" pause produced by step(), no replay history
    // yet — the common case) or length > 1 (a pause produced by an earlier resumeFromCheckpoint
    // call, where every element but the last is a resume value already fed to an earlier yield
    // during a previous replay of this same node execution). Either way, everything but the
    // last element is the prior-answers history to replay before applying the new resumeValue.
    const priorAnswers = checkpoint.pendingYields.slice(0, -1) as NodeResumeValue[];
    const replayQueue = [...priorAnswers, resumeValue];

    const outcome = await this.runNodeToCompletion(
      nodeId,
      generator,
      tenant,
      checkpoint.runId,
      undefined,
      () => {
        // No live generator to persist here — resumeFromCheckpoint always reconstructs a fresh
        // generator by replay next time too, so there is nothing useful to keep in `this.paused`.
      },
      replayQueue,
    );

    if (outcome.status === "paused") {
      this.emitTrace("hitl_interrupt", checkpoint.runId, tenant, { nodeId, reason: outcome.reason });
      const pausedCheckpoint: Checkpoint<TState> = {
        ...checkpoint,
        nodeCursor: nodeId,
        status: "paused",
        pendingYields: [...replayQueue, { type: "awaiting_approval", reason: outcome.reason }],
      };
      await this.deps.checkpointStore.save(pausedCheckpoint);
      return pausedCheckpoint;
    }

    this.emitTrace("node_exit", checkpoint.runId, tenant, { nodeId });
    const advanced = await this.completeNode(nodeId, outcome.partial, checkpoint);
    return advanced.status === "running" ? this.run(advanced) : advanced;
  }
```

Note: this does **not** validate that `checkpoint.tenantId`/`sessionId` match some caller-asserted tenant, unlike `resume()`'s spoof check. That's intentional — `resumeFromCheckpoint` takes the full `Checkpoint` object (not just a bare `runId`), and there is no shared in-memory state keyed loosely by `runId` for a mismatched tenant to collide with. Tenant authorization for *which caller* is allowed to trigger a resume for a given `runId` is the responsibility of whoever loads the checkpoint and calls this method (the scheduler's `enqueueResume`, built in a later task) — the engine itself stays decoupled from identity/authorization concerns, consistent with the design established in the core engine plan.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pnpm --filter @opentalos/core-graph test`
Expected: PASS — all 20 tests in the package green (15 pre-existing engine tests + 2 fan-out + 3 subgraph... — run the full suite and confirm the previously-passing 17 are still green, plus these 5 new ones = 22 total. If the exact pre-existing count differs from what's written here, that's fine — the important thing is zero regressions and 5 new passing tests).

- [ ] **Step 6: Confirm zero regressions and rebuild**

Run: `pnpm --filter @opentalos/core-graph build && pnpm --filter @opentalos/core-graph typecheck`
Expected: PASS, no TypeScript errors, `dist/` still has no test artifacts.

- [ ] **Step 7: Commit**

```bash
git add packages/core-graph
git commit -m "feat(core-graph): add resumeFromCheckpoint for replay-based cross-process resume"
```

---

## Task 2: `postgres-checkpoint` Package

**Files:**
- Create: `packages/postgres-checkpoint/package.json`
- Create: `packages/postgres-checkpoint/tsconfig.json`
- Create: `packages/postgres-checkpoint/src/schema.ts`
- Create: `packages/postgres-checkpoint/src/store.ts`
- Create: `packages/postgres-checkpoint/src/index.ts`
- Test: `packages/postgres-checkpoint/src/store.test.ts`

Migrations are explicitly out of scope for this phase (see the design spec's section 8) — the test setup creates the table directly via a `CREATE TABLE` statement that must stay in sync with `schema.ts`'s column definitions. This requires a running Docker daemon (used by `testcontainers` to start a real, ephemeral PostgreSQL instance per test file).

- [ ] **Step 1: Create `packages/postgres-checkpoint/package.json`**

```json
{
  "name": "@opentalos/postgres-checkpoint",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@opentalos/core-types": "workspace:*",
    "drizzle-orm": "^0.45.2",
    "pg": "^8.23.0"
  },
  "devDependencies": {
    "@types/pg": "^8.23.1",
    "testcontainers": "^12.1.0",
    "@testcontainers/postgresql": "^12.1.0"
  }
}
```

- [ ] **Step 2: Create `packages/postgres-checkpoint/tsconfig.json`**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src"],
  "exclude": ["src/**/*.test.ts"]
}
```

- [ ] **Step 3: Create `packages/postgres-checkpoint/src/schema.ts`**

```ts
import { jsonb, pgTable, text, timestamp } from "drizzle-orm/pg-core";

export const checkpoints = pgTable("checkpoints", {
  runId: text("run_id").primaryKey(),
  graphId: text("graph_id").notNull(),
  tenantId: text("tenant_id").notNull(),
  sessionId: text("session_id").notNull(),
  nodeCursor: jsonb("node_cursor").notNull(),
  state: jsonb("state").notNull(),
  pendingYields: jsonb("pending_yields").notNull(),
  status: text("status").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});
```

- [ ] **Step 4: Write the failing tests — `packages/postgres-checkpoint/src/store.test.ts`**

```ts
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";
import type { Checkpoint } from "@opentalos/core-types";
import { PostgresCheckpointStore } from "./store.js";

let container: StartedPostgreSqlContainer;
let pool: Pool;
let store: PostgresCheckpointStore;

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
  `);
  store = new PostgresCheckpointStore(pool);
}, 120_000);

afterAll(async () => {
  await pool.end();
  await container.stop();
});

function makeCheckpoint(overrides: Partial<Checkpoint> = {}): Checkpoint {
  return {
    graphId: "g1",
    runId: "run-1",
    tenantId: "tenant-a",
    sessionId: "session-1",
    nodeCursor: "start",
    state: { count: 0 },
    pendingYields: [],
    status: "running",
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

describe("PostgresCheckpointStore", () => {
  it("saves and loads a checkpoint by runId", async () => {
    const checkpoint = makeCheckpoint({ runId: "run-save-load" });
    await store.save(checkpoint);
    const loaded = await store.load("run-save-load");
    expect(loaded?.runId).toBe("run-save-load");
    expect(loaded?.state).toEqual({ count: 0 });
    expect(loaded?.status).toBe("running");
  });

  it("returns undefined for an unknown runId", async () => {
    await expect(store.load("does-not-exist")).resolves.toBeUndefined();
  });

  it("upserts on repeated save with the same runId (overwrites, doesn't duplicate)", async () => {
    await store.save(makeCheckpoint({ runId: "run-upsert", status: "running" }));
    await store.save(makeCheckpoint({ runId: "run-upsert", status: "done", state: { count: 5 } }));
    const loaded = await store.load("run-upsert");
    expect(loaded?.status).toBe("done");
    expect(loaded?.state).toEqual({ count: 5 });
  });

  it("lists checkpoints filtered by tenantId and sessionId", async () => {
    await store.save(makeCheckpoint({ runId: "list-run-1", tenantId: "tenant-x", sessionId: "s1" }));
    await store.save(makeCheckpoint({ runId: "list-run-2", tenantId: "tenant-y", sessionId: "s1" }));
    await store.save(makeCheckpoint({ runId: "list-run-3", tenantId: "tenant-x", sessionId: "s2" }));

    const tenantXOnly = await store.list({ tenantId: "tenant-x" });
    expect(tenantXOnly.map((c) => c.runId).sort()).toEqual(["list-run-1", "list-run-3"]);

    const tenantXAndSession1 = await store.list({ tenantId: "tenant-x", sessionId: "s1" });
    expect(tenantXAndSession1.map((c) => c.runId)).toEqual(["list-run-1"]);
  });

  it("round-trips nodeCursor as an arbitrary JSON value (plain string or a parallel-descriptor object)", async () => {
    const parallelCursor = { type: "parallel", branches: ["a", "b"], joinTo: "join" };
    await store.save(makeCheckpoint({ runId: "run-parallel-cursor", nodeCursor: parallelCursor }));
    const loaded = await store.load("run-parallel-cursor");
    expect(loaded?.nodeCursor).toEqual(parallelCursor);
  });
});
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pnpm install && pnpm --filter @opentalos/postgres-checkpoint test`
Expected: FAIL — `PostgresCheckpointStore` is not defined. (This step will also download the `postgres:16-alpine` Docker image on first run if not already cached — expect the first run to take longer.)

- [ ] **Step 6: Implement `packages/postgres-checkpoint/src/store.ts`**

```ts
import { and, eq } from "drizzle-orm";
import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import type { Pool } from "pg";
import type { Checkpoint, CheckpointQuery, CheckpointStore } from "@opentalos/core-types";
import { checkpoints } from "./schema.js";

type CheckpointRow = typeof checkpoints.$inferSelect;

export class PostgresCheckpointStore implements CheckpointStore {
  private readonly db: NodePgDatabase;

  constructor(pool: Pool) {
    this.db = drizzle(pool);
  }

  async save(checkpoint: Checkpoint): Promise<void> {
    const values = {
      runId: checkpoint.runId,
      graphId: checkpoint.graphId,
      tenantId: checkpoint.tenantId,
      sessionId: checkpoint.sessionId,
      nodeCursor: checkpoint.nodeCursor,
      state: checkpoint.state,
      pendingYields: checkpoint.pendingYields,
      status: checkpoint.status,
      createdAt: new Date(checkpoint.createdAt),
    };
    await this.db
      .insert(checkpoints)
      .values(values)
      .onConflictDoUpdate({
        target: checkpoints.runId,
        set: {
          graphId: values.graphId,
          tenantId: values.tenantId,
          sessionId: values.sessionId,
          nodeCursor: values.nodeCursor,
          state: values.state,
          pendingYields: values.pendingYields,
          status: values.status,
          updatedAt: new Date(),
        },
      });
  }

  async load(runId: string): Promise<Checkpoint | undefined> {
    const rows = await this.db.select().from(checkpoints).where(eq(checkpoints.runId, runId)).limit(1);
    return rows[0] ? this.toCheckpoint(rows[0]) : undefined;
  }

  async list(query: CheckpointQuery): Promise<Checkpoint[]> {
    const conditions = [];
    if (query.tenantId) conditions.push(eq(checkpoints.tenantId, query.tenantId));
    if (query.sessionId) conditions.push(eq(checkpoints.sessionId, query.sessionId));
    const rows =
      conditions.length > 0
        ? await this.db.select().from(checkpoints).where(and(...conditions))
        : await this.db.select().from(checkpoints);
    return rows.map((row) => this.toCheckpoint(row));
  }

  private toCheckpoint(row: CheckpointRow): Checkpoint {
    return {
      runId: row.runId,
      graphId: row.graphId,
      tenantId: row.tenantId,
      sessionId: row.sessionId,
      nodeCursor: row.nodeCursor,
      state: row.state,
      pendingYields: row.pendingYields as unknown[],
      status: row.status as Checkpoint["status"],
      createdAt: row.createdAt.toISOString(),
    };
  }
}
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pnpm --filter @opentalos/postgres-checkpoint test`
Expected: PASS — all 5 tests green.

- [ ] **Step 8: Create `packages/postgres-checkpoint/src/index.ts`**

```ts
export { PostgresCheckpointStore } from "./store.js";
export { checkpoints } from "./schema.js";
```

- [ ] **Step 9: Rebuild and re-run tests, verify no test artifacts in dist/**

Run: `pnpm --filter @opentalos/postgres-checkpoint build && pnpm --filter @opentalos/postgres-checkpoint test && ls packages/postgres-checkpoint/dist/`
Expected: PASS; `dist/` contains only `index.{js,d.ts}`, `schema.{js,d.ts}`, `store.{js,d.ts}` — no `.test.js`.

- [ ] **Step 10: Commit**

```bash
git add packages/postgres-checkpoint pnpm-lock.yaml
git commit -m "feat(postgres-checkpoint): add real PostgreSQL-backed CheckpointStore"
```

---

## Task 3: `scheduler` Package — Graph Registry and Enqueue API

**Files:**
- Create: `packages/scheduler/package.json`
- Create: `packages/scheduler/tsconfig.json`
- Create: `packages/scheduler/src/graph-registry.ts`
- Create: `packages/scheduler/src/schema.ts`
- Create: `packages/scheduler/src/enqueue.ts`
- Create: `packages/scheduler/src/test-db.ts` (shared test-only helper — reused by Tasks 4 and 5 too, see Step 7a)
- Create: `packages/scheduler/src/index.ts`
- Test: `packages/scheduler/src/graph-registry.test.ts`
- Test: `packages/scheduler/src/enqueue.test.ts`

- [ ] **Step 1: Create `packages/scheduler/package.json`**

```json
{
  "name": "@opentalos/scheduler",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@opentalos/core-types": "workspace:*",
    "@opentalos/core-graph": "workspace:*",
    "@opentalos/postgres-checkpoint": "workspace:*",
    "drizzle-orm": "^0.45.2",
    "pg": "^8.23.0"
  },
  "devDependencies": {
    "@types/pg": "^8.23.1",
    "testcontainers": "^12.1.0",
    "@testcontainers/postgresql": "^12.1.0"
  }
}
```

- [ ] **Step 2: Create `packages/scheduler/tsconfig.json`**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src"],
  "exclude": ["src/**/*.test.ts", "src/test-db.ts"]
}
```

`test-db.ts` is excluded from the build the same way test files are: it's a shared testing helper (starts a real ephemeral Postgres via `testcontainers` and creates both tables), not part of the package's shipped surface, and it imports `devDependencies` (`@testcontainers/postgresql`) that a production build shouldn't need to resolve.

### Part A — `GraphRegistry` (no database needed)

- [ ] **Step 3: Write the failing tests — `packages/scheduler/src/graph-registry.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { EngineDeps, GraphDefinition, NodeFn } from "@opentalos/core-graph";
import { shallowMergeReducer } from "@opentalos/core-graph";
import { GraphRegistry } from "./graph-registry.js";

interface State {
  count: number;
}

function makeGraph(): GraphDefinition<State> {
  const increment: NodeFn<State> = async function* (state) {
    return { count: state.count + 1 };
  };
  return { id: "counter", entryNode: "increment", nodes: { increment }, edges: [], reducer: shallowMergeReducer };
}

function makeDeps(): Omit<EngineDeps, "checkpointStore"> {
  return {
    toolRegistry: { register() {}, get: () => undefined, list: () => [], execute: async (call) => ({ id: call.id, output: null }) },
    eventBus: { emit() {}, subscribe: () => () => {} },
  };
}

describe("GraphRegistry", () => {
  it("registers and retrieves a graph by id", () => {
    const registry = new GraphRegistry();
    registry.register("counter", { buildGraph: makeGraph, buildDeps: makeDeps });
    const registration = registry.get("counter");
    expect(registration).toBeDefined();
    expect(registration?.buildGraph().id).toBe("counter");
  });

  it("returns undefined from get() for an unregistered graphId", () => {
    const registry = new GraphRegistry();
    expect(registry.get("missing")).toBeUndefined();
  });

  it("getOrThrow throws a clear error for an unregistered graphId", () => {
    const registry = new GraphRegistry();
    expect(() => registry.getOrThrow("missing")).toThrow(/Unknown graphId: "missing"/);
  });

  it("getOrThrow returns the registration for a registered graphId", () => {
    const registry = new GraphRegistry();
    registry.register("counter", { buildGraph: makeGraph, buildDeps: makeDeps });
    expect(registry.getOrThrow("counter").buildGraph().id).toBe("counter");
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pnpm install && pnpm --filter @opentalos/scheduler test -- graph-registry`
Expected: FAIL — `GraphRegistry` is not defined.

- [ ] **Step 5: Implement `packages/scheduler/src/graph-registry.ts`**

```ts
import type { EngineDeps, GraphDefinition } from "@opentalos/core-graph";

export interface GraphRegistration<TState> {
  buildGraph: () => GraphDefinition<TState>;
  /** Everything the graph's own nodes need except checkpoint storage — the scheduler always
   * injects its own PostgresCheckpointStore, so registrations never provide one. */
  buildDeps: () => Omit<EngineDeps, "checkpointStore">;
}

export class GraphRegistry {
  private readonly registrations = new Map<string, GraphRegistration<unknown>>();

  register<TState>(graphId: string, registration: GraphRegistration<TState>): void {
    this.registrations.set(graphId, registration as GraphRegistration<unknown>);
  }

  get(graphId: string): GraphRegistration<unknown> | undefined {
    return this.registrations.get(graphId);
  }

  getOrThrow(graphId: string): GraphRegistration<unknown> {
    const registration = this.registrations.get(graphId);
    if (!registration) {
      throw new Error(`Unknown graphId: "${graphId}" is not registered`);
    }
    return registration;
  }
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pnpm --filter @opentalos/scheduler test -- graph-registry`
Expected: PASS — all 4 tests green.

### Part B — `tasks` schema and enqueue API

- [ ] **Step 7: Create `packages/scheduler/src/schema.ts`**

```ts
import { integer, jsonb, pgTable, serial, text, timestamp } from "drizzle-orm/pg-core";

export const tasks = pgTable("tasks", {
  id: serial("id").primaryKey(),
  runId: text("run_id").notNull(),
  graphId: text("graph_id").notNull(),
  tenantId: text("tenant_id").notNull(),
  sessionId: text("session_id").notNull(),
  kind: text("kind").notNull(), // "start" | "resume"
  resumeValue: jsonb("resume_value"),
  status: text("status").notNull(), // "queued" | "running" | "done" | "failed"
  attempts: integer("attempts").notNull().default(0),
  maxAttempts: integer("max_attempts").notNull().default(3),
  timeoutMs: integer("timeout_ms").notNull().default(30_000),
  priority: integer("priority").notNull().default(0),
  availableAt: timestamp("available_at", { withTimezone: true }).notNull().defaultNow(),
  lockedAt: timestamp("locked_at", { withTimezone: true }),
  error: text("error"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});
```

- [ ] **Step 8: Create the shared test-database helper — `packages/scheduler/src/test-db.ts`**

Tasks 3 (this one), 4, and 5 each need a fresh, ephemeral Postgres instance with both tables created. Rather than duplicating the container/connection/`CREATE TABLE` boilerplate across three test files, extract it once here and import it from each.

```ts
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";

export const CREATE_TABLES_SQL = `
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
`;

export interface TestDatabase {
  container: StartedPostgreSqlContainer;
  pool: Pool;
}

export async function startTestDatabase(): Promise<TestDatabase> {
  const container = await new PostgreSqlContainer("postgres:16-alpine").start();
  const pool = new Pool({ connectionString: container.getConnectionUri() });
  await pool.query(CREATE_TABLES_SQL);
  return { container, pool };
}

export async function stopTestDatabase(db: TestDatabase): Promise<void> {
  await db.pool.end();
  await db.container.stop();
}
```

- [ ] **Step 9: Write the failing tests — `packages/scheduler/src/enqueue.test.ts`**

```ts
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
```

- [ ] **Step 10: Run tests to verify they fail**

Run: `pnpm install && pnpm --filter @opentalos/scheduler test -- enqueue`
Expected: FAIL — `Scheduler` is not defined. (First run will also download the `postgres:16-alpine` Docker image if not already cached.)

- [ ] **Step 11: Implement `packages/scheduler/src/enqueue.ts`**

```ts
import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import type { Pool } from "pg";
import type { TenantContext } from "@opentalos/core-types";
import { GraphEngine, type NodeResumeValue } from "@opentalos/core-graph";
import type { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import type { GraphRegistry } from "./graph-registry.js";
import { tasks } from "./schema.js";

export interface EnqueueOptions {
  maxAttempts?: number;
  timeoutMs?: number;
  priority?: number;
}

export class Scheduler {
  private readonly db: NodePgDatabase;

  constructor(
    pool: Pool,
    private readonly registry: GraphRegistry,
    private readonly checkpointStore: PostgresCheckpointStore,
  ) {
    this.db = drizzle(pool);
  }

  async enqueueStart<TState>(
    graphId: string,
    initialState: TState,
    tenant: TenantContext,
    runId: string,
    options: EnqueueOptions = {},
  ): Promise<void> {
    const registration = this.registry.getOrThrow(graphId);
    const graph = registration.buildGraph();
    const deps = registration.buildDeps();
    const engine = new GraphEngine(graph, { ...deps, checkpointStore: this.checkpointStore });
    const checkpoint = engine.start(initialState, tenant, runId);
    await this.checkpointStore.save(checkpoint);

    await this.db.insert(tasks).values({
      runId,
      graphId,
      tenantId: tenant.tenantId,
      sessionId: tenant.sessionId,
      kind: "start",
      status: "queued",
      maxAttempts: options.maxAttempts ?? 3,
      timeoutMs: options.timeoutMs ?? 30_000,
      priority: options.priority ?? 0,
    });
  }

  async enqueueResume(runId: string, resumeValue: NodeResumeValue, options: EnqueueOptions = {}): Promise<void> {
    const checkpoint = await this.checkpointStore.load(runId);
    if (!checkpoint) {
      throw new Error(`Cannot enqueue resume: no checkpoint found for run "${runId}"`);
    }
    if (checkpoint.status !== "paused") {
      throw new Error(`Cannot enqueue resume: run "${runId}" is not paused (status: "${checkpoint.status}")`);
    }
    await this.db.insert(tasks).values({
      runId,
      graphId: checkpoint.graphId,
      tenantId: checkpoint.tenantId,
      sessionId: checkpoint.sessionId,
      kind: "resume",
      resumeValue: resumeValue as object | undefined,
      status: "queued",
      maxAttempts: options.maxAttempts ?? 3,
      timeoutMs: options.timeoutMs ?? 30_000,
      priority: options.priority ?? 0,
    });
  }
}
```

- [ ] **Step 12: Run tests to verify they pass**

Run: `pnpm --filter @opentalos/scheduler test`
Expected: PASS — all 9 tests green (4 graph-registry + 5 enqueue).

- [ ] **Step 13: Create `packages/scheduler/src/index.ts`**

```ts
export { GraphRegistry, type GraphRegistration } from "./graph-registry.js";
export { Scheduler, type EnqueueOptions } from "./enqueue.js";
export { tasks } from "./schema.js";
```

- [ ] **Step 14: Rebuild and re-run tests, verify no test artifacts in dist/**

Run: `pnpm --filter @opentalos/scheduler build && pnpm --filter @opentalos/scheduler test && ls packages/scheduler/dist/`
Expected: PASS; `dist/` contains only `enqueue.{js,d.ts}`, `graph-registry.{js,d.ts}`, `index.{js,d.ts}`, `schema.{js,d.ts}` — no `.test.js` and no `test-db.{js,d.ts}` (excluded via tsconfig).

- [ ] **Step 15: Commit**

```bash
git add packages/scheduler pnpm-lock.yaml
git commit -m "feat(scheduler): add GraphRegistry and enqueueStart/enqueueResume"
```

---

## Task 4: `scheduler` Package — Worker (claim, execute, timeout, retry)

**Files:**
- Create: `packages/scheduler/src/worker.ts`
- Modify: `packages/scheduler/src/index.ts`
- Test: `packages/scheduler/src/worker.test.ts`

The worker's core correctness property is that claiming a task (the `SELECT ... FOR UPDATE SKIP LOCKED`) and marking it `running` must happen inside **one transaction**, so the row lock covers both the read and the write — otherwise two concurrent workers could both select the same row before either commits its claim.

`Worker.pollOnce()` claims a batch, then **awaits the full completion** of every task it claimed before returning. This makes the concurrency caps (`globalConcurrency`/`tenantConcurrency`) apply per poll cycle rather than continuously across overlapping cycles — a deliberate, documented simplification for this phase (see the design spec). It also makes `pollOnce()` a clean, deterministic unit to test directly, without needing artificial delays or polling loops in tests.

- [ ] **Step 1: Write the failing tests — `packages/scheduler/src/worker.test.ts`**

```ts
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

beforeEach(() => {
  executionCount = 0;
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

    // Simulate the backoff period elapsing, instead of really waiting for it.
    await db.update(tasks).set({ availableAt: new Date() }).where(eq(tasks.runId, "worker-fail-run"));
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --filter @opentalos/scheduler test -- worker`
Expected: FAIL — `Worker` is not defined.

- [ ] **Step 3: Implement `packages/scheduler/src/worker.ts`**

```ts
import { and, asc, desc, eq, lte } from "drizzle-orm";
import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import type { Pool } from "pg";
import { GraphEngine, type NodeResumeValue } from "@opentalos/core-graph";
import type { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import type { GraphRegistry } from "./graph-registry.js";
import { tasks } from "./schema.js";

type TaskRow = typeof tasks.$inferSelect;

export interface WorkerOptions {
  globalConcurrency: number;
  tenantConcurrency: number;
  pollIntervalMs?: number;
  batchSize?: number;
}

export class Worker {
  private readonly db: NodePgDatabase;
  private stopped = true;
  private pollTimer: ReturnType<typeof setTimeout> | undefined;

  constructor(
    private readonly pool: Pool,
    private readonly registry: GraphRegistry,
    private readonly checkpointStore: PostgresCheckpointStore,
    private readonly options: WorkerOptions,
  ) {
    this.db = drizzle(pool);
  }

  /** Starts continuous polling on a timer. Call stop() to end it. */
  start(): void {
    this.stopped = false;
    this.scheduleNextPoll(0);
  }

  stop(): void {
    this.stopped = true;
    if (this.pollTimer) clearTimeout(this.pollTimer);
  }

  private scheduleNextPoll(delayMs: number): void {
    if (this.stopped) return;
    this.pollTimer = setTimeout(() => {
      this.pollOnce()
        .catch(() => undefined)
        .finally(() => this.scheduleNextPoll(this.options.pollIntervalMs ?? 100));
    }, delayMs);
  }

  /**
   * Claims up to `batchSize` queued, due tasks (respecting global/tenant concurrency caps),
   * then runs all claimed tasks to completion before returning. Concurrency caps therefore
   * apply per poll cycle, not continuously across overlapping cycles — see the design spec
   * for why this simplification is acceptable for a single-process worker.
   */
  async pollOnce(): Promise<void> {
    const batchSize = this.options.batchSize ?? 10;
    const claimed = await this.db.transaction(async (tx) => {
      const candidates = await tx
        .select()
        .from(tasks)
        .where(and(eq(tasks.status, "queued"), lte(tasks.availableAt, new Date())))
        .orderBy(desc(tasks.priority), asc(tasks.createdAt))
        .limit(batchSize)
        .for("update", { skipLocked: true });

      const toRun: TaskRow[] = [];
      const tenantCounts = new Map<string, number>();
      for (const candidate of candidates) {
        if (toRun.length >= this.options.globalConcurrency) break;
        const tenantCount = tenantCounts.get(candidate.tenantId) ?? 0;
        if (tenantCount >= this.options.tenantConcurrency) continue;
        toRun.push(candidate);
        tenantCounts.set(candidate.tenantId, tenantCount + 1);
      }

      for (const candidate of toRun) {
        await tx.update(tasks).set({ status: "running", lockedAt: new Date() }).where(eq(tasks.id, candidate.id));
      }
      return toRun;
    });

    await Promise.all(claimed.map((task) => this.execute(task)));
  }

  private async execute(task: TaskRow): Promise<void> {
    try {
      await this.runWithTimeout(task);
      await this.db.update(tasks).set({ status: "done", updatedAt: new Date() }).where(eq(tasks.id, task.id));
    } catch (error) {
      const attempts = task.attempts + 1;
      if (attempts >= task.maxAttempts) {
        await this.db
          .update(tasks)
          .set({ status: "failed", attempts, error: errorMessage(error), updatedAt: new Date() })
          .where(eq(tasks.id, task.id));
      } else {
        const backoffMs = 2 ** attempts * 1000;
        await this.db
          .update(tasks)
          .set({
            status: "queued",
            attempts,
            error: errorMessage(error),
            availableAt: new Date(Date.now() + backoffMs),
            updatedAt: new Date(),
          })
          .where(eq(tasks.id, task.id));
      }
    }
  }

  private async runWithTimeout(task: TaskRow): Promise<void> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error(`Task ${task.id} timed out after ${task.timeoutMs}ms`)), task.timeoutMs);
    });
    try {
      await Promise.race([this.runTask(task), timeout]);
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  private async runTask(task: TaskRow): Promise<void> {
    const registration = this.registry.getOrThrow(task.graphId);
    const graph = registration.buildGraph();
    const deps = registration.buildDeps();
    const engine = new GraphEngine(graph, { ...deps, checkpointStore: this.checkpointStore });

    const checkpoint = await this.checkpointStore.load(task.runId);
    if (!checkpoint) {
      throw new Error(`No checkpoint found for run "${task.runId}"`);
    }

    if (task.kind === "start") {
      await engine.run(checkpoint);
      return;
    }
    await engine.resumeFromCheckpoint(checkpoint, task.resumeValue as NodeResumeValue);
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --filter @opentalos/scheduler test -- worker`
Expected: PASS — all 6 tests green. (These tests exercise real concurrent Postgres transactions and real timeouts — if any test is flaky, re-run once before investigating; if it fails consistently, the claiming transaction or timeout logic has a real bug, not a timing fluke.)

Note: the enqueue.test.ts suite has 5 tests (not 7, per Task 3's corrected count), so the running total after this task is 4 (graph-registry) + 5 (enqueue) + 6 (worker) = 15, not 17 — see Step 6 below.

- [ ] **Step 5: Update `packages/scheduler/src/index.ts`**

```ts
export { GraphRegistry, type GraphRegistration } from "./graph-registry.js";
export { Scheduler, type EnqueueOptions } from "./enqueue.js";
export { Worker, type WorkerOptions } from "./worker.js";
export { tasks } from "./schema.js";
```

- [ ] **Step 6: Rebuild and run the full package test suite**

Run: `pnpm --filter @opentalos/scheduler build && pnpm --filter @opentalos/scheduler test`
Expected: PASS — all 15 tests green (4 graph-registry + 5 enqueue + 6 worker).

- [ ] **Step 7: Commit**

```bash
git add packages/scheduler
git commit -m "feat(scheduler): add Worker with SKIP LOCKED claiming, concurrency caps, timeout, and retry backoff"
```

---

## Task 5: Cross-Instance Durable Resume — Capstone Integration Test

This is the test the design spec calls out explicitly: proving that a paused run started by one `Worker`/`GraphEngine` instance can be resumed to completion by a **completely separate** instance (a fresh `GraphRegistry`, re-registering the same graph from scratch) — simulating two different process lifetimes, not just two objects in the same test file sharing hidden state.

**Files:**
- Test: `packages/scheduler/src/cross-instance.test.ts`

- [ ] **Step 1: Write the test — `packages/scheduler/src/cross-instance.test.ts`**

```ts
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
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `pnpm --filter @opentalos/scheduler test -- cross-instance`
Expected: PASS — the single test green. If it fails, the bug is almost certainly in how `resumeFromCheckpoint` (Task 1) reconstructs state, or in how the worker loads the checkpoint before resuming (Task 4) — re-check those before assuming the test itself is wrong.

- [ ] **Step 3: Run the full package suite one more time**

Run: `pnpm --filter @opentalos/scheduler build && pnpm --filter @opentalos/scheduler test`
Expected: PASS — all 16 tests green (4 graph-registry + 5 enqueue + 6 worker + 1 cross-instance).

- [ ] **Step 4: Commit**

```bash
git add packages/scheduler
git commit -m "test(scheduler): add cross-instance capstone test proving durable resume across separate process instances"
```

---

## Final Verification

- [ ] Run `pnpm run build` from the repo root — expect PASS across every package (13 packages/examples now: the 11 + 1 example from the core engine plan, plus `postgres-checkpoint` and `scheduler`).
- [ ] Run `pnpm run typecheck` from the repo root — expect PASS, no type errors anywhere.
- [ ] Run `pnpm run test` from the repo root — expect PASS across every package (this will start and tear down several ephemeral Postgres containers via Docker; expect this run to take noticeably longer than the core-engine-only suite did).
- [ ] Re-read `docs/superpowers/specs/2026-09-09-task-scheduling-infrastructure-design.md` section by section and confirm: `resumeFromCheckpoint` exists and is tested (section 2), `postgres-checkpoint` is a real, tested `CheckpointStore` (section 4), the `scheduler` package enforces tenant/global concurrency caps and timeout/retry (section 5), and the cross-instance capstone test (section 7's explicit requirement) passes.
