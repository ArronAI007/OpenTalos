import type { ChatSession } from "../types.js";

const SESSIONS_KEY = "opentalos-sessions";
const ACTIVE_SESSION_KEY = "opentalos-active-session";

export function createEmptySession(): ChatSession {
  return { id: crypto.randomUUID(), createdAt: Date.now(), messages: [] };
}

/** apps/api has no endpoint to list past runs for a session — conversation history only ever
 * lived in this tab's React state, so a refresh silently lost it. Persisting the session list
 * (and which one is active) to localStorage fixes that for this browser, without needing any
 * backend changes. */
export function loadSessions(): { sessions: ChatSession[]; activeSessionId: string } {
  try {
    const raw = localStorage.getItem(SESSIONS_KEY);
    if (raw) {
      const sessions = JSON.parse(raw) as ChatSession[];
      if (Array.isArray(sessions) && sessions.length > 0) {
        // Backfill createdAt for sessions saved before this field existed, so old localStorage
        // data doesn't break relativeTime() below.
        const normalized = sessions.map((session) => ({ ...session, createdAt: session.createdAt ?? Date.now() }));
        const storedActiveId = localStorage.getItem(ACTIVE_SESSION_KEY);
        const activeSessionId =
          storedActiveId && normalized.some((session) => session.id === storedActiveId)
            ? storedActiveId
            : normalized[0].id;
        return { sessions: normalized, activeSessionId };
      }
    }
  } catch {
    // Corrupted/unreadable storage: fall through to a single fresh session below.
  }
  const session = createEmptySession();
  return { sessions: [session], activeSessionId: session.id };
}

export function saveSessions(sessions: ChatSession[], activeSessionId: string): void {
  try {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
    localStorage.setItem(ACTIVE_SESSION_KEY, activeSessionId);
  } catch {
    // Best-effort only (e.g. private browsing with storage disabled) — the chat still works
    // in-memory for the current tab, it just won't survive a refresh.
  }
}

export function sessionTitle(session: ChatSession): string {
  const firstUserMessage = session.messages.find((message) => message.role === "user");
  if (!firstUserMessage) return "新会话";
  return firstUserMessage.text.length > 20 ? `${firstUserMessage.text.slice(0, 20)}…` : firstUserMessage.text;
}

/** Terse relative age for the sidebar list ("刚刚" / "5分钟" / "3小时" / "2天"), matching how long
 * ago a session was created — not a general-purpose date formatter. */
export function relativeSessionAge(createdAt: number): string {
  const diffMs = Date.now() - createdAt;
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diffMs < minute) return "刚刚";
  if (diffMs < hour) return `${Math.floor(diffMs / minute)}分钟`;
  if (diffMs < day) return `${Math.floor(diffMs / hour)}小时`;
  return `${Math.floor(diffMs / day)}天`;
}
