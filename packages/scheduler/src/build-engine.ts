import { GraphEngine } from "@opentalos/core-graph";
import type { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import type { GraphRegistry } from "./graph-registry.js";

/**
 * Looks up a graphId's registration, rebuilds its GraphDefinition + deps, and constructs a
 * ready-to-use GraphEngine with the scheduler's PostgresCheckpointStore injected. Shared by
 * enqueueStart (enqueue.ts) and runTask (worker.ts), which both need to go from a bare graphId
 * string to an executable engine.
 */
export function buildEngine(registry: GraphRegistry, checkpointStore: PostgresCheckpointStore, graphId: string): GraphEngine<unknown> {
  const registration = registry.getOrThrow(graphId);
  const graph = registration.buildGraph();
  const deps = registration.buildDeps();
  return new GraphEngine(graph, { ...deps, checkpointStore });
}
