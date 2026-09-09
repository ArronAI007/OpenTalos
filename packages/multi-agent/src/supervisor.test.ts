import { describe, expect, it } from "vitest";
import type { TenantContext } from "@opentalos/core-types";
import { GraphEngine } from "@opentalos/core-graph";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryToolRegistry } from "@opentalos/tool-registry";
import { buildSupervisorGraph } from "./supervisor.js";
import type { NodeFn } from "@opentalos/core-graph";

interface PlanState {
  plan: string[];
  cursor: number;
  results: string[];
}

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

function makeDeps() {
  return {
    toolRegistry: new InMemoryToolRegistry(),
    eventBus: new InMemoryEventBus(),
    checkpointStore: new InMemoryCheckpointStore(),
  };
}

describe("buildSupervisorGraph", () => {
  it("routes to each named agent in the order the route function returns, then finishes", async () => {
    const researcher: NodeFn<PlanState> = async function* (state) {
      return { results: [...state.results, "researched"], cursor: state.cursor + 1 };
    };
    const writer: NodeFn<PlanState> = async function* (state) {
      return { results: [...state.results, "written"], cursor: state.cursor + 1 };
    };

    const graph = buildSupervisorGraph<PlanState>({
      id: "plan-agent",
      agents: { researcher, writer },
      route: (state) => state.plan[state.cursor] ?? "DONE",
      reducer: (state, partial) => ({ ...state, ...partial }),
    });

    const engine = new GraphEngine(graph, makeDeps());
    let checkpoint = engine.start({ plan: ["researcher", "writer"], cursor: 0, results: [] }, tenant, "sup-run-1");
    checkpoint = await engine.run(checkpoint);

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.results).toEqual(["researched", "written"]);
  });
});
