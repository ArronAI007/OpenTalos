import type { ChatSession } from "../types.js";

const SESSIONS_KEY = "opentalos-sessions";
const ACTIVE_SESSION_KEY = "opentalos-active-session";

export function createEmptySession(): ChatSession {
  return { id: crypto.randomUUID(), messages: [] };
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
        const storedActiveId = localStorage.getItem(ACTIVE_SESSION_KEY);
        const activeSessionId =
          storedActiveId && sessions.some((session) => session.id === storedActiveId) ? storedActiveId : sessions[0].id;
        return { sessions, activeSessionId };
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
  if (!firstUserMessage) return "新对话";
  return firstUserMessage.text.length > 20 ? `${firstUserMessage.text.slice(0, 20)}…` : firstUserMessage.text;
}
