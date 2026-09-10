import { describe, expect, it } from "vitest";
import { initialTraceTimelineState, traceTimelineReducer } from "./trace-reducer.js";
import type { TraceEventDto } from "../types.js";

const sampleEvent: TraceEventDto = {
  id: 1,
  type: "node_enter",
  runId: "r1",
  tenantId: "t1",
  sessionId: "s1",
  timestamp: "2026-01-01T00:00:00.000Z",
};

describe("traceTimelineReducer", () => {
  it("appends a trace event without mutating the previous state", () => {
    const next = traceTimelineReducer(initialTraceTimelineState, { kind: "trace", event: sampleEvent });
    expect(next.events).toEqual([sampleEvent]);
    expect(initialTraceTimelineState.events).toEqual([]);
  });

  it("updates status without touching accumulated events", () => {
    const withEvent = traceTimelineReducer(initialTraceTimelineState, { kind: "trace", event: sampleEvent });
    const next = traceTimelineReducer(withEvent, { kind: "status", status: "paused" });
    expect(next.status).toBe("paused");
    expect(next.events).toEqual([sampleEvent]);
  });

  it("appends multiple events in order", () => {
    let state = initialTraceTimelineState;
    state = traceTimelineReducer(state, { kind: "trace", event: sampleEvent });
    state = traceTimelineReducer(state, {
      kind: "trace",
      event: { ...sampleEvent, id: 2, type: "tool_call_start" },
    });
    expect(state.events.map((e) => e.type)).toEqual(["node_enter", "tool_call_start"]);
  });

  it("records the final state payload when the run completes", () => {
    const next = traceTimelineReducer(initialTraceTimelineState, { kind: "final", state: { reply: "done" } });
    expect(next.finalState).toEqual({ reply: "done" });
  });
});
