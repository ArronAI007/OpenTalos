import { describe, expect, it } from "vitest";
import type { TenantContext } from "@opentalos/core-types";
import { GraphEngine, shallowMergeReducer, type NodeFn } from "@opentalos/core-graph";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryToolRegistry } from "@opentalos/tool-registry";
import { loadGraphConfig } from "./schema.js";
import { compileGraphConfig } from "./compile.js";

interface State {
  count: number;
}

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

describe("compileGraphConfig", () => {
  it("resolves node factories by name and builds a runnable GraphDefinition", async () => {
    const config = loadGraphConfig(`
id: counter
entryNode: tick
nodes:
  tick:
    use: incrementBy
    params:
      amount: 3
edges: []
`);
    const incrementByFactory = (params: Record<string, unknown> | undefined): NodeFn<State> => {
      const amount = (params?.amount as number) ?? 1;
      return async function* (state) {
        return { count: state.count + amount };
      };
    };

    const graph = compileGraphConfig<State>(config, { incrementBy: incrementByFactory }, {}, shallowMergeReducer);
    const engine = new GraphEngine(graph, {
      toolRegistry: new InMemoryToolRegistry(),
      eventBus: new InMemoryEventBus(),
      checkpointStore: new InMemoryCheckpointStore(),
    });
    let checkpoint = engine.start({ count: 0 }, tenant, "cfg-run-1");
    checkpoint = await engine.run(checkpoint);
    expect(checkpoint.state.count).toBe(3);
  });

  it("throws a clear error when a node references an unregistered factory", () => {
    const config = loadGraphConfig(`
id: bad
entryNode: n1
nodes:
  n1:
    use: doesNotExist
edges: []
`);
    expect(() => compileGraphConfig<State>(config, {}, {}, shallowMergeReducer)).toThrow(/doesNotExist/);
  });
});
