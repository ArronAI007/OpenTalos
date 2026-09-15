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
  /** Base64 data URIs of images attached to this message — only ever set on a user message (see
   * ChatPanel's attachment picker). Persisted alongside the message so it still renders after a
   * reload. */
  images?: string[];
  /** Text/code files attached to this message — only ever set on a user message. Rendered as its
   * own labeled code block (see TextAttachmentBlock), separate from `text`: the model still sees
   * this content inlined into the message actually sent (see api.ts's startRun call in App.tsx),
   * but the LOCAL display keeps it out of `text` so it doesn't show up as literal ``` characters
   * in the plain-text user bubble (user messages are intentionally never markdown-rendered). */
  textAttachments?: { name: string; content: string }[];
}

/** What ChatPanel's composer hands to App.tsx's onSend when the user submits a message — see
 * ChatPanel.tsx's own comment on why modelText and displayText differ. */
export interface OutgoingChatMessage {
  modelText: string;
  displayText: string;
  images?: string[];
  textAttachments?: { name: string; content: string }[];
}

export interface ChatSession {
  id: string;
  createdAt: number;
  messages: ChatMessage[];
  runId?: string;
}
