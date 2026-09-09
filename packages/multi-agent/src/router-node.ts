import type { NodeFn } from "@opentalos/core-graph";

/** A no-op node used purely as a routing/join point in generated graphs. */
export function createRouterNode<TState>(): NodeFn<TState> {
  return async function* router() {
    return {};
  };
}
