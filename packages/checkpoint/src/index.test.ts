import { describe, expect, it } from "vitest";
import type { Checkpoint } from "@opentalos/core-types";
import { InMemoryCheckpointStore } from "./index.js";

function makeCheckpoint(overrides: Partial<Checkpoint> = {}): Checkpoint {
  return {
    graphId: "g1",
    runId: "run-1",
    tenantId: "tenant-a",
    sessionId: "session-1",
    nodeCursor: "start",
    state: {},
    pendingYields: [],
    status: "running",
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

describe("InMemoryCheckpointStore", () => {
  it("saves and loads a checkpoint by runId", async () => {
    const store = new InMemoryCheckpointStore();
    const checkpoint = makeCheckpoint();
    await store.save(checkpoint);
    await expect(store.load("run-1")).resolves.toEqual(checkpoint);
  });

  it("returns undefined for an unknown runId", async () => {
    const store = new InMemoryCheckpointStore();
    await expect(store.load("missing")).resolves.toBeUndefined();
  });

  it("overwrites a checkpoint saved again with the same runId", async () => {
    const store = new InMemoryCheckpointStore();
    await store.save(makeCheckpoint({ status: "running" }));
    await store.save(makeCheckpoint({ status: "done" }));
    const loaded = await store.load("run-1");
    expect(loaded?.status).toBe("done");
  });

  it("lists checkpoints filtered by tenantId and sessionId", async () => {
    const store = new InMemoryCheckpointStore();
    await store.save(makeCheckpoint({ runId: "run-1", tenantId: "tenant-a", sessionId: "s1" }));
    await store.save(makeCheckpoint({ runId: "run-2", tenantId: "tenant-b", sessionId: "s1" }));
    await store.save(makeCheckpoint({ runId: "run-3", tenantId: "tenant-a", sessionId: "s2" }));

    const tenantAOnly = await store.list({ tenantId: "tenant-a" });
    expect(tenantAOnly.map((c) => c.runId).sort()).toEqual(["run-1", "run-3"]);

    const tenantAAndSession1 = await store.list({ tenantId: "tenant-a", sessionId: "s1" });
    expect(tenantAAndSession1.map((c) => c.runId)).toEqual(["run-1"]);
  });
});
