import { describe, expect, it } from "vitest";
import type { TenantContext } from "@opentalos/core-types";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryToolRegistry } from "@opentalos/tool-registry";
import { GraphEngine } from "./engine.js";
import { shallowMergeReducer } from "./reducer.js";
import type { GraphDefinition, NodeFn } from "./types.js";

interface FanState {
  a?: number;
  b?: number;
}

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

function makeDeps() {
  return {
    toolRegistry: new InMemoryToolRegistry(),
    eventBus: new InMemoryEventBus(),
    checkpointStore: new InMemoryCheckpointStore(),
  };
}

describe("GraphEngine — fan-out/fan-in", () => {
  it("runs branches concurrently and merges their partial state at the join node", async () => {
    const start: NodeFn<FanState> = async function* () {
      return {};
    };
    const branchA: NodeFn<FanState> = async function* () {
      return { a: 1 };
    };
    const branchB: NodeFn<FanState> = async function* () {
      return { b: 2 };
    };
    const join: NodeFn<FanState> = async function* () {
      return {};
    };
    const graph: GraphDefinition<FanState> = {
      id: "fan1",
      entryNode: "start",
      nodes: { start, branchA, branchB, join },
      edges: [{ from: "start", to: ["branchA", "branchB"], joinTo: "join" }],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engine = new GraphEngine(graph, deps);
    let checkpoint = engine.start({}, tenant, "fan-run-1");
    checkpoint = await engine.run(checkpoint);

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state).toEqual({ a: 1, b: 2 });
    const enters = deps.eventBus.getEvents().filter((e) => e.type === "node_enter").map((e) => e.payload?.nodeId);
    expect(enters).toContain("branchA");
    expect(enters).toContain("branchB");
  });

  it("rejects a branch that tries to await approval inside a fan-out wave", async () => {
    const start: NodeFn<FanState> = async function* () {
      return {};
    };
    const pausingBranch: NodeFn<FanState> = async function* () {
      yield { type: "awaiting_approval", reason: "not allowed here" };
      return { a: 1 };
    };
    const graph: GraphDefinition<FanState> = {
      id: "fan2",
      entryNode: "start",
      nodes: { start, pausingBranch },
      edges: [{ from: "start", to: ["pausingBranch"], joinTo: undefined }],
      reducer: shallowMergeReducer,
    };
    const engine = new GraphEngine(graph, makeDeps());
    const checkpoint = engine.start({}, tenant, "fan-run-2");
    await expect(engine.run(checkpoint)).rejects.toThrow(/not supported/);
  });
});
