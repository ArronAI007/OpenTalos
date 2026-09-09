import type { GraphDefinition, NodeFn } from "@opentalos/core-graph";
import { createRouterNode } from "./router-node.js";

export interface SwarmConfig<TState> {
  id: string;
  agents: Record<string, NodeFn<TState>>;
  reducer: (state: TState, partial: Partial<TState>) => TState;
}

export function buildSwarmGraph<TState>(config: SwarmConfig<TState>): GraphDefinition<TState> {
  const nodes: Record<string, NodeFn<TState>> = {
    start: createRouterNode<TState>(),
    join: createRouterNode<TState>(),
    ...config.agents,
  };
  return {
    id: config.id,
    entryNode: "start",
    nodes,
    edges: [{ from: "start", to: Object.keys(config.agents), joinTo: "join" }],
    reducer: config.reducer,
  };
}
