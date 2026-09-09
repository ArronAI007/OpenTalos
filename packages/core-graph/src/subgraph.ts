import { GraphEngine, type EngineDeps } from "./engine.js";
import type { GraphDefinition, NodeFn } from "./types.js";

/**
 * `deps` is shared as-is with the child engine, which has two consequences worth knowing:
 * - Guardrails match by nodeId only (see engine.ts's wrapWithGuardrails), so a guardrail
 *   configured for a nodeId in the parent graph will also apply if the child graph happens
 *   to reuse that same nodeId — since subgraphs can't handle pauses, this surfaces as the
 *   "not supported when nested" throw below, which can be confusing to debug if the real
 *   cause is an unrelated guardrail rather than the child's own logic.
 * - Every subgraph invocation persists its own checkpoints to the shared checkpointStore
 *   under a synthetic runId that's never queried again once the subgraph completes — for
 *   the in-memory store used in this phase that's harmless, but a real persistent store
 *   would accumulate orphaned rows for each subgraph call (more so inside a loop or a
 *   fan-out branch). Acceptable for now; worth revisiting when a real CheckpointStore lands.
 */
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
