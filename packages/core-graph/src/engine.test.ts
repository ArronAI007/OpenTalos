import { describe, expect, it } from "vitest";
import type { Guardrail, TenantContext } from "@opentalos/core-types";
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
  const eventBus = new InMemoryEventBus();
  const checkpointStore = new InMemoryCheckpointStore();
  return { toolRegistry, eventBus, checkpointStore };
}

describe("GraphEngine — sequential execution", () => {
  it("runs a two-node sequential graph to completion", async () => {
    const increment: NodeFn<CounterState> = async function* (state) {
      return { count: state.count + 1 };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g1",
      entryNode: "a",
      nodes: { a: increment, b: increment },
      edges: [{ from: "a", to: "b" }],
      reducer: shallowMergeReducer,
    };
    const engine = new GraphEngine(graph, makeDeps());
    let checkpoint = engine.start({ count: 0 }, tenant, "run-1");
    checkpoint = await engine.run(checkpoint);
    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.count).toBe(2);
  });

  it("follows a conditional edge based on state", async () => {
    const setFlag: NodeFn<CounterState> = async function* () {
      return { count: 5 };
    };
    const high: NodeFn<CounterState> = async function* () {
      return { count: 100 };
    };
    const low: NodeFn<CounterState> = async function* () {
      return { count: -100 };
    };
    const start: NodeFn<CounterState> = setFlag;
    const graph: GraphDefinition<CounterState> = {
      id: "g2",
      entryNode: "start",
      nodes: { start, high, low },
      edges: [
        { from: "start", to: "high", condition: (s) => s.count >= 5 },
        { from: "start", to: "low", condition: (s) => s.count < 5 },
      ],
      reducer: shallowMergeReducer,
    };
    const engine = new GraphEngine(graph, makeDeps());
    let checkpoint = engine.start({ count: 0 }, tenant, "run-2");
    checkpoint = await engine.run(checkpoint);
    expect(checkpoint.state.count).toBe(100);
  });

  it("loops back to an earlier node until a condition is met", async () => {
    const tick: NodeFn<CounterState> = async function* (state) {
      return { count: state.count + 1 };
    };
    const done: NodeFn<CounterState> = async function* () {
      return {};
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g3",
      entryNode: "tick",
      nodes: { tick, done },
      edges: [
        { from: "tick", to: "tick", condition: (s) => s.count < 3 },
        { from: "tick", to: "done", condition: (s) => s.count >= 3 },
      ],
      reducer: shallowMergeReducer,
    };
    const engine = new GraphEngine(graph, makeDeps());
    let checkpoint = engine.start({ count: 0 }, tenant, "run-3");
    checkpoint = await engine.run(checkpoint);
    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.count).toBe(3);
  });

  it("auto-resolves an awaiting_tool yield via the injected ToolRegistry", async () => {
    const callTool: NodeFn<CounterState> = async function* (state) {
      const resume = yield { type: "awaiting_tool", toolCall: { id: "t1", name: "increment", input: {} } };
      const delta = resume?.type === "tool_result" ? (resume.result.output as number) : 0;
      return { count: state.count + delta };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g4",
      entryNode: "callTool",
      nodes: { callTool },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engine = new GraphEngine(graph, deps);
    let checkpoint = engine.start({ count: 0 }, tenant, "run-4");
    checkpoint = await engine.run(checkpoint);
    expect(checkpoint.state.count).toBe(1);
    expect(deps.eventBus.getEvents().map((e) => e.type)).toContain("tool_call_start");
    expect(deps.eventBus.getEvents().map((e) => e.type)).toContain("tool_call_end");
  });

  it("auto-resolves an emit yield by persisting a trace event and continuing without pausing", async () => {
    const streamText: NodeFn<CounterState> = async function* (state) {
      yield { type: "emit", eventType: "llm_call_start" };
      yield { type: "emit", eventType: "llm_text_delta", payload: { delta: "hi" } };
      yield { type: "emit", eventType: "llm_call_end" };
      return { count: state.count + 1 };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g4b",
      entryNode: "streamText",
      nodes: { streamText },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engine = new GraphEngine(graph, deps);
    let checkpoint = engine.start({ count: 0 }, tenant, "run-4b");
    checkpoint = await engine.run(checkpoint);

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.count).toBe(1);
    const deltaEvents = deps.eventBus.getEvents().filter((e) => e.type === "llm_text_delta");
    expect(deltaEvents).toHaveLength(1);
    expect(deltaEvents[0].payload).toEqual({ delta: "hi" });
    expect(deps.eventBus.getEvents().map((e) => e.type)).toContain("llm_call_start");
    expect(deps.eventBus.getEvents().map((e) => e.type)).toContain("llm_call_end");
  });

  it("pauses on an awaiting_approval yield and persists a paused checkpoint", async () => {
    const askApproval: NodeFn<CounterState> = async function* (state) {
      const resume = yield { type: "awaiting_approval", reason: "please confirm" };
      return { count: state.count + 1, approved: resume?.type === "approval" ? resume.approved : false };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g5",
      entryNode: "ask",
      nodes: { ask: askApproval },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engine = new GraphEngine(graph, deps);
    let checkpoint = engine.start({ count: 0 }, tenant, "run-5");
    checkpoint = await engine.run(checkpoint);

    expect(checkpoint.status).toBe("paused");
    expect(checkpoint.pendingYields).toEqual([{ type: "awaiting_approval", reason: "please confirm" }]);
    const persisted = await deps.checkpointStore.load("run-5");
    expect(persisted?.status).toBe("paused");

    checkpoint = await engine.resume(checkpoint, { type: "approval", approved: true });
    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state).toEqual({ count: 1, approved: true });
  });

  it("throws a clear error when resuming a run with no in-memory paused generator", async () => {
    const askApproval: NodeFn<CounterState> = async function* () {
      yield { type: "awaiting_approval", reason: "please confirm" };
      return {};
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g6",
      entryNode: "ask",
      nodes: { ask: askApproval },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engineA = new GraphEngine(graph, deps);
    let checkpoint = engineA.start({ count: 0 }, tenant, "run-6");
    checkpoint = await engineA.run(checkpoint);

    const engineB = new GraphEngine(graph, deps); // fresh engine instance, no in-memory generator
    await expect(engineB.resume(checkpoint, { type: "approval", approved: true })).rejects.toThrow(
      /Cross-process resume is not supported/,
    );
  });

  it("wraps a thrown error as NodeError, emits an error trace event, and propagates it", async () => {
    const explode: NodeFn<CounterState> = async function* () {
      throw new Error("boom");
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g7",
      entryNode: "explode",
      nodes: { explode },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engine = new GraphEngine(graph, deps);
    const checkpoint = engine.start({ count: 0 }, tenant, "run-7");
    await expect(engine.run(checkpoint)).rejects.toThrow(/Node "explode" failed: boom/);
    const errorEvents = deps.eventBus.getEvents().filter((e) => e.type === "error");
    expect(errorEvents).toHaveLength(1);
    expect(errorEvents[0].payload?.nodeId).toBe("explode");
  });

  it("blocks a node before execution when a guardrail decision is 'block'", async () => {
    const increment: NodeFn<CounterState> = async function* (state) {
      return { count: state.count + 1 };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g8",
      entryNode: "increment",
      nodes: { increment },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const blockingGuardrail: Guardrail = {
      async check() {
        return "block";
      },
    };
    const deps = { ...makeDeps(), guardrails: [blockingGuardrail] };
    const engine = new GraphEngine(graph, deps);
    const checkpoint = engine.start({ count: 0 }, tenant, "run-8");
    await expect(engine.run(checkpoint)).rejects.toThrow(/Guardrail blocked node "increment"/);
  });

  it("pauses for approval when a guardrail requires it, then proceeds or fails based on the decision", async () => {
    const increment: NodeFn<CounterState> = async function* (state) {
      return { count: state.count + 1 };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g9",
      entryNode: "increment",
      nodes: { increment },
      edges: [],
      reducer: shallowMergeReducer,
    };
    // Requires approval on BOTH the "before" and "after" guardrail phases, exercising the
    // engine's support for a node pausing more than once within a single logical execution
    // (resume() can itself pause again — see engine.ts).
    const approvalGuardrail: Guardrail = {
      async check() {
        return "require_approval";
      },
    };

    const depsApproved = { ...makeDeps(), guardrails: [approvalGuardrail] };
    const engineApproved = new GraphEngine(graph, depsApproved);
    let approvedCheckpoint = engineApproved.start({ count: 0 }, tenant, "run-9a");
    approvedCheckpoint = await engineApproved.run(approvedCheckpoint);
    expect(approvedCheckpoint.status).toBe("paused"); // before-phase pause

    approvedCheckpoint = await engineApproved.resume(approvedCheckpoint, { type: "approval", approved: true });
    expect(approvedCheckpoint.status).toBe("paused"); // after-phase pause; node body already ran

    approvedCheckpoint = await engineApproved.resume(approvedCheckpoint, { type: "approval", approved: true });
    expect(approvedCheckpoint.status).toBe("done");
    expect(approvedCheckpoint.state.count).toBe(1);

    const depsDenied = { ...makeDeps(), guardrails: [approvalGuardrail] };
    const engineDenied = new GraphEngine(graph, depsDenied);
    let deniedCheckpoint = engineDenied.start({ count: 0 }, tenant, "run-9b");
    deniedCheckpoint = await engineDenied.run(deniedCheckpoint);
    await expect(engineDenied.resume(deniedCheckpoint, { type: "approval", approved: false })).rejects.toThrow(
      /Guardrail approval was denied/,
    );
  });

  it("refuses to resume a paused run under a different tenant/session than it was paused with", async () => {
    const askApproval: NodeFn<CounterState> = async function* () {
      yield { type: "awaiting_approval", reason: "please confirm" };
      return {};
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g10",
      entryNode: "ask",
      nodes: { ask: askApproval },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engine = new GraphEngine(graph, deps);
    let checkpoint = engine.start({ count: 0 }, tenant, "run-10");
    checkpoint = await engine.run(checkpoint);

    const spoofedCheckpoint = { ...checkpoint, tenantId: "tenant-b" };
    await expect(engine.resume(spoofedCheckpoint, { type: "approval", approved: true })).rejects.toThrow(
      /different tenant\/session/,
    );
  });

  it("passes the node's output to an \"after\" phase guardrail so it can validate results", async () => {
    const produceBad: NodeFn<CounterState> = async function* () {
      return { count: 999 };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g11",
      entryNode: "produce",
      nodes: { produce: produceBad },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const outputCheckingGuardrail: Guardrail = {
      async check(input) {
        if (input.phase === "after" && (input.output as Partial<CounterState> | undefined)?.count === 999) {
          return "block";
        }
        return "allow";
      },
    };
    const deps = { ...makeDeps(), guardrails: [outputCheckingGuardrail] };
    const engine = new GraphEngine(graph, deps);
    const checkpoint = engine.start({ count: 0 }, tenant, "run-11");
    await expect(engine.run(checkpoint)).rejects.toThrow(/Guardrail blocked node "produce" after execution/);
  });

  it("runs two tenants' graphs concurrently on one shared engine instance without cross-contamination", async () => {
    const tick: NodeFn<CounterState> = async function* (state) {
      return { count: state.count + 1 };
    };
    const done: NodeFn<CounterState> = async function* () {
      return {};
    };
    const graph: GraphDefinition<CounterState> = {
      id: "concurrent-g",
      entryNode: "tick",
      nodes: { tick, done },
      edges: [
        { from: "tick", to: "tick", condition: (s) => s.count % 100 < 5 },
        { from: "tick", to: "done", condition: (s) => s.count % 100 >= 5 },
      ],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engine = new GraphEngine(graph, deps);
    const tenantA: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };
    const tenantB: TenantContext = { tenantId: "tenant-b", sessionId: "session-1" };

    const [resultA, resultB] = await Promise.all([
      engine.run(engine.start({ count: 0 }, tenantA, "concurrent-run-a")),
      engine.run(engine.start({ count: 100 }, tenantB, "concurrent-run-b")),
    ]);

    expect(resultA.status).toBe("done");
    expect(resultA.state.count).toBe(5);
    expect(resultA.tenantId).toBe("tenant-a");

    expect(resultB.status).toBe("done");
    expect(resultB.state.count).toBe(105);
    expect(resultB.tenantId).toBe("tenant-b");

    const persistedA = await deps.checkpointStore.load("concurrent-run-a");
    const persistedB = await deps.checkpointStore.load("concurrent-run-b");
    expect(persistedA?.tenantId).toBe("tenant-a");
    expect(persistedA?.state).toEqual({ count: 5 });
    expect(persistedB?.tenantId).toBe("tenant-b");
    expect(persistedB?.state).toEqual({ count: 105 });
  });
});
