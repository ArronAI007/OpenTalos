import type { RunStatus, TraceEventDto } from "../types.js";

export interface TraceTimelineState {
  events: TraceEventDto[];
  status: RunStatus;
  finalState?: Record<string, unknown>;
  /** The assistant's reply as it streams in, accumulated from llm_text_delta trace events (never
   * pushed into `events` themselves — one per model chunk would flood the trace timeline). Reset
   * to "" whenever a tool call starts, since any text streamed before that point was a preamble
   * for the tool decision, not the model's final answer. */
  streamingText: string;
  /** The model's reasoning/thinking trace as it streams in, accumulated from llm_reasoning_delta
   * trace events. Unlike streamingText, this is NEVER reset on tool_call_start — the model's
   * reasoning about which tool to call is part of the same thinking process as its reasoning about
   * the final answer, so it just keeps growing across every round of a turn. */
  reasoningStreamingText: string;
  /** Set when the run's status becomes "failed" — the human-readable error from the backend
   * (see GET /runs/:runId's and the SSE "failed" event's `error` field). */
  runError?: string;
  /** Set when the SSE connection died AND a follow-up GET /runs/:runId confirmed the server has no
   * checkpoint for this runId at all (see useRunEvents' onerror handler) — a stale local reference
   * to a run that's genuinely gone (e.g. its checkpoint was deleted), not a real connectivity
   * failure. App.tsx uses this to silently drop the session's runId instead of showing a
   * "connection lost, please refresh" message that a refresh could never actually fix. */
  runNotFound?: boolean;
}

export const initialTraceTimelineState: TraceTimelineState = {
  events: [],
  status: "running",
  streamingText: "",
  reasoningStreamingText: "",
};

export type TraceTimelineAction =
  | { kind: "trace"; event: TraceEventDto }
  | { kind: "status"; status: RunStatus }
  | { kind: "final"; state: Record<string, unknown> }
  | { kind: "failed"; error: string }
  | { kind: "run_not_found" }
  | { kind: "reset" };

export function traceTimelineReducer(state: TraceTimelineState, action: TraceTimelineAction): TraceTimelineState {
  if (action.kind === "reset") {
    return initialTraceTimelineState;
  }
  if (action.kind === "run_not_found") {
    return { ...state, runNotFound: true };
  }
  if (action.kind === "trace") {
    const { event } = action;
    if (event.type === "llm_text_delta") {
      const delta = typeof event.payload?.delta === "string" ? event.payload.delta : "";
      return { ...state, streamingText: state.streamingText + delta };
    }
    if (event.type === "llm_reasoning_delta") {
      const delta = typeof event.payload?.delta === "string" ? event.payload.delta : "";
      return { ...state, reasoningStreamingText: state.reasoningStreamingText + delta };
    }
    if (event.type === "tool_call_start") {
      return { ...state, events: [...state.events, event], streamingText: "" };
    }
    return { ...state, events: [...state.events, event] };
  }
  if (action.kind === "status") {
    return { ...state, status: action.status };
  }
  if (action.kind === "failed") {
    return { ...state, status: "failed", runError: action.error };
  }
  return { ...state, finalState: action.state };
}
