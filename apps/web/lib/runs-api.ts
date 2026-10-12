import { API_URL } from "./api";

export interface RunSummary {
  session_id: string;
  agent_name: string | null;
  agent_type: string | null;
  task_id: string | null;
  task_title: string | null;
  status: string;
  started_at: string | null;
  total_steps: number;
  total_tokens: number;
  total_cost: number;
  duration_seconds: number;
  model_calls: number;
}

export async function listRuns(limit = 50): Promise<RunSummary[]> {
  const res = await fetch(`${API_URL}/api/runs?limit=${limit}`, { cache: "no-store" });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(detail || `API ${res.status} ${res.statusText}`);
  }
  const data = await res.json();
  return data.runs;
}

export function reportUrl(sessionId: string): string {
  return `${API_URL}/api/runs/${sessionId}/report`;
}
