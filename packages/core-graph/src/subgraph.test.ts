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

  it("invokes the same subgraph node repeatedly via a parent-graph loop without runId collisions", async () => {
    interface LoopState {
      total: number;
      iterations: number;
    }
    const double: NodeFn<ChildState> = async function* (state) {
      return { value: state.value * 2 };
    };
    const childGraph: GraphDefinition<ChildState> = {
      id: "child-loop",
      entryNode: "double",
      nodes: { double },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const subgraphNode = createSubgraphNode<LoopState, ChildState>(
      childGraph,
      deps,
      (parentState) => ({ value: parentState.total }),
      (childState) => ({ total: childState.value }),
    );
    const countIteration: NodeFn<LoopState> = async function* (state) {
      return { iterations: state.iterations + 1 };
    };
    const parentGraph: GraphDefinition<LoopState> = {
      id: "loop-parent",
      entryNode: "child",
      nodes: { child: subgraphNode, count: countIteration },
      edges: [
        { from: "child", to: "count" },
        { from: "count", to: "child", condition: (s) => s.iterations < 3 },
      ],
      reducer: shallowMergeReducer,
    };
    const engine = new GraphEngine(parentGraph, deps);
    let checkpoint = engine.start({ total: 1, iterations: 0 }, tenant, "loop-run-1");
    checkpoint = await engine.run(checkpoint);

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.total).toBe(8); // doubled 3 times
    expect(checkpoint.state.iterations).toBe(3);

    // Each of the 3 subgraph invocations must have persisted under its own distinct runId —
    // a collision in createSubgraphNode's runId scheme would silently overwrite one call's
    // checkpoint with another's.
    const childCheckpoints = (await deps.checkpointStore.list({})).filter((c) => c.graphId === "child-loop");
    const distinctRunIds = new Set(childCheckpoints.map((c) => c.runId));
    expect(distinctRunIds.size).toBe(3);
  });
});
