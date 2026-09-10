import { useEffect, useReducer, useState } from "react";
import { eventsUrl, getRun } from "../api.js";
import { initialTraceTimelineState, traceTimelineReducer } from "./trace-reducer.js";

export function useRunEvents(runId: string | undefined) {
  const [state, dispatch] = useReducer(traceTimelineReducer, initialTraceTimelineState);
  const [connectionError, setConnectionError] = useState(false);

  useEffect(() => {
    if (!runId) return;
    setConnectionError(false);
    const source = new EventSource(eventsUrl(runId));

    source.addEventListener("trace", (event) => {
      dispatch({ kind: "trace", event: JSON.parse((event as MessageEvent).data) });
    });
    source.addEventListener("status_changed", (event) => {
      const { status } = JSON.parse((event as MessageEvent).data);
      dispatch({ kind: "status", status });
    });
    source.addEventListener("done", () => {
      getRun(runId)
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
  }, [runId]);

  return { ...state, connectionError };
}
