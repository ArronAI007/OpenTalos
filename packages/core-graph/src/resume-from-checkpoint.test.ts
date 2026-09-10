import { describe, expect, it } from "vitest";
import type { TenantContext } from "@opentalos/core-types";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryToolRegistry } from "@opentalos/tool-registry";
import { GraphEngine } from "./engine.js";
import { shallowMergeReducer } from "./reducer.js";
import type { GraphDefinition, NodeFn } from "./types.js";

interface CounterState {
  count: number;
  approved?: boolean;
}

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

function makeDeps() {
  const toolRegistry = new InMemoryToolRegistry();
  toolRegistry.register({
    definition: { name: "increment", description: "returns +1", inputSchema: {} },
    async execute() {
      return { id: "tool-1", output: 1 };
    },
  });
  return { toolRegistry, eventBus: new InMemoryEventBus(), checkpointStore: new InMemoryCheckpointStore() };
}

describe("GraphEngine.resumeFromCheckpoint", () => {
  it("resumes a paused checkpoint on a brand-new engine instance (no in-memory generator)", async () => {
    const askApproval: NodeFn<CounterState> = async function* (state) {
      const resume = yield { type: "awaiting_approval", reason: "please confirm" };
      return { count: state.count + 1, approved: resume?.type === "approval" ? resume.approved : false };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g1",
      entryNode: "ask",
      nodes: { ask: askApproval },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engineA = new GraphEngine(graph, deps);
    let checkpoint = engineA.start({ count: 0 }, tenant, "run-1");
    checkpoint = await engineA.run(checkpoint);
    expect(checkpoint.status).toBe("paused");

    // A fresh GraphEngine instance, sharing only the checkpoint object and deps — simulating
    // a completely different process that has no knowledge of engineA's in-memory `paused` map.
    const engineB = new GraphEngine(graph, deps);
    const resumed = await engineB.resumeFromCheckpoint(checkpoint, { type: "approval", approved: true });
    expect(resumed.status).toBe("done");
    expect(resumed.state).toEqual({ count: 1, approved: true });
  });

  it("replays and re-resolves a tool call that happened before the approval yield", async () => {
    const callToolThenAsk: NodeFn<CounterState> = async function* (state) {
      const toolResume = yield { type: "awaiting_tool", toolCall: { id: "t1", name: "increment", input: {} } };
      const delta = toolResume?.type === "tool_result" ? (toolResume.result.output as number) : 0;
      const approvalResume = yield { type: "awaiting_approval", reason: "confirm the increment" };
      const approved = approvalResume?.type === "approval" ? approvalResume.approved : false;
      return { count: state.count + delta, approved };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g2",
      entryNode: "node",
      nodes: { node: callToolThenAsk },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engineA = new GraphEngine(graph, deps);
    let checkpoint = engineA.start({ count: 0 }, tenant, "run-2");
    checkpoint = await engineA.run(checkpoint);
    expect(checkpoint.status).toBe("paused");
    const eventsBeforeResume = deps.eventBus.getEvents().filter((e) => e.type === "tool_call_end").length;
    expect(eventsBeforeResume).toBe(1);

    const engineB = new GraphEngine(graph, deps);
    const resumed = await engineB.resumeFromCheckpoint(checkpoint, { type: "approval", approved: true });
    expect(resumed.status).toBe("done");
    expect(resumed.state).toEqual({ count: 1, approved: true });
    // Replay re-drives the node from the top, so the tool yield is auto-resolved a second time.
    const eventsAfterResume = deps.eventBus.getEvents().filter((e) => e.type === "tool_call_end").length;
    expect(eventsAfterResume).toBe(2);
  });

  it("pauses again (with a fresh reason) if the node yields a second approval during replay", async () => {
    const increment: NodeFn<CounterState> = async function* (state) {
      return { count: state.count + 1 };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g3",
      entryNode: "increment",
      nodes: { increment },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const alwaysRequireApproval = { check: async () => "require_approval" as const };
    const engineA = new GraphEngine(graph, { ...deps, guardrails: [alwaysRequireApproval] });
    let checkpoint = engineA.start({ count: 0 }, tenant, "run-3");
    checkpoint = await engineA.run(checkpoint); // before-phase pause

    const engineB = new GraphEngine(graph, { ...deps, guardrails: [alwaysRequireApproval] });
    const afterFirstResume = await engineB.resumeFromCheckpoint(checkpoint, { type: "approval", approved: true });
    expect(afterFirstResume.status).toBe("paused"); // after-phase pause, hit during replay

    const engineC = new GraphEngine(graph, { ...deps, guardrails: [alwaysRequireApproval] });
    const afterSecondResume = await engineC.resumeFromCheckpoint(afterFirstResume, { type: "approval", approved: true });
    expect(afterSecondResume.status).toBe("done");
    expect(afterSecondResume.state.count).toBe(1);
  });

  it("throws a clear error when the checkpoint is not paused", async () => {
    const increment: NodeFn<CounterState> = async function* (state) {
      return { count: state.count + 1 };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g4",
      entryNode: "increment",
      nodes: { increment },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engine = new GraphEngine(graph, deps);
    const doneCheckpoint = await engine.run(engine.start({ count: 0 }, tenant, "run-4"));
    expect(doneCheckpoint.status).toBe("done");

    await expect(engine.resumeFromCheckpoint(doneCheckpoint, { type: "approval", approved: true })).rejects.toThrow(
      /not in a resumable paused state/,
    );
  });

  it("throws a clear error when nodeCursor references an unknown node", async () => {
    const increment: NodeFn<CounterState> = async function* (state) {
      return { count: state.count + 1 };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g5",
      entryNode: "increment",
      nodes: { increment },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engine = new GraphEngine(graph, deps);
    let checkpoint = engine.start({ count: 0 }, tenant, "run-5");
    checkpoint = await engine.run(checkpoint);
    const corrupted = { ...checkpoint, status: "paused" as const, nodeCursor: "does-not-exist" };
    await expect(engine.resumeFromCheckpoint(corrupted, { type: "approval", approved: true })).rejects.toThrow(
      /Unknown node/,
    );
  });
});
