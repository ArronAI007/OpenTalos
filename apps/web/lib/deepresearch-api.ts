import { API_URL } from "./api";

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
  return fetchJson<DeepResearchRun>(`${API_URL}/api/deepresearch/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic }),
  });
}

export async function listDeepResearchRuns(): Promise<DeepResearchRun[]> {
  return fetchJson<{ runs: DeepResearchRun[] }>(`${API_URL}/api/deepresearch/runs`, { cache: "no-store" }).then(
    (d) => d.runs
  );
}

export async function getDeepResearchRun(id: string): Promise<DeepResearchRun> {
  return fetchJson<DeepResearchRun>(`${API_URL}/api/deepresearch/runs/${id}`, { cache: "no-store" });
}

export async function deleteDeepResearchRun(id: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/deepresearch/runs/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API ${res.status} ${res.statusText}`);
}

export function deepResearchStreamUrl(id: string): string {
  return `${API_URL}/api/deepresearch/runs/${id}/stream`;
}
