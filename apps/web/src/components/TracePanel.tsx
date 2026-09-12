import { useEffect, useRef, useState } from "react";
import type { TraceEventDto } from "../types.js";
import type { TraceTimelineState } from "../hooks/trace-reducer.js";

interface HistoricalRun {
  runId: string;
  label: string;
  events: TraceEventDto[];
}

interface TracePanelProps {
  /** Every earlier run in this session, oldest first, each already resolved to its full persisted
   * event list (see useRunHistory). */
  historicalRuns: HistoricalRun[];
  /** The user message text that started the run `timeline` below is currently tracking, if any. */
  currentLabel?: string;
  timeline: TraceTimelineState;
  onApprove: (approved: boolean) => void;
}

const DOT_COLOR: Record<string, string> = {
  node_enter: "var(--color-accent)",
  node_exit: "var(--color-accent)",
  tool_call_start: "var(--color-accent-secondary)",
  tool_call_end: "var(--color-accent-secondary)",
  llm_call_start: "var(--color-accent-secondary)",
  llm_call_end: "var(--color-accent-secondary)",
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

export function TracePanel({ historicalRuns, currentLabel, timeline, onApprove }: TracePanelProps) {
  // Guards against a fast double-click (or an impatient double-tap) enqueuing two "resume" tasks
  // for the same run: timeline.status stays "paused" for up to ~500ms after the first click,
  // until the next SSE poll cycle reports the status change, so a second click in that window
  // would otherwise slip through. Reset whenever a NEW pause starts (status transitions INTO
  // "paused") rather than once ever, so approval still works for every future run's pause, not
  // just the first one.
  //
  // A `useState` flag alone isn't enough: two click handlers fired in the same JS turn (e.g. a
  // fast double-click, or two synchronous DOM .click() calls) both close over the SAME pre-render
  // `hasResponded` value, since React doesn't re-render between them -- so a `setState`-only
  // guard would let both calls through. A ref is mutated immediately and synchronously, so the
  // second call in the same tick sees the first call's write.
  const hasRespondedRef = useRef(false);
  const [hasResponded, setHasResponded] = useState(false);

  useEffect(() => {
    if (timeline.status === "paused") {
      hasRespondedRef.current = false;
      setHasResponded(false);
    }
  }, [timeline.status]);

  function handleApprove(approved: boolean) {
    if (hasRespondedRef.current) return;
    hasRespondedRef.current = true;
    setHasResponded(true);
    onApprove(approved);
  }

  // Group labels only earn their keep once there's more than one turn to tell apart — for the
  // common case of a single in-flight run, this renders identically to before (just the list).
  const showGroupLabels = historicalRuns.length > 0;
  const isEmpty = historicalRuns.length === 0 && timeline.events.length === 0;

  return (
    <div className="trace-panel">
      {isEmpty ? (
        <p className="trace-empty">还没有轨迹事件</p>
      ) : (
        <>
          {historicalRuns.map((run) => (
            <section className="trace-group" key={run.runId} aria-label={run.label}>
              {showGroupLabels && <p className="trace-group-label">{run.label}</p>}
              <ul className="trace-timeline">
                {run.events.map((event) => (
                  <TraceEventRow key={event.id} event={event} />
                ))}
              </ul>
            </section>
          ))}
          {timeline.events.length > 0 && (
            <section className="trace-group" aria-label={currentLabel}>
              {showGroupLabels && currentLabel && <p className="trace-group-label">{currentLabel}</p>}
              <ul className="trace-timeline">
                {timeline.events.map((event) => (
                  <TraceEventRow key={event.id} event={event} />
                ))}
              </ul>
            </section>
          )}
        </>
      )}
      {timeline.status === "paused" && (
        <div className="trace-approval">
          <p>⏸ 等待你确认</p>
          <div className="trace-approval-actions">
            <button className="approve-button" onClick={() => handleApprove(true)} disabled={hasResponded}>
              ✓ 批准
            </button>
            <button className="deny-button" onClick={() => handleApprove(false)} disabled={hasResponded}>
              ✕ 拒绝
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
