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

  it("reaches done immediately when route returns DONE with no agents dispatched", async () => {
    const researcher: NodeFn<PlanState> = async function* (state) {
      return { results: [...state.results, "researched"], cursor: state.cursor + 1 };
    };
    const graph = buildSupervisorGraph<PlanState>({
      id: "empty-plan-agent",
      agents: { researcher },
      route: (state) => state.plan[state.cursor] ?? "DONE",
      reducer: (state, partial) => ({ ...state, ...partial }),
    });
    const engine = new GraphEngine(graph, makeDeps());
    let checkpoint = engine.start({ plan: [], cursor: 0, results: [] }, tenant, "sup-run-2");
    checkpoint = await engine.run(checkpoint);
    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.results).toEqual([]);
  });

  it('throws at construction time if an agent is named "DONE"', () => {
    const noop: NodeFn<PlanState> = async function* () {
      return {};
    };
    expect(() =>
      buildSupervisorGraph<PlanState>({
        id: "bad-agent",
        agents: { DONE: noop },
        route: () => "DONE",
        reducer: (state, partial) => ({ ...state, ...partial }),
      }),
    ).toThrow(/reserved/);
  });

  it("throws when route() returns a value that matches no agent and isn't DONE", async () => {
    const researcher: NodeFn<PlanState> = async function* (state) {
      return { results: [...state.results, "researched"], cursor: state.cursor + 1 };
    };
    const graph = buildSupervisorGraph<PlanState>({
      id: "bad-route-agent",
      agents: { researcher },
      route: () => "not-a-real-agent",
      reducer: (state, partial) => ({ ...state, ...partial }),
    });
    const engine = new GraphEngine(graph, makeDeps());
    const checkpoint = engine.start({ plan: [], cursor: 0, results: [] }, tenant, "sup-run-3");
    await expect(engine.run(checkpoint)).rejects.toThrow(/not-a-real-agent/);
  });
});
