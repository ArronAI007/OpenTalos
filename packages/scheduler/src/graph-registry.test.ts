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
