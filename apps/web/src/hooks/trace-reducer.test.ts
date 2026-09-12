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

  it("accumulates llm_text_delta payloads into streamingText without adding them to events", () => {
    let state = initialTraceTimelineState;
    state = traceTimelineReducer(state, {
      kind: "trace",
      event: { ...sampleEvent, type: "llm_text_delta", payload: { delta: "hel" } },
    });
    state = traceTimelineReducer(state, {
      kind: "trace",
      event: { ...sampleEvent, id: 2, type: "llm_text_delta", payload: { delta: "lo" } },
    });
    expect(state.streamingText).toBe("hello");
    expect(state.events).toEqual([]);
  });

  it("clears streamingText once a tool call starts, but still records that event", () => {
    let state = initialTraceTimelineState;
    state = traceTimelineReducer(state, {
      kind: "trace",
      event: { ...sampleEvent, type: "llm_text_delta", payload: { delta: "thinking…" } },
    });
    state = traceTimelineReducer(state, {
      kind: "trace",
      event: { ...sampleEvent, id: 2, type: "tool_call_start" },
    });
    expect(state.streamingText).toBe("");
    expect(state.events.map((e) => e.type)).toEqual(["tool_call_start"]);
  });

  it("records the final state payload when the run completes", () => {
    const next = traceTimelineReducer(initialTraceTimelineState, { kind: "final", state: { reply: "done" } });
    expect(next.finalState).toEqual({ reply: "done" });
  });

  it("resets to the initial state regardless of accumulated events, status, or finalState", () => {
    let state = initialTraceTimelineState;
    state = traceTimelineReducer(state, { kind: "trace", event: sampleEvent });
    state = traceTimelineReducer(state, {
      kind: "trace",
      event: { ...sampleEvent, id: 2, type: "tool_call_start" },
    });
    state = traceTimelineReducer(state, { kind: "status", status: "paused" });
    state = traceTimelineReducer(state, { kind: "final", state: { reply: "done" } });

    const next = traceTimelineReducer(state, { kind: "reset" });
    expect(next).toEqual(initialTraceTimelineState);
  });
});
