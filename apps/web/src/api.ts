const SESSION_ID = crypto.randomUUID();
const API_KEY_STORAGE_KEY = "opentalos-api-key";

export class ApiAuthError extends Error {
  constructor() {
    super("API key rejected");
    this.name = "ApiAuthError";
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

function withSession(path: string): string {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}sessionId=${SESSION_ID}`;
}

async function authedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const apiKey = getApiKey();
  const res = await fetch(withSession(path), {
    ...init,
    headers: { ...init.headers, Authorization: `Bearer ${apiKey}` },
  });
  if (res.status === 401) {
    clearApiKey();
    throw new ApiAuthError();
  }
  return res;
}

export async function startRun(message: string): Promise<{ runId: string }> {
  const res = await authedFetch("/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) throw new Error(`Failed to start run: ${res.status}`);
  return res.json();
}

export async function resumeRun(runId: string, approved: boolean): Promise<void> {
  const res = await authedFetch(`/runs/${runId}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved }),
  });
  if (!res.ok) throw new Error(`Failed to resume run: ${res.status}`);
}

export async function getRun(runId: string): Promise<{ runId: string; status: string; state: Record<string, unknown> }> {
  const res = await authedFetch(`/runs/${runId}`);
  if (!res.ok) throw new Error(`Failed to load run: ${res.status}`);
  return res.json();
}

/** EventSource (used by useRunEvents) cannot set custom request headers, so the API key is
 * appended as a query parameter here specifically — apps/api's auth middleware accepts either
 * the Authorization header or this query parameter uniformly (see apps/api/src/auth.ts). */
export function eventsUrl(runId: string): string {
  const apiKey = getApiKey();
  return `${withSession(`/runs/${runId}/events`)}&apiKey=${encodeURIComponent(apiKey ?? "")}`;
}
