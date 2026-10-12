import { API_URL } from "./api";

export interface Memory {
  id: number;
  content: string;
  importance: number;
  created_at: string;
  updated_at: string;
}

export interface ForgetMemoriesInput {
  strategy: "importance_based" | "time_based" | "capacity_based";
  threshold?: number;
  max_age_days?: number;
  max_count?: number;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(detail || `API ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function listMemories(): Promise<Memory[]> {
  return fetchJson<{ memories: Memory[] }>(`${API_URL}/api/memories`, { cache: "no-store" }).then(
    (d) => d.memories
  );
}

export async function deleteMemory(id: number): Promise<void> {
  const res = await fetch(`${API_URL}/api/memories/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API ${res.status} ${res.statusText}`);
}

export async function forgetMemories(input: ForgetMemoriesInput): Promise<number> {
  return fetchJson<{ deleted: number }>(`${API_URL}/api/memories/forget`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  }).then((d) => d.deleted);
}

export async function consolidateMemories(similarityThreshold = 0.9): Promise<number> {
  return fetchJson<{ merged: number }>(`${API_URL}/api/memories/consolidate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ similarity_threshold: similarityThreshold }),
  }).then((d) => d.merged);
}
