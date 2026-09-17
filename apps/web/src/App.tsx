import { useEffect, useRef, useState } from "react";
import { startRun, resumeRun, cancelRun, steerRun, getApiKey, clearApiKey, ApiAuthError } from "./api.js";
import { useRunEvents } from "./hooks/useRunEvents.js";
import { useRunHistory } from "./hooks/useRunHistory.js";
import { ChatPanel } from "./components/ChatPanel.js";
import { TracePanel } from "./components/TracePanel.js";
import { ApiKeyGate } from "./components/ApiKeyGate.js";
import { SessionSidebar } from "./components/SessionSidebar.js";
import { SessionLogMenu } from "./components/SessionLogMenu.js";
import { EditIcon } from "./components/icons.js";
import { SettingsPanel } from "./components/SettingsPanel.js";
import { RenameSessionDialog } from "./components/RenameSessionDialog.js";
import { createEmptySession, loadSessions, saveSessions, sessionTitle } from "./lib/sessions.js";
import { applyTheme, loadTheme, saveTheme, type ThemePreference } from "./lib/theme.js";
import { loadSidebarWidth, saveSidebarWidth } from "./lib/sidebar-width.js";
import type { ChatSession, OutgoingChatMessage } from "./types.js";
import "./styles/tokens.css";
import "./styles/app.css";

type Tab = "chat" | "trace";

