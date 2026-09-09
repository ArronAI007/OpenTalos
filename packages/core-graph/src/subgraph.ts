import { GraphEngine, type EngineDeps } from "./engine.js";
import type { GraphDefinition, NodeFn } from "./types.js";

export function createSubgraphNode<TState, TSub>(
  childGraph: GraphDefinition<TSub>,
  deps: EngineDeps,
  toChildState: (state: TState) => TSub,
  fromChildState: (childState: TSub, parentState: TState) => Partial<TState>,
): NodeFn<TState> {
  return async function* subgraphNode(state, ctx) {
    const engine = new GraphEngine(childGraph, deps);
    const runId = `${ctx.tenant.sessionId}:${childGraph.id}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
    let checkpoint = engine.start(toChildState(state), ctx.tenant, runId);
    checkpoint = await engine.run(checkpoint);
    if (checkpoint.status === "paused") {
      throw new Error(
        `Subgraph "${childGraph.id}" paused for approval, which is not supported when nested inside a parent graph in this version`,
      );
    }
    return fromChildState(checkpoint.state, state);
  };
}
