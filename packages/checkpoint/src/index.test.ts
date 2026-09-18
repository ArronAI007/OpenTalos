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
    cancelRequested: false,
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

  it("requestCancel sets cancelRequested on an existing checkpoint", async () => {
    const store = new InMemoryCheckpointStore();
    await store.save(makeCheckpoint({ runId: "run-cancel" }));
    await store.requestCancel("run-cancel");
    const loaded = await store.load("run-cancel");
    expect(loaded?.cancelRequested).toBe(true);
  });

  it("requestCancel on an unknown runId is a silent no-op", async () => {
    const store = new InMemoryCheckpointStore();
    await expect(store.requestCancel("does-not-exist")).resolves.toBeUndefined();
  });

  it("a later save() with a stale cancelRequested: false does not clobber a concurrent requestCancel()", async () => {
    const store = new InMemoryCheckpointStore();
    await store.save(makeCheckpoint({ runId: "run-race", cancelRequested: false }));
    await store.requestCancel("run-race");

    // Simulate the engine's own next node-boundary save() call, still carrying the OLD in-memory
    // checkpoint object from before requestCancel() was called (cancelRequested: false).
    await store.save(makeCheckpoint({ runId: "run-race", status: "running", cancelRequested: false }));

    const loaded = await store.load("run-race");
    expect(loaded?.cancelRequested).toBe(true);
  });

  it("requestSteer sets steerMessage on an existing checkpoint", async () => {
    const store = new InMemoryCheckpointStore();
    await store.save(makeCheckpoint({ runId: "run-steer" }));
    await store.requestSteer("run-steer", "turn left instead");
    const loaded = await store.load("run-steer");
    expect(loaded?.steerMessage).toBe("turn left instead");
  });

  it("requestSteer on an unknown runId is a silent no-op", async () => {
    const store = new InMemoryCheckpointStore();
    await expect(store.requestSteer("does-not-exist", "hi")).resolves.toBeUndefined();
  });

  it("clearSteerMessage resets steerMessage back to undefined", async () => {
    const store = new InMemoryCheckpointStore();
    await store.save(makeCheckpoint({ runId: "run-clear-steer" }));
    await store.requestSteer("run-clear-steer", "turn left instead");
    await store.clearSteerMessage("run-clear-steer");
    const loaded = await store.load("run-clear-steer");
    expect(loaded?.steerMessage).toBeUndefined();
  });

  it("a later save() with a stale steerMessage does not clobber a concurrent requestSteer()", async () => {
    const store = new InMemoryCheckpointStore();
    await store.save(makeCheckpoint({ runId: "run-steer-race" }));
    await store.requestSteer("run-steer-race", "turn left instead");

    // Simulate the engine's own next node-boundary save() call, still carrying the OLD in-memory
    // checkpoint object from before requestSteer() was called (steerMessage: undefined).
    await store.save(makeCheckpoint({ runId: "run-steer-race", status: "running" }));

    const loaded = await store.load("run-steer-race");
    expect(loaded?.steerMessage).toBe("turn left instead");
  });

  it("does not let a later, orphaned save() downgrade an already-'failed' checkpoint", async () => {
    const store = new InMemoryCheckpointStore();
    // Worker.execute()'s final-failure branch records the terminal failure first.
    await store.save(makeCheckpoint({ runId: "run-orphan-timeout", status: "failed", error: "boom" }));

    // Simulate the orphaned, still-in-flight node execution from runWithTimeout()'s race: its
    // abort-aware node body finished normally (rather than throwing) after the timeout already
    // fired, so GraphEngine's ordinary completeNode() path calls save() with a perfectly normal,
    // stale, non-failed checkpoint arriving AFTER the authoritative failure.
    await store.save(makeCheckpoint({ runId: "run-orphan-timeout", status: "done", error: undefined }));

    const loaded = await store.load("run-orphan-timeout");
    expect(loaded?.status).toBe("failed");
    expect(loaded?.error).toBe("boom");
  });

  it("still allows a legitimate 'failed' -> 'failed' re-save (same information saved twice)", async () => {
    const store = new InMemoryCheckpointStore();
    await store.save(makeCheckpoint({ runId: "run-refail", status: "failed", error: "boom" }));
    await store.save(makeCheckpoint({ runId: "run-refail", status: "failed", error: "boom" }));
    const loaded = await store.load("run-refail");
    expect(loaded?.status).toBe("failed");
    expect(loaded?.error).toBe("boom");
  });

  it("still allows a save() whose incoming status IS 'failed' to overwrite an existing 'failed' checkpoint (a legitimate terminal write, e.g. an updated error message)", async () => {
    const store = new InMemoryCheckpointStore();
    await store.save(makeCheckpoint({ runId: "run-refail-2", status: "failed", error: "first error" }));
    await store.save(makeCheckpoint({ runId: "run-refail-2", status: "failed", error: "second error" }));
    const loaded = await store.load("run-refail-2");
    expect(loaded?.status).toBe("failed");
    expect(loaded?.error).toBe("second error");
  });

  it("loadForTenant returns the checkpoint when tenantId matches", async () => {
    const store = new InMemoryCheckpointStore();
    await store.save(makeCheckpoint({ runId: "run-tenant-match", tenantId: "tenant-a" }));
    const loaded = await store.loadForTenant("run-tenant-match", "tenant-a");
    expect(loaded?.runId).toBe("run-tenant-match");
  });

  it("loadForTenant returns undefined when tenantId does not match", async () => {
    const store = new InMemoryCheckpointStore();
    await store.save(makeCheckpoint({ runId: "run-tenant-mismatch", tenantId: "tenant-a" }));
    await expect(store.loadForTenant("run-tenant-mismatch", "tenant-b")).resolves.toBeUndefined();
  });

  it("loadForTenant returns undefined for an unknown runId regardless of tenantId", async () => {
    const store = new InMemoryCheckpointStore();
    await expect(store.loadForTenant("missing", "tenant-a")).resolves.toBeUndefined();
  });

  it("requestCancelForTenant sets cancelRequested only when tenantId matches", async () => {
    const store = new InMemoryCheckpointStore();
    await store.save(makeCheckpoint({ runId: "run-cancel-tenant", tenantId: "tenant-a" }));

    await store.requestCancelForTenant("run-cancel-tenant", "tenant-b");
    expect((await store.load("run-cancel-tenant"))?.cancelRequested).toBe(false);

    await store.requestCancelForTenant("run-cancel-tenant", "tenant-a");
    expect((await store.load("run-cancel-tenant"))?.cancelRequested).toBe(true);
  });

  it("requestSteerForTenant sets steerMessage only when tenantId matches", async () => {
    const store = new InMemoryCheckpointStore();
    await store.save(makeCheckpoint({ runId: "run-steer-tenant", tenantId: "tenant-a" }));

    await store.requestSteerForTenant("run-steer-tenant", "turn left", "tenant-b");
    expect((await store.load("run-steer-tenant"))?.steerMessage).toBeUndefined();

    await store.requestSteerForTenant("run-steer-tenant", "turn left", "tenant-a");
    expect((await store.load("run-steer-tenant"))?.steerMessage).toBe("turn left");
  });

  it("clearSteerMessageForTenant clears steerMessage only when tenantId matches", async () => {
    const store = new InMemoryCheckpointStore();
    await store.save(makeCheckpoint({ runId: "run-clear-tenant", tenantId: "tenant-a" }));
    await store.requestSteer("run-clear-tenant", "turn left");

    await store.clearSteerMessageForTenant("run-clear-tenant", "tenant-b");
    expect((await store.load("run-clear-tenant"))?.steerMessage).toBe("turn left");

    await store.clearSteerMessageForTenant("run-clear-tenant", "tenant-a");
    expect((await store.load("run-clear-tenant"))?.steerMessage).toBeUndefined();
  });
});
