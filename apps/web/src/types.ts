export interface TraceEventDto {
  id: number;
  type: string;
  runId: string;
  tenantId: string;
  sessionId: string;
  timestamp: string;
  payload?: Record<string, unknown>;
}

export type RunStatus = "running" | "paused" | "done";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  /** Set on a user message once its run has started — links the message to the trace events it
   * produced, so the 轨迹 tab can show every past run's trace grouped under the turn that
   * triggered it, not just the most recent one. */
  runId?: string;
}

export interface ChatSession {
  id: string;
  createdAt: number;
  messages: ChatMessage[];
  runId?: string;
}
