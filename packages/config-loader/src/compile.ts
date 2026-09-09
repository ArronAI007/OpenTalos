import type { EdgeDefinition, GraphDefinition, NodeFn } from "@opentalos/core-graph";
import type { GraphConfig } from "./schema.js";

export type NodeFactory<TState> = (params: Record<string, unknown> | undefined) => NodeFn<TState>;
export type ConditionFactory<TState> = (state: TState) => boolean;

export function compileGraphConfig<TState>(
  config: GraphConfig,
  nodeFactories: Record<string, NodeFactory<TState>>,
  conditionFactories: Record<string, ConditionFactory<TState>>,
  reducer: (state: TState, partial: Partial<TState>) => TState,
): GraphDefinition<TState> {
  const nodes: Record<string, NodeFn<TState>> = {};
  for (const [nodeId, ref] of Object.entries(config.nodes)) {
    const factory = nodeFactories[ref.use];
    if (!factory) {
      throw new Error(`Unknown node factory "${ref.use}" referenced by node "${nodeId}"`);
    }
    nodes[nodeId] = factory(ref.params);
  }

  const edges: EdgeDefinition<TState>[] = config.edges.map((edge) => {
    if (edge.when && !conditionFactories[edge.when]) {
      throw new Error(`Unknown condition factory "${edge.when}" referenced by edge from "${edge.from}"`);
    }
    return {
      from: edge.from,
      to: edge.to,
      joinTo: edge.joinTo,
      condition: edge.when ? conditionFactories[edge.when] : undefined,
    };
  });

  return { id: config.id, entryNode: config.entryNode, nodes, edges, reducer };
}
