import { useEffect, useState } from "react";
import { startRun, resumeRun, getApiKey, ApiAuthError } from "./api.js";
import { useRunEvents } from "./hooks/useRunEvents.js";
import { ChatPanel } from "./components/ChatPanel.js";
import { TraceDrawer } from "./components/TraceDrawer.js";
import { ApiKeyGate } from "./components/ApiKeyGate.js";
import { SessionSidebar } from "./components/SessionSidebar.js";
import { createEmptySession, loadSessions, saveSessions } from "./lib/sessions.js";
import type { ChatSession } from "./types.js";
import "./styles/tokens.css";
import "./styles/app.css";

export function App() {
  const [hasApiKey, setHasApiKey] = useState(() => getApiKey() !== null);
  const [authError, setAuthError] = useState<string>();
  const [{ sessions, activeSessionId }, setSessionState] = useState(loadSessions);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [error, setError] = useState<string>();

  const activeSession = sessions.find((session) => session.id === activeSessionId) ?? sessions[0];
  const timeline = useRunEvents(activeSessionId, activeSession.runId);
  // Once the SSE connection is confirmed terminally dead, no more trace events or status changes
  // will ever arrive for this run, so timeline.status can never reach "done" on its own. Without
  // excluding connectionError here, the run would stay "in flight" forever and the user could
  // never send another message. Treating a confirmed-dead connection as "not in flight" lets the
  // user start a fresh conversation (implicitly abandoning the stuck run) instead of being
  // permanently locked out.
  const isRunInFlight =
    activeSession.runId !== undefined &&
    !timeline.connectionError &&
    (timeline.status === "running" || timeline.status === "paused");

  useEffect(() => {
    saveSessions(sessions, activeSessionId);
  }, [sessions, activeSessionId]);

  function updateSession(sessionId: string, update: (session: ChatSession) => ChatSession) {
    setSessionState((prev) => ({
      ...prev,
      sessions: prev.sessions.map((session) => (session.id === sessionId ? update(session) : session)),
    }));
  }

  useEffect(() => {
    const reply = timeline.finalState?.reply;
    if (typeof reply !== "string") return;
    // activeSessionId is captured fresh on every render this effect can run in (it's a dep), so
    // this always appends to whichever session actually owns the run timeline came from — not
    // necessarily whatever's active by the time the effect body executes.
    updateSession(activeSessionId, (session) => ({
      ...session,
      messages: [...session.messages, { id: crypto.randomUUID(), role: "assistant", text: reply }],
    }));
  }, [timeline.finalState, activeSessionId]);

  useEffect(() => {
    if (timeline.connectionError) {
      setError("与服务器的连接已断开，请刷新页面重试");
    }
  }, [timeline.connectionError]);

  async function handleSend(text: string) {
    const sessionId = activeSessionId;
    updateSession(sessionId, (session) => ({
      ...session,
      messages: [...session.messages, { id: crypto.randomUUID(), role: "user", text }],
    }));
    try {
      const { runId: newRunId } = await startRun(sessionId, text);
      updateSession(sessionId, (session) => ({ ...session, runId: newRunId }));
      setError(undefined);
    } catch (err) {
      if (err instanceof ApiAuthError) {
        setHasApiKey(false);
        setAuthError("密钥无效或已被吊销，请重新输入");
        return;
      }
      setError("发送失败，请重试");
    }
  }

  async function handleApprove(approved: boolean) {
    const runId = activeSession.runId;
    if (!runId) return;
    try {
      await resumeRun(activeSessionId, runId, approved);
    } catch (err) {
      if (err instanceof ApiAuthError) {
        setHasApiKey(false);
        setAuthError("密钥无效或已被吊销，请重新输入");
        return;
      }
      setError("操作失败，请重试");
    }
  }

  function handleCreateSession() {
    const session = createEmptySession();
    setSessionState((prev) => ({ sessions: [session, ...prev.sessions], activeSessionId: session.id }));
    setSidebarOpen(false);
    setError(undefined);
  }

  function handleSelectSession(sessionId: string) {
    setSessionState((prev) => ({ ...prev, activeSessionId: sessionId }));
    setSidebarOpen(false);
    setError(undefined);
  }

  function handleDeleteSession(sessionId: string) {
    setSessionState((prev) => {
      const remaining = prev.sessions.filter((session) => session.id !== sessionId);
      if (remaining.length === 0) {
        const fresh = createEmptySession();
        return { sessions: [fresh], activeSessionId: fresh.id };
      }
      const activeSessionId = prev.activeSessionId === sessionId ? remaining[0].id : prev.activeSessionId;
      return { sessions: remaining, activeSessionId };
    });
  }

  if (!hasApiKey) {
    return (
      <main className="app-gate-shell">
        <ApiKeyGate
          error={authError}
          onSubmit={() => {
            setAuthError(undefined);
            setHasApiKey(true);
          }}
        />
      </main>
    );
  }

  return (
    <div className="app-shell">
      <SessionSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        open={sidebarOpen}
        onSelect={handleSelectSession}
        onCreate={handleCreateSession}
        onDelete={handleDeleteSession}
        onClose={() => setSidebarOpen(false)}
      />
      <main className="app-main">
        <header className="app-header">
          <button className="sidebar-trigger" onClick={() => setSidebarOpen((value) => !value)} aria-label="会话列表">
            ☰
          </button>
          <span className="app-title">OpenTalos · chat-agent</span>
          <button className="drawer-trigger" onClick={() => setDrawerOpen((value) => !value)}>
            📊 轨迹 ({timeline.events.length})
          </button>
        </header>
        <ChatPanel messages={activeSession.messages} onSend={handleSend} error={error} disabled={isRunInFlight} />
        <TraceDrawer
          open={drawerOpen}
          timeline={timeline}
          onClose={() => setDrawerOpen(false)}
          onApprove={handleApprove}
        />
      </main>
    </div>
  );
}