export function App() {
  const [hasApiKey, setHasApiKey] = useState(() => getApiKey() !== null);
  const [authError, setAuthError] = useState<string>();
  const [{ sessions, activeSessionId }, setSessionState] = useState(loadSessions);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState<number>(loadSidebarWidth);
  const [activeTab, setActiveTab] = useState<Tab>("chat");
  const [renamingSession, setRenamingSession] = useState(false);
  const [error, setError] = useState<string>();
  const [steerConfirmation, setSteerConfirmation] = useState<string>();
  const [theme, setTheme] = useState<ThemePreference>(loadTheme);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    applyTheme(theme);
    saveTheme(theme);
  }, [theme]);

  useEffect(() => {
    saveSidebarWidth(sidebarWidth);
  }, [sidebarWidth]);

  const activeSession = sessions.find((session) => session.id === activeSessionId) ?? sessions[0];
  const timeline = useRunEvents(activeSessionId, activeSession.runId);
  // Reconnecting useRunEvents' SSE (e.g. right after a page reload) always starts from
  // initialTraceTimelineState — status "running", no finalState — even for a run that finished
  // long ago, until the replayed status_changed/done events round-trip back. Without this, that
  // brief window would flash the composer disabled and re-play the reply as a transient
  // "streaming" bubble alongside the already-persisted message, every single time this run's
  // stream is reconnected to. A locally-recorded reply for this exact run is known synchronously
  // from session state — no round trip needed — so it's a more trustworthy "is this run actually
  // still going" signal than the freshly-reset timeline is, right after a reconnect.
  const activeRunAlreadyCompletedLocally =
    activeSession.runId !== undefined &&
    activeSession.messages.some((message) => message.role === "assistant" && message.runId === activeSession.runId);
  // Once the SSE connection is confirmed terminally dead, no more trace events or status changes
  // will ever arrive for this run, so timeline.status can never reach "done" on its own. Without
  // excluding connectionError here, the run would stay "in flight" forever and the user could
  // never send another message. Treating a confirmed-dead connection as "not in flight" lets the
  // user start a fresh conversation (implicitly abandoning the stuck run) instead of being
  // permanently locked out.
  // Neither "running" nor "paused" force-disables the composer anymore: sending during "running"
  // steers (handleSteer), sending during "paused" queues as a follow-up (handleSend below) — every
  // possible status now has a defined behavior for a new send, so there's nothing left to block.
  // Kept (renamed from isRunInFlight) only to drive that queue-vs-start branch and the drain effect
  // below, never to disable the composer.
  const hasPausedRun =
    !activeRunAlreadyCompletedLocally &&
    activeSession.runId !== undefined &&
    !timeline.connectionError &&
    timeline.status === "paused";
  // Broader than hasPausedRun: true for "running" too, not just "paused". Used ONLY to gate the
  // follow-up drain effect below — it must wait for a drained item's own run to reach an actual
  // terminal state (done/failed), not just stop being paused, before advancing to the next queued
  // item. Draining on hasPausedRun alone would advance the moment a drained item's run becomes
  // "running" (before its own eventual pause/approval even happens), racing two sends at once.
  const hasActiveRun =
    !activeRunAlreadyCompletedLocally &&
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
    if (timeline.streamingText) setSteerConfirmation(undefined);
  }, [timeline.streamingText]);

  useEffect(() => {
    const reply = timeline.finalState?.reply;
    if (typeof reply !== "string") return;
    const reasoningText = typeof timeline.finalState?.reasoningText === "string" ? timeline.finalState.reasoningText : undefined;
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
        messages: [...session.messages, { id: crypto.randomUUID(), role: "assistant", text: reply, runId, reasoningText }],
      };
    });
  }, [timeline.finalState, activeSessionId]);

  useEffect(() => {
    if (timeline.connectionError) {
      setError("与服务器的连接已断开，请刷新页面重试");
    }
  }, [timeline.connectionError]);

  useEffect(() => {
    // The run this session was tracking genuinely no longer exists server-side (see useRunEvents'
    // onerror handler) — most likely a stale runId left over from before its checkpoint was
    // deleted. Recover silently by dropping the reference: the session's message history is
    // untouched, the composer was never blocked by run status in the first place, and
    // there's nothing productive for the user to do about a run that's gone for good — showing an
    // error here would just be alarming and, unlike a real connection failure, unfixable by the
    // "refresh and retry" a connectionError banner suggests.
    if (!timeline.runNotFound) return;
    updateSession(activeSessionId, (session) => ({ ...session, runId: undefined }));
  }, [timeline.runNotFound, activeSessionId]);

  // Draining strictly one queued follow-up at a time: `isDrainingFollowUp` blocks the drain effect
  // below from dequeuing a second item while an earlier drained item's OWN run is still going.
  // Gating only on hasPausedRun (i.e. "not currently paused") is not enough: the moment a drained
  // item's handleSend() starts its run, status flips to "running" (not "paused"), which would let
  // this effect immediately dequeue and send the NEXT item too — racing two sends before the first
  // one has even reached its own pause/approval, let alone finished. hasActiveRun (running OR
  // paused) is the real "still busy" signal, so the ref is only released once that goes back to
  // false — i.e. the drained item's run has actually reached a terminal state.
  // If a drained item's own send FAILS (e.g. startRun rejects), hasActiveRun never becomes true in
  // the first place, so it can never transition back to false to release the guard above via the
  // effect below — bumping this forces the drain effect to re-check regardless. Only used on the
  // failure path; the success path relies purely on hasActiveRun's real transition (see above).
  const [drainRetryTick, setDrainRetryTick] = useState(0);
  const isDrainingFollowUp = useRef(false);
  useEffect(() => {
    if (!hasActiveRun) isDrainingFollowUp.current = false;
  }, [hasActiveRun]);
  useEffect(() => {
    if (hasActiveRun || isDrainingFollowUp.current) return;
    const pending = activeSession.pendingFollowUps;
    if (!pending || pending.length === 0) return;
    const [next, ...rest] = pending;
    isDrainingFollowUp.current = true;
    updateSession(activeSessionId, (session) => ({ ...session, pendingFollowUps: rest }));
    void handleSend(next).then((succeeded) => {
      if (!succeeded) {
        isDrainingFollowUp.current = false;
        setDrainRetryTick((tick) => tick + 1);
      }
    });
  }, [hasActiveRun, activeSessionId, activeSession.pendingFollowUps, drainRetryTick]);

  useEffect(() => {
    if (timeline.runError) {
      setError(timeline.runError);
    }
  }, [timeline.runError]);

  // Returns whether the message actually resulted in an active run (started, or steered into an
  // already-active one) — false on failure. The follow-up drain effect uses this to tell "send
  // failed, nothing is now active" apart from "send succeeded, hasActiveRun will flip true then
  // false on its own" — without it, a failed drained send would leave the drain guard stuck
  // forever, since hasActiveRun would never transition to unblock it (see that effect's comment).
  async function handleSend({ modelText, displayText, images, textAttachments }: OutgoingChatMessage): Promise<boolean> {
    if (timeline.status === "running" && activeSession.runId) {
      await handleSteer(modelText);
      return true;
    }
    if (hasPausedRun) {
      // Nothing to steer while paused (the model already produced this turn's output and is just
      // waiting on a human approval click) — queue this message and let the drain effect below
      // send it once the run is no longer paused. Store the full message (not just modelText) so
      // images/textAttachments and the separate display text survive the wait.
      updateSession(activeSessionId, (session) => ({
        ...session,
        pendingFollowUps: [...(session.pendingFollowUps ?? []), { modelText, displayText, images, textAttachments }],
      }));
      return true;
    }
    const sessionId = activeSessionId;
    const messageId = crypto.randomUUID();
    updateSession(sessionId, (session) => ({
      ...session,
      messages: [...session.messages, { id: messageId, role: "user", text: displayText, images, textAttachments }],
    }));
    try {
      const { runId: newRunId } = await startRun(sessionId, modelText, images);
      updateSession(sessionId, (session) => ({
        ...session,
        runId: newRunId,
        messages: session.messages.map((message) =>
          message.id === messageId ? { ...message, runId: newRunId } : message,
        ),
      }));
      setError(undefined);
      return true;
    } catch (err) {
      if (err instanceof ApiAuthError) {
        setHasApiKey(false);
        setAuthError("密钥无效或已被吊销，请重新输入");
        return false;
      }
      setError("发送失败，请重试");
      return false;
    }
  }

  async function handleStop() {
    const runId = activeSession.runId;
    if (!runId) return;
    try {
      await cancelRun(activeSessionId, runId);
    } catch (err) {
      if (err instanceof ApiAuthError) {
        setHasApiKey(false);
        setAuthError("密钥无效或已被吊销，请重新输入");
        return;
      }
      setError("停止失败，请重试");
    }
  }

  async function handleSteer(text: string) {
    const runId = activeSession.runId;
    if (!runId) return;
    try {
      await steerRun(activeSessionId, runId, text);
      setSteerConfirmation("已发送修改意见，等待模型响应");
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
    setSteerConfirmation(undefined);
    setRenamingSession(false);
  }

  function handleSelectSession(sessionId: string) {
    setSessionState((prev) => ({ ...prev, activeSessionId: sessionId }));
    setSidebarOpen(false);
    setActiveTab("chat");
    setError(undefined);
    setSteerConfirmation(undefined);
    setRenamingSession(false);
  }

  function handleSaveTitle(value: string) {
    const trimmed = value.trim();
    updateSession(activeSessionId, (session) => ({ ...session, customTitle: trimmed || undefined }));
    setRenamingSession(false);
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
        width={sidebarWidth}
        onWidthChange={setSidebarWidth}
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
              <div className="app-header-titles">
                <button
                  type="button"
                  className="app-session-title-row"
                  onClick={() => setRenamingSession(true)}
                  aria-label="重命名会话"
                >
                  <h1 className="app-session-title">{sessionTitle(activeSession)}</h1>
                  <span className="app-session-title-edit-icon" aria-hidden="true">
                    <EditIcon />
                  </span>
                </button>
                <p className="app-header-caption">AI 生成可能有误，注意核实</p>
              </div>
              <div className="app-header-actions">
                <SessionLogMenu session={activeSession} />
                <button
                  type="button"
                  className="sidebar-icon-button app-trace-toggle"
                  aria-pressed={activeTab === "trace"}
                  aria-label="轨迹"
                  onClick={() => setActiveTab(activeTab === "trace" ? "chat" : "trace")}
                >
                  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden="true">
                    <circle cx="12" cy="12" r="8.5" stroke="currentColor" strokeWidth="1.6" />
                    <path
                      d="M12 7.5V12l3 2"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                  {timeline.status === "paused" && <span className="app-tab-badge" aria-label="有待确认的操作" />}
                </button>
              </div>
            </div>
          </div>
        </header>
        {activeTab === "chat" ? (
          <ChatPanel
            messages={activeSession.messages}
            onSend={handleSend}
            onStop={handleStop}
            error={error}
            status={timeline.status}
            streamingText={activeRunAlreadyCompletedLocally || timeline.finalState ? undefined : timeline.streamingText}
            reasoningStreamingText={
              activeRunAlreadyCompletedLocally || timeline.finalState ? undefined : timeline.reasoningStreamingText
            }
            onApprove={handleApprove}
            steerConfirmation={steerConfirmation}
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
      {renamingSession && (
        <RenameSessionDialog
          initialValue={sessionTitle(activeSession)}
          onSave={handleSaveTitle}
          onCancel={() => setRenamingSession(false)}
        />
      )}
    </div>
  );
}
