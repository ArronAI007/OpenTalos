import { useEffect, useRef, useState } from "react";
import { eventsUrl } from "../api.js";
import type { TraceEventDto } from "../types.js";

/** Fetches and caches the full trace history for every run in `runIds`, keyed by runId. Every one
 * of these runs is already finished (the currently in-flight run is handled live by
 * useRunEvents instead), so opening `/runs/:runId/events` here just replays that run's entire
 * persisted event history once and then closes — no ongoing connection to manage, unlike a live
 * run's stream. */
export function useRunHistory(sessionId: string, runIds: string[]): Record<string, TraceEventDto[]> {
  const [history, setHistory] = useState<Record<string, TraceEventDto[]>>({});
  const fetchedRef = useRef(new Set<string>());

  useEffect(() => {
    fetchedRef.current = new Set();
    setHistory({});
  }, [sessionId]);

  useEffect(() => {
    const toFetch = runIds.filter((runId) => !fetchedRef.current.has(runId));
    const sources = toFetch.map((runId) => {
      fetchedRef.current.add(runId);
      const events: TraceEventDto[] = [];
      const source = new EventSource(eventsUrl(sessionId, runId));
      source.addEventListener("trace", (event) => {
        events.push(JSON.parse((event as MessageEvent).data));
      });
      source.addEventListener("done", () => {
        setHistory((prev) => ({ ...prev, [runId]: events }));
        source.close();
      });
      source.onerror = () => {
        // This run's events are already durably persisted server-side — a fetch failure here just
        // leaves this one run's trace segment empty in the panel, not fatal to the rest of the
        // conversation's history.
        source.close();
      };
      return source;
    });

    return () => {
      for (const source of sources) source.close();
    };
    // Depend on the joined id string, not `runIds` itself: App.tsx recomputes that array fresh
    // every render, and this effect should only redo work when the actual set of run ids changes.
  }, [sessionId, runIds.join(",")]);

  return history;
}
