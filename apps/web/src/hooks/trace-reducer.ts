import type { RunStatus, TraceEventDto } from "../types.js";

export interface TraceTimelineState {
  events: TraceEventDto[];
  status: RunStatus;
  finalState?: Record<string, unknown>;
}

export const initialTraceTimelineState: TraceTimelineState = { events: [], status: "running" };

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
    return { ...state, events: [...state.events, action.event] };
  }
  if (action.kind === "status") {
    return { ...state, status: action.status };
  }
  return { ...state, finalState: action.state };
}
