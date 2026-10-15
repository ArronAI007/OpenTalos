export const DEEPRESEARCH_URL = process.env.NEXT_PUBLIC_DEEPRESEARCH_URL || "http://localhost:8441";

export interface DeepResearchSource {
  title: string;
  url: string;
}

export interface DeepResearchTodo {
  id: number;
  query: string;
  status: "pending" | "running" | "completed" | "failed";
  summary: string | null;
  sources: DeepResearchSource[];
}

export interface DeepResearchRun {
  id: string;
  created_at: string;
  status: "running" | "completed" | "failed";
  topic: string;
  todos: DeepResearchTodo[];
  report: string | null;
  error: string | null;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(`API ${res.status} ${res.statusText}`);
  return res.json();
}

export async function createDeepResearchRun(topic: string): Promise<DeepResearchRun> {
  return fetchJson<DeepResearchRun>(`${DEEPRESEARCH_URL}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic }),
  });
}

export async function listDeepResearchRuns(): Promise<DeepResearchRun[]> {
  return fetchJson<{ runs: DeepResearchRun[] }>(`${DEEPRESEARCH_URL}/runs`, { cache: "no-store" }).then(
    (d) => d.runs
  );
}

export async function getDeepResearchRun(id: string): Promise<DeepResearchRun> {
  return fetchJson<DeepResearchRun>(`${DEEPRESEARCH_URL}/runs/${id}`, { cache: "no-store" });
}

export async function deleteDeepResearchRun(id: string): Promise<void> {
  const res = await fetch(`${DEEPRESEARCH_URL}/runs/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API ${res.status} ${res.statusText}`);
}

export function deepResearchStreamUrl(id: string): string {
  return `${DEEPRESEARCH_URL}/runs/${id}/stream`;
}
