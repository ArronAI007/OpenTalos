import { describe, expect, it } from "vitest";
import type { TenantContext } from "@opentalos/core-types";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryToolRegistry } from "@opentalos/tool-registry";
import { GraphEngine } from "./engine.js";
import { shallowMergeReducer } from "./reducer.js";
import { createSubgraphNode } from "./subgraph.js";
import type { GraphDefinition, NodeFn } from "./types.js";

interface ParentState {
  total: number;
}
interface ChildState {
  value: number;
}

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

function makeDeps() {
  return {
    toolRegistry: new InMemoryToolRegistry(),
    eventBus: new InMemoryEventBus(),
    checkpointStore: new InMemoryCheckpointStore(),
  };
}

describe("createSubgraphNode", () => {
  it("runs a nested graph to completion inside a single parent node", async () => {
    const double: NodeFn<ChildState> = async function* (state) {
      return { value: state.value * 2 };
    };
    const childGraph: GraphDefinition<ChildState> = {
      id: "child",
      entryNode: "double",
      nodes: { double },
      edges: [],
      reducer: shallowMergeReducer,
    };

    const deps = makeDeps();
    const subgraphNode = createSubgraphNode<ParentState, ChildState>(
      childGraph,
      deps,
      (parentState) => ({ value: parentState.total }),
      (childState) => ({ total: childState.value }),
    );

    const parentGraph: GraphDefinition<ParentState> = {
      id: "parent",
      entryNode: "child",
      nodes: { child: subgraphNode },
      edges: [],
      reducer: shallowMergeReducer,
    };

    const engine = new GraphEngine(parentGraph, deps);
    let checkpoint = engine.start({ total: 5 }, tenant, "sub-run-1");
    checkpoint = await engine.run(checkpoint);

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.total).toBe(10);
  });

  it("throws when the nested subgraph pauses for approval", async () => {
    const pause: NodeFn<ChildState> = async function* () {
      yield { type: "awaiting_approval", reason: "child needs approval" };
      return {};
    };
    const childGraph: GraphDefinition<ChildState> = {
      id: "child2",
      entryNode: "pause",
      nodes: { pause },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const subgraphNode = createSubgraphNode<ParentState, ChildState>(
      childGraph,
      deps,
      (parentState) => ({ value: parentState.total }),
      (childState) => ({ total: childState.value }),
    );
    const parentGraph: GraphDefinition<ParentState> = {
      id: "parent2",
      entryNode: "child",
      nodes: { child: subgraphNode },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const engine = new GraphEngine(parentGraph, deps);
    const checkpoint = engine.start({ total: 1 }, tenant, "sub-run-2");
    await expect(engine.run(checkpoint)).rejects.toThrow(/not supported when nested/);
  });
});
