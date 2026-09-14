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
      cancel_requested BOOLEAN NOT NULL DEFAULT false,
      error TEXT,
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
    cancelRequested: false,
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

  it("requestCancel sets cancel_requested without disturbing other columns", async () => {
    await store.save(makeCheckpoint({ runId: "run-cancel-pg", state: { count: 1 } }));
    await store.requestCancel("run-cancel-pg");
    const loaded = await store.load("run-cancel-pg");
    expect(loaded?.cancelRequested).toBe(true);
    expect(loaded?.state).toEqual({ count: 1 });
    expect(loaded?.status).toBe("running");
  });

  it("a later save() with a stale cancelRequested: false does not clobber a concurrent requestCancel()", async () => {
    await store.save(makeCheckpoint({ runId: "run-cancel-race-pg", cancelRequested: false }));
    await store.requestCancel("run-cancel-race-pg");

    // Simulate the engine's own next node-boundary save() call, still carrying the OLD in-memory
    // checkpoint object from before requestCancel() flipped the DB row (cancelRequested: false).
    await store.save(makeCheckpoint({ runId: "run-cancel-race-pg", status: "running", cancelRequested: false }));

    const loaded = await store.load("run-cancel-race-pg");
    expect(loaded?.cancelRequested).toBe(true);
  });

  it("round-trips status: 'failed' and an error message through save()/load()", async () => {
    const checkpoint = makeCheckpoint({
      runId: "run-failed",
      status: "failed",
      error: "some message",
    });
    await store.save(checkpoint);
    const loaded = await store.load("run-failed");
    expect(loaded?.status).toBe("failed");
    expect(loaded?.error).toBe("some message");
  });

  it("does not let a later, orphaned save() downgrade an already-'failed' checkpoint", async () => {
    // Worker.execute()'s final-failure branch records the terminal failure first.
    await store.save(makeCheckpoint({ runId: "run-orphan-timeout-pg", status: "failed", error: "boom" }));

    // Simulate the orphaned, still-in-flight node execution from runWithTimeout()'s race: its
    // abort-aware node body finished normally (rather than throwing) after the timeout already
    // fired, so GraphEngine's ordinary completeNode() path calls save() with a perfectly normal,
    // stale, non-failed checkpoint arriving AFTER the authoritative failure.
    await store.save(makeCheckpoint({ runId: "run-orphan-timeout-pg", status: "done", error: undefined }));

    const loaded = await store.load("run-orphan-timeout-pg");
    expect(loaded?.status).toBe("failed");
    expect(loaded?.error).toBe("boom");
  });

  it("still allows a legitimate 'failed' -> 'failed' re-save (same information saved twice)", async () => {
    await store.save(makeCheckpoint({ runId: "run-refail-pg", status: "failed", error: "boom" }));
    await store.save(makeCheckpoint({ runId: "run-refail-pg", status: "failed", error: "boom" }));
    const loaded = await store.load("run-refail-pg");
    expect(loaded?.status).toBe("failed");
    expect(loaded?.error).toBe("boom");
  });

  it("still allows a save() whose incoming status IS 'failed' to overwrite an existing 'failed' checkpoint (a legitimate terminal write, e.g. an updated error message)", async () => {
    await store.save(makeCheckpoint({ runId: "run-refail-2-pg", status: "failed", error: "first error" }));
    await store.save(makeCheckpoint({ runId: "run-refail-2-pg", status: "failed", error: "second error" }));
    const loaded = await store.load("run-refail-2-pg");
    expect(loaded?.status).toBe("failed");
    expect(loaded?.error).toBe("second error");
  });
});
