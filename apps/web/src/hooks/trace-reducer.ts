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
}

export const initialTraceTimelineState: TraceTimelineState = { events: [], status: "running", streamingText: "" };

export type TraceTimelineAction =
  | { kind: "trace"; event: TraceEventDto }
  | { kind: "status"; status: RunStatus }
  | { kind: "final"; state: Record<string, unknown> }
  | { kind: "reset" };

export function traceTimelineReducer(state: TraceTimelineState, action: TraceTimelineAction): TraceTimelineState {
  if (action.kind === "reset") {
    return initialTraceTimelineState;
  }
  if (action.kind === "trace") {
    const { event } = action;
    if (event.type === "llm_text_delta") {
      const delta = typeof event.payload?.delta === "string" ? event.payload.delta : "";
      return { ...state, streamingText: state.streamingText + delta };
    }
    if (event.type === "tool_call_start") {
      return { ...state, events: [...state.events, event], streamingText: "" };
    }
    return { ...state, events: [...state.events, event] };
  }
  if (action.kind === "status") {
    return { ...state, status: action.status };
  }
  return { ...state, finalState: action.state };
}
