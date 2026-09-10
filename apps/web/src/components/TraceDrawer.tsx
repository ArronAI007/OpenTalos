import { useEffect, useState } from "react";
import type { TraceEventDto } from "../types.js";
import type { TraceTimelineState } from "../hooks/trace-reducer.js";

interface TraceDrawerProps {
  open: boolean;
  timeline: TraceTimelineState;
  onClose: () => void;
  onApprove: (approved: boolean) => void;
}

const DOT_COLOR: Record<string, string> = {
  node_enter: "var(--color-accent-start)",
  node_exit: "var(--color-accent-start)",
  tool_call_start: "var(--color-accent-teal)",
  tool_call_end: "var(--color-accent-teal)",
  llm_call_start: "var(--color-accent-teal)",
  llm_call_end: "var(--color-accent-teal)",
  hitl_interrupt: "var(--color-warn-text)",
  error: "var(--color-danger-text)",
};

function TraceEventRow({ event }: { event: TraceEventDto }) {
  const [expanded, setExpanded] = useState(false);
  const isPause = event.type === "hitl_interrupt";
  return (
    <li className="trace-row">
      <span className="trace-dot" style={{ background: DOT_COLOR[event.type] ?? "var(--color-text-muted)" }} />
      <div className={`trace-card${isPause ? " trace-card-pause" : ""}`}>
        <button
          type="button"
          className="trace-card-header"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
        >
          <span className="trace-type">{event.type}</span>
          <time className="trace-time">{new Date(event.timestamp).toLocaleTimeString()}</time>
        </button>
        {expanded && event.payload && <pre className="trace-payload">{JSON.stringify(event.payload, null, 2)}</pre>}
      </div>
    </li>
  );
}

export function TraceDrawer({ open, timeline, onClose, onApprove }: TraceDrawerProps) {
  useEffect(() => {
    if (!open) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <aside className="trace-drawer" aria-label="执行轨迹">
      <div className="trace-drawer-header">
        <h2>执行轨迹</h2>
        <button onClick={onClose} aria-label="关闭">
          ✕
        </button>
      </div>
      <ul className="trace-timeline">
        {timeline.events.map((event) => (
          <TraceEventRow key={event.id} event={event} />
        ))}
      </ul>
      {timeline.status === "paused" && (
        <div className="trace-approval">
          <p>⏸ 等待你确认</p>
          <div className="trace-approval-actions">
            <button className="approve-button" onClick={() => onApprove(true)}>
              ✓ 批准
            </button>
            <button className="deny-button" onClick={() => onApprove(false)}>
              ✕ 拒绝
            </button>
          </div>
        </div>
      )}
    </aside>
  );
}
