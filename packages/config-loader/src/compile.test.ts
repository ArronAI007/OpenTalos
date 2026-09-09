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

  it("throws a clear error when entryNode references an unknown node", () => {
    const config = loadGraphConfig(`
id: bad-entry
entryNode: missing
nodes:
  n1:
    use: noop
edges: []
`);
    const noopFactory = (): NodeFn<State> =>
      async function* () {
        return {};
      };
    expect(() => compileGraphConfig<State>(config, { noop: noopFactory }, {}, shallowMergeReducer)).toThrow(
      /entryNode "missing"/,
    );
  });

  it("throws a clear error when an edge references an unknown \"to\" node", () => {
    const config = loadGraphConfig(`
id: bad-edge
entryNode: n1
nodes:
  n1:
    use: noop
edges:
  - from: n1
    to: missingNode
`);
    const noopFactory = (): NodeFn<State> =>
      async function* () {
        return {};
      };
    expect(() => compileGraphConfig<State>(config, { noop: noopFactory }, {}, shallowMergeReducer)).toThrow(
      /missingNode/,
    );
  });

  it("throws when joinTo is set on a non-array \"to\" edge", () => {
    const config = loadGraphConfig(`
id: bad-jointo
entryNode: n1
nodes:
  n1:
    use: noop
  n2:
    use: noop
edges:
  - from: n1
    to: n2
    joinTo: n2
`);
    const noopFactory = (): NodeFn<State> =>
      async function* () {
        return {};
      };
    expect(() => compileGraphConfig<State>(config, { noop: noopFactory }, {}, shallowMergeReducer)).toThrow(
      /joinTo/,
    );
  });

  it("throws a clear error when an edge references an unregistered condition factory", () => {
    const config = loadGraphConfig(`
id: cond-bad
entryNode: n1
nodes:
  n1:
    use: noop
  n2:
    use: noop
edges:
  - from: n1
    to: n2
    when: missingCondition
`);
    const noopFactory = (): NodeFn<State> =>
      async function* () {
        return {};
      };
    expect(() => compileGraphConfig<State>(config, { noop: noopFactory }, {}, shallowMergeReducer)).toThrow(
      /missingCondition/,
    );
  });

  it("resolves a registered condition factory and uses it to gate edge traversal", async () => {
    interface CondState {
      value: number;
    }
    const config = loadGraphConfig(`
id: cond-good
entryNode: start
nodes:
  start:
    use: setFlag
  high:
    use: setHigh
  low:
    use: setLow
edges:
  - from: start
    to: high
    when: isHigh
  - from: start
    to: low
    when: isLow
`);
    const setFlag = (): NodeFn<CondState> =>
      async function* () {
        return { value: 5 };
      };
    const setHigh = (): NodeFn<CondState> =>
      async function* () {
        return { value: 100 };
      };
    const setLow = (): NodeFn<CondState> =>
      async function* () {
        return { value: -100 };
      };
    const graph = compileGraphConfig<CondState>(
      config,
      { setFlag, setHigh, setLow },
      { isHigh: (s) => s.value >= 5, isLow: (s) => s.value < 5 },
      shallowMergeReducer,
    );
    const engine = new GraphEngine(graph, {
      toolRegistry: new InMemoryToolRegistry(),
      eventBus: new InMemoryEventBus(),
      checkpointStore: new InMemoryCheckpointStore(),
    });
    let checkpoint = engine.start({ value: 0 }, tenant, "cfg-run-2");
    checkpoint = await engine.run(checkpoint);
    expect(checkpoint.state.value).toBe(100);
  });
});
