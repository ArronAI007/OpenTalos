export interface TraceEventDto {
  id: number;
  type: string;
  runId: string;
  tenantId: string;
  sessionId: string;
  timestamp: string;
  payload?: Record<string, unknown>;
}

export type RunStatus = "running" | "paused" | "done" | "failed";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  /** Set on the user message once its run has started, and again on the assistant reply once the
   * run completes. On a user message, this links it to the trace events its run produced, so the
   * 轨迹 tab can show every past run's trace grouped under the turn that triggered it. On the
   * assistant reply, it's used purely to detect "this run's reply is already recorded" — an
   * already-finished run's SSE stream replays in full (and re-delivers a fresh finalState) every
   * time it's reconnected to (e.g. on page reload), which would otherwise duplicate the reply. */
  runId?: string;
  /** The model's reasoning/thinking trace for this reply (see ChatState.reasoningText on the
   * backend) — only set on assistant messages, and only when the model actually produced one.
   * Persisted alongside the message so historical turns can still expand it after a reload. */
  reasoningText?: string;
}

export interface ChatSession {
  id: string;
  createdAt: number;
  messages: ChatMessage[];
  runId?: string;
}
