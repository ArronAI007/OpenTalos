import type { EdgeDefinition, GraphDefinition, NodeFn } from "@opentalos/core-graph";
import { createRouterNode } from "./router-node.js";

export interface SupervisorConfig<TState> {
  id: string;
  agents: Record<string, NodeFn<TState>>;
  /**
   * Reads state and returns the key of the agent to call next, or "DONE" to finish.
   * Must be a cheap, pure, deterministic function of state — it may be called more than
   * once per hop (once by the router node's validation check, once per edge condition
   * evaluated during routing). Do not perform I/O or expensive computation here; if a
   * decision requires an LLM call, do that inside an agent node and have route() merely
   * read the field that node already wrote into state (as the research-agent example does).
   */
  route: (state: TState) => string;
  reducer: (state: TState, partial: Partial<TState>) => TState;
}

export function buildSupervisorGraph<TState>(config: SupervisorConfig<TState>): GraphDefinition<TState> {
  // "DONE" is a reserved sentinel meaning "finish" — an agent using that name would collide
  // with the router->done edge below (edges are matched in array order, and the agent's own
  // router->agentKey edge would always win first), silently breaking termination.
  if ("DONE" in config.agents) {
    throw new Error('buildSupervisorGraph: an agent cannot be named "DONE" — that name is reserved to signal completion');
  }
  const agentKeys = new Set(Object.keys(config.agents));

  // A bespoke router (rather than the generic createRouterNode) so a typo'd/unrecognized
  // route() return value fails loudly instead of silently completing the run — completeNode
  // treats "no matching edge" as normal completion, which is indistinguishable from an actual
  // typo'd route() value unless this node validates it first.
  const router: NodeFn<TState> = async function* routerNode(state) {
    const next = config.route(state);
    if (next !== "DONE" && !agentKeys.has(next)) {
      throw new Error(
        `buildSupervisorGraph: route() returned "${next}", which is neither a known agent key (${[...agentKeys].join(", ")}) nor "DONE"`,
      );
    }
    return {};
  };

  const nodes: Record<string, NodeFn<TState>> = {
    router,
    done: createRouterNode<TState>(),
    ...config.agents,
  };

  const edges: EdgeDefinition<TState>[] = [];
  for (const agentKey of agentKeys) {
    edges.push({ from: "router", to: agentKey, condition: (state) => config.route(state) === agentKey });
    edges.push({ from: agentKey, to: "router" });
  }
  edges.push({ from: "router", to: "done", condition: (state) => config.route(state) === "DONE" });

  return { id: config.id, entryNode: "router", nodes, edges, reducer: config.reducer };
}
