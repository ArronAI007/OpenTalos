const API_KEY_STORAGE_KEY = "opentalos-api-key";

export class ApiAuthError extends Error {
  constructor() {
    super("API key rejected");
    this.name = "ApiAuthError";
  }
}

/** Thrown by getRun when the server has no checkpoint for this runId at all (never "belongs to a
 * different session" or any other 4xx — those still throw the generic Error below). Distinct from
 * a real connectivity failure: useRunEvents uses this to recognize "this run genuinely no longer
 * exists" (e.g. a stale runId left over in localStorage from before its checkpoint was deleted)
 * and recover silently, rather than showing a "connection lost, please refresh" message that a
 * refresh could never actually fix — reloading would just retry the same gone-forever runId. */
export class RunNotFoundError extends Error {
  constructor() {
    super("Run not found");
    this.name = "RunNotFoundError";
  }
}

export function getApiKey(): string | null {
  return localStorage.getItem(API_KEY_STORAGE_KEY);
}

export function setApiKey(key: string): void {
  localStorage.setItem(API_KEY_STORAGE_KEY, key);
}

export function clearApiKey(): void {
  localStorage.removeItem(API_KEY_STORAGE_KEY);
}

function withSession(path: string, sessionId: string): string {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}sessionId=${sessionId}`;
}

async function authedFetch(path: string, sessionId: string, init: RequestInit = {}): Promise<Response> {
  const apiKey = getApiKey();
  const res = await fetch(withSession(path, sessionId), {
    ...init,
    headers: { ...init.headers, Authorization: `Bearer ${apiKey}` },
  });
  if (res.status === 401) {
    clearApiKey();
    throw new ApiAuthError();
  }
  return res;
}

export async function startRun(sessionId: string, message: string): Promise<{ runId: string }> {
  const res = await authedFetch("/runs", sessionId, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) throw new Error(`Failed to start run: ${res.status}`);
  return res.json();
}

export async function resumeRun(sessionId: string, runId: string, approved: boolean): Promise<void> {
  const res = await authedFetch(`/runs/${runId}/resume`, sessionId, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved }),
  });
  if (!res.ok) throw new Error(`Failed to resume run: ${res.status}`);
}

export async function cancelRun(sessionId: string, runId: string): Promise<void> {
  const res = await authedFetch(`/runs/${runId}/cancel`, sessionId, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to cancel run: ${res.status}`);
}

export async function getRun(
  sessionId: string,
  runId: string,
): Promise<{ runId: string; status: string; state: Record<string, unknown>; error?: string }> {
  const res = await authedFetch(`/runs/${runId}`, sessionId);
  if (res.status === 404) throw new RunNotFoundError();
  if (!res.ok) throw new Error(`Failed to load run: ${res.status}`);
  return res.json();
}

/** EventSource (used by useRunEvents) cannot set custom request headers, so the API key is
 * appended as a query parameter here specifically — apps/api's auth middleware accepts either
 * the Authorization header or this query parameter uniformly (see apps/api/src/auth.ts). */
export function eventsUrl(sessionId: string, runId: string): string {
  const apiKey = getApiKey();
  return `${withSession(`/runs/${runId}/events`, sessionId)}&apiKey=${encodeURIComponent(apiKey ?? "")}`;
}
