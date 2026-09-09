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
  const nodeIds = new Set(Object.keys(config.nodes));

  // Catch config-authoring mistakes (typo'd node ids) here, at compile time, rather than
  // letting them surface later as an opaque "Unknown node" error from core-graph mid-run.
  if (!nodeIds.has(config.entryNode)) {
    throw new Error(`Unknown entryNode "${config.entryNode}": no node with that id is defined`);
  }

  const nodes: Record<string, NodeFn<TState>> = {};
  for (const [nodeId, ref] of Object.entries(config.nodes)) {
    const factory = nodeFactories[ref.use];
    if (!factory) {
      throw new Error(`Unknown node factory "${ref.use}" referenced by node "${nodeId}"`);
    }
    nodes[nodeId] = factory(ref.params);
  }

  const edges: EdgeDefinition<TState>[] = config.edges.map((edge) => {
    if (!nodeIds.has(edge.from)) {
      throw new Error(`Edge references unknown "from" node "${edge.from}"`);
    }
    const toIds = Array.isArray(edge.to) ? edge.to : [edge.to];
    for (const toId of toIds) {
      if (!nodeIds.has(toId)) {
        throw new Error(`Edge from "${edge.from}" references unknown "to" node "${toId}"`);
      }
    }
    if (edge.joinTo !== undefined) {
      // core-graph only reads `joinTo` when `to` is an array (fan-out); on a plain-string
      // `to` it's silently ignored, which is exactly the kind of copy-paste mistake (e.g.
      // converting a fan-out edge back to a single edge and forgetting to remove joinTo)
      // this compile step exists to catch instead of letting it silently do nothing.
      if (!Array.isArray(edge.to)) {
        throw new Error(
          `Edge from "${edge.from}" sets "joinTo" but "to" is not an array — joinTo only applies to fan-out edges`,
        );
      }
      if (!nodeIds.has(edge.joinTo)) {
        throw new Error(`Edge from "${edge.from}" references unknown "joinTo" node "${edge.joinTo}"`);
      }
    }
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
