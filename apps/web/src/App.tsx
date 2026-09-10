import { useEffect, useState } from "react";
import { startRun, resumeRun } from "./api.js";
import { useRunEvents } from "./hooks/useRunEvents.js";
import { ChatPanel } from "./components/ChatPanel.js";
import { TraceDrawer } from "./components/TraceDrawer.js";
import type { ChatMessage } from "./types.js";
import "./styles/tokens.css";
import "./styles/app.css";

export function App() {
  const [runId, setRunId] = useState<string>();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [error, setError] = useState<string>();
  const timeline = useRunEvents(runId);

  useEffect(() => {
    const reply = timeline.finalState?.reply;
    if (typeof reply === "string") {
      setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "assistant", text: reply }]);
    }
  }, [timeline.finalState]);

  useEffect(() => {
    if (timeline.connectionError) {
      setError("与服务器的连接已断开，请刷新页面重试");
    }
  }, [timeline.connectionError]);

  async function handleSend(text: string) {
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "user", text }]);
    try {
      const { runId: newRunId } = await startRun(text);
      setRunId(newRunId);
      setError(undefined);
    } catch {
      setError("发送失败，请重试");
    }
  }

  async function handleApprove(approved: boolean) {
    if (!runId) return;
    try {
      await resumeRun(runId, approved);
    } catch {
      setError("操作失败，请重试");
    }
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <span className="app-title">OpenTalos · chat-demo-agent</span>
        <button className="drawer-trigger" onClick={() => setDrawerOpen((value) => !value)}>
          📊 轨迹 ({timeline.events.length})
        </button>
      </header>
      <ChatPanel messages={messages} onSend={handleSend} error={error} />
      <TraceDrawer
        open={drawerOpen}
        timeline={timeline}
        onClose={() => setDrawerOpen(false)}
        onApprove={handleApprove}
      />
    </main>
  );
}
