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
}

export interface ChatSession {
  id: string;
  messages: ChatMessage[];
  runId?: string;
}
