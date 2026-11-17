import { API_URL } from "./api";

export interface LocalAgentSession {
  id: string;
  source: string;
  source_name: string;
  session_id: string;
  title: string;
  preview: string;
  cwd: string | null;
  created_at: string | null;
  updated_at: string;
  message_count: number | null;
  user_message_count: number;
  model: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number | null;
  archived: boolean;
  subagent: boolean;
  parent_session_id: string | null;
}

export interface LocalAgentSource {
  id: string;
  name: string;
  count: number;
}

export interface LocalAgentSessionMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string | null;
}

export interface LocalAgentSessionDetail extends LocalAgentSession {
  messages: LocalAgentSessionMessage[];
}

export function localSessionsUrl(source?: string, query?: string): string {
  const params = new URLSearchParams();
  if (source) params.set("source", source);
  if (query?.trim()) params.set("q", query.trim());
  const suffix = params.size ? `?${params.toString()}` : "";
  return `${API_URL}/api/local-sessions${suffix}`;
}

export async function listLocalAgentSessions(
  options?: { source?: string; query?: string }
): Promise<{
  sessions: LocalAgentSession[];
  sources: LocalAgentSource[];
  home: string;
}> {
  const response = await fetch(
    localSessionsUrl(options?.source, options?.query),
    { cache: "no-store" }
  );
  if (!response.ok) {
    throw new Error(`API ${response.status} ${response.statusText}`);
  }
  return response.json();
}

export async function getLocalAgentSession(
  source: string,
  sessionId: string
): Promise<LocalAgentSessionDetail> {
  const response = await fetch(
    `${API_URL}/api/local-sessions/${encodeURIComponent(source)}/${encodeURIComponent(sessionId)}`,
    { cache: "no-store" }
  );
  if (!response.ok) {
    throw new Error(`API ${response.status} ${response.statusText}`);
  }
  return response.json();
}

export function resumeCommand(source: string, sessionId: string): string {
  if (source === "codex") return `codex resume ${sessionId}`;
  if (source === "claude-code") return `claude --resume ${sessionId}`;
  if (source === "pi") return `pi --session ${sessionId}`;
  return "";
}
