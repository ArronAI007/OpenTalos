import { useEffect, useReducer, useState } from "react";
import { eventsUrl, getRun } from "../api.js";
import { initialTraceTimelineState, traceTimelineReducer } from "./trace-reducer.js";

export function useRunEvents(sessionId: string | undefined, runId: string | undefined) {
  const [state, dispatch] = useReducer(traceTimelineReducer, initialTraceTimelineState);
  const [connectionError, setConnectionError] = useState(false);

  // Reset synchronously during render — React's sanctioned "adjust state when a prop changes"
  // pattern (see https://react.dev/reference/react/useState#storing-information-from-previous-renders)
  // — rather than only from the effect below. An effect-only reset runs one commit AFTER the
  // render that changed (sessionId, runId), so on THAT first render `state` is still the
  // PREVIOUS run's — and anything that reads this hook's return value in that same commit (e.g.
  // App.tsx's finalState-append effect, which re-fires on every activeSessionId change) would see
  // a stale finalState as if it belonged to the newly active session. Since a session with no run
  // yet can never satisfy a runId-keyed dedup check, that stale read re-appended the PREVIOUS
  // session's reply every single time it was switched back into.
  //
  // A ref mutated during render (an earlier attempt at this fix) is NOT safe here: React's
  // StrictMode double-invokes every render to catch exactly this kind of impurity, and the second
  // invocation would see the ref already updated by the first and silently skip the reset.
  // Routing the reset through dispatch/setState instead makes it visible to React, which discards
  // the first (pre-adjustment) invocation's output and re-renders with the corrected state before
  // committing — safe no matter how many times it's invoked.
  const key = sessionId && runId ? `${sessionId}:${runId}` : undefined;
  const [previousKey, setPreviousKey] = useState(key);
  if (previousKey !== key) {
    setPreviousKey(key);
    dispatch({ kind: "reset" });
    setConnectionError(false);
  }

  useEffect(() => {
    if (!sessionId || !runId) return;
    const source = new EventSource(eventsUrl(sessionId, runId));

    source.addEventListener("trace", (event) => {
      dispatch({ kind: "trace", event: JSON.parse((event as MessageEvent).data) });
    });
    source.addEventListener("status_changed", (event) => {
      const { status } = JSON.parse((event as MessageEvent).data);
      dispatch({ kind: "status", status });
    });
    source.addEventListener("done", () => {
      getRun(sessionId, runId)
        .then((run) => dispatch({ kind: "final", state: run.state }))
        .catch(() => {
          // Best-effort: if the final-state fetch fails, the timeline still shows every trace
          // event that streamed in — only the convenience "final reply" summary is missing.
        })
        .finally(() => source.close());
    });
    source.onopen = () => {
      setConnectionError(false);
    };
    source.onerror = () => {
      // EventSource retries automatically on transient network errors, so a single error
      // isn't necessarily fatal. But `readyState === CLOSED` means the browser has given up
      // (e.g. the server returned a non-retryable HTTP status), so surface that to the UI —
      // otherwise a chat waiting on a paused/running run would sit silently forever with no
      // indication that no further trace events or status changes will ever arrive.
      if (source.readyState === EventSource.CLOSED) {
        setConnectionError(true);
      }
    };

    return () => source.close();
  }, [sessionId, runId]);

  return { ...state, connectionError };
}
