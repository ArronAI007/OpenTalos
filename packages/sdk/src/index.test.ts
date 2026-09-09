import { describe, expect, it } from "vitest";
import type { TenantContext } from "@opentalos/core-types";
import type { NodeFn } from "@opentalos/core-graph";
import { createEngine, defineGraph } from "./index.js";

interface State {
  count: number;
}

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

describe("sdk", () => {
  it("defineGraph fills in a default shallow-merge reducer when none is given", async () => {
    const increment: NodeFn<State> = async function* (state) {
      return { count: state.count + 1 };
    };
    const graph = defineGraph<State>({ id: "g1", entryNode: "inc", nodes: { inc: increment }, edges: [] });
    const engine = createEngine(graph);
    let checkpoint = engine.start({ count: 0 }, tenant, "sdk-run-1");
    checkpoint = await engine.run(checkpoint);
    expect(checkpoint.state.count).toBe(1);
  });

  it("createEngine wires in-memory defaults for tool registry, event bus, and checkpoint store", async () => {
    const graph = defineGraph<State>({
      id: "g2",
      entryNode: "inc",
      nodes: {
        inc: async function* (state) {
          return { count: state.count + 1 };
        },
      },
      edges: [],
    });
    const engine = createEngine(graph);
    let checkpoint = engine.start({ count: 0 }, tenant, "sdk-run-2");
    checkpoint = await engine.run(checkpoint);
    expect(checkpoint.status).toBe("done");
  });
});
