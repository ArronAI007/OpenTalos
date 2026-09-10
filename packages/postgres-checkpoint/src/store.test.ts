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
