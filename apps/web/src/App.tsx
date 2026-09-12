import { useEffect, useState } from "react";
import { startRun, resumeRun, getApiKey, clearApiKey, ApiAuthError } from "./api.js";
import { useRunEvents } from "./hooks/useRunEvents.js";
import { useRunHistory } from "./hooks/useRunHistory.js";
import { ChatPanel } from "./components/ChatPanel.js";
import { TracePanel } from "./components/TracePanel.js";
import { ApiKeyGate } from "./components/ApiKeyGate.js";
import { SessionSidebar } from "./components/SessionSidebar.js";
import { SessionLogMenu } from "./components/SessionLogMenu.js";
import { SettingsPanel } from "./components/SettingsPanel.js";
import { createEmptySession, loadSessions, saveSessions, sessionTitle } from "./lib/sessions.js";
import { applyTheme, loadTheme, saveTheme, type ThemePreference } from "./lib/theme.js";
import type { ChatSession } from "./types.js";
import "./styles/tokens.css";
import "./styles/app.css";

type Tab = "chat" | "trace";

export function App() {
  const [hasApiKey, setHasApiKey] = useState(() => getApiKey() !== null);
  const [authError, setAuthError] = useState<string>();
  const [{ sessions, activeSessionId }, setSessionState] = useState(loadSessions);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>("chat");
  const [error, setError] = useState<string>();
  const [theme, setTheme] = useState<ThemePreference>(loadTheme);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    applyTheme(theme);
    saveTheme(theme);
  }, [theme]);

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

  // Every past run's trace is durably persisted server-side, but ChatSession only ever tracks its
  // most recent runId (needed for resume/approve) — so without this, switching turns or reloading
  // the page would only ever show the latest run's trace, silently dropping every earlier turn's.
  // Attaching runId to the user message that started each run (see handleSend) lets the 轨迹 tab
  // reconstruct the full history and group it turn-by-turn, matching the 对话 tab's message list.
  // Restricted to the user role: the assistant reply for that same run also carries this runId
  // (see the finalState effect below, for dedup) — counting both would double up every group.
  const runTurns = activeSession.messages.filter(
    (message): message is typeof message & { runId: string } => message.role === "user" && message.runId !== undefined,
  );
  const currentTurn = runTurns.find((turn) => turn.runId === activeSession.runId);
  const historicalTurns = runTurns.filter((turn) => turn.runId !== activeSession.runId);
  const runHistory = useRunHistory(
    activeSessionId,
    historicalTurns.map((turn) => turn.runId),
  );
  const historicalRuns = historicalTurns.map((turn) => ({
    runId: turn.runId,
    label: turn.text,
    events: runHistory[turn.runId] ?? [],
  }));

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
    updateSession(activeSessionId, (session) => {
      const runId = session.runId;
      // A page reload (or revisiting this session) reconnects useRunEvents' SSE for a run that's
      // already "done" — the server replays its full history and re-delivers a fresh finalState
      // object every time, so without this guard, this effect would append another duplicate
      // copy of the same reply on every single reconnect.
      const alreadyRecorded =
        runId !== undefined && session.messages.some((message) => message.role === "assistant" && message.runId === runId);
      if (alreadyRecorded) return session;
      return {
        ...session,
        messages: [...session.messages, { id: crypto.randomUUID(), role: "assistant", text: reply, runId }],
      };
    });
  }, [timeline.finalState, activeSessionId]);

  useEffect(() => {
    if (timeline.connectionError) {
      setError("与服务器的连接已断开，请刷新页面重试");
    }
  }, [timeline.connectionError]);

  async function handleSend(text: string) {
    const sessionId = activeSessionId;
    const messageId = crypto.randomUUID();
    updateSession(sessionId, (session) => ({
      ...session,
      messages: [...session.messages, { id: messageId, role: "user", text }],
    }));
    try {
      const { runId: newRunId } = await startRun(sessionId, text);
      updateSession(sessionId, (session) => ({
        ...session,
        runId: newRunId,
        messages: session.messages.map((message) =>
          message.id === messageId ? { ...message, runId: newRunId } : message,
        ),
      }));
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
      setActiveTab("chat");
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
    setActiveTab("chat");
    setError(undefined);
  }

  function handleSelectSession(sessionId: string) {
    setSessionState((prev) => ({ ...prev, activeSessionId: sessionId }));
    setSidebarOpen(false);
    setActiveTab("chat");
    setError(undefined);
  }

  function handleChangeApiKey() {
    clearApiKey();
    setHasApiKey(false);
    setSettingsOpen(false);
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
        collapsed={sidebarCollapsed}
        onSelect={handleSelectSession}
        onCreate={handleCreateSession}
        onDelete={handleDeleteSession}
        onClose={() => setSidebarOpen(false)}
        onToggleCollapse={() => setSidebarCollapsed((value) => !value)}
        onOpenSettings={() => setSettingsOpen(true)}
      />
      <main className="app-main">
        <header className="app-header">
          <button className="sidebar-trigger" onClick={() => setSidebarOpen((value) => !value)} aria-label="会话列表">
            ☰
          </button>
          <div className="app-header-main">
            <div className="app-header-top">
              <h1 className="app-session-title">{sessionTitle(activeSession)}</h1>
              <SessionLogMenu session={activeSession} />
            </div>
            <nav className="app-tabs" aria-label="视图切换">
              <button
                type="button"
                className={`app-tab${activeTab === "chat" ? " app-tab-active" : ""}`}
                onClick={() => setActiveTab("chat")}
              >
                对话
              </button>
              <button
                type="button"
                className={`app-tab${activeTab === "trace" ? " app-tab-active" : ""}`}
                onClick={() => setActiveTab("trace")}
              >
                轨迹
                {timeline.status === "paused" && <span className="app-tab-badge" aria-label="有待确认的操作" />}
              </button>
            </nav>
          </div>
        </header>
        {activeTab === "chat" ? (
          <ChatPanel
            messages={activeSession.messages}
            onSend={handleSend}
            error={error}
            disabled={isRunInFlight}
            streamingText={timeline.finalState ? undefined : timeline.streamingText}
          />
        ) : (
          <TracePanel
            historicalRuns={historicalRuns}
            currentLabel={currentTurn?.text}
            timeline={timeline}
            onApprove={handleApprove}
          />
        )}
      </main>
      {settingsOpen && (
        <SettingsPanel
          theme={theme}
          onThemeChange={setTheme}
          onChangeApiKey={handleChangeApiKey}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  );
}
