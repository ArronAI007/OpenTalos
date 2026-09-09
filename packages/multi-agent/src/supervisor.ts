import type { EdgeDefinition, GraphDefinition, NodeFn } from "@opentalos/core-graph";
import { createRouterNode } from "./router-node.js";

export interface SupervisorConfig<TState> {
  id: string;
  agents: Record<string, NodeFn<TState>>;
  /** Reads state and returns the key of the agent to call next, or "DONE" to finish. */
  route: (state: TState) => string;
  reducer: (state: TState, partial: Partial<TState>) => TState;
}

export function buildSupervisorGraph<TState>(config: SupervisorConfig<TState>): GraphDefinition<TState> {
  const nodes: Record<string, NodeFn<TState>> = {
    router: createRouterNode<TState>(),
    done: createRouterNode<TState>(),
    ...config.agents,
  };

  const edges: EdgeDefinition<TState>[] = [];
  for (const agentKey of Object.keys(config.agents)) {
    edges.push({ from: "router", to: agentKey, condition: (state) => config.route(state) === agentKey });
    edges.push({ from: agentKey, to: "router" });
  }
  edges.push({ from: "router", to: "done", condition: (state) => config.route(state) === "DONE" });

  return { id: config.id, entryNode: "router", nodes, edges, reducer: config.reducer };
}
