const AGENTRL_URL = process.env.NEXT_PUBLIC_AGENTRL_URL || "http://localhost:8420";

export interface AgentRLConfig {
  sft_samples: number;
  sft_steps: number;
  grpo_samples: number;
  grpo_steps: number;
}

export interface AgentRLComparison {
  question: string;
  before: string;
  after: string;
  expected: string;
}

export interface AgentRLRun {
  id: string;
  created_at: string;
  status: "running" | "completed" | "failed";
  config: AgentRLConfig;
  metrics: { sft_loss: number[]; grpo_reward: number[] };
  result: AgentRLComparison[] | null;
  error: string | null;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(`API ${res.status} ${res.statusText}`);
  return res.json();
}

export async function createAgentRLRun(config: AgentRLConfig): Promise<AgentRLRun> {
  return fetchJson<AgentRLRun>(`${AGENTRL_URL}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
}

export async function listAgentRLRuns(): Promise<AgentRLRun[]> {
  return fetchJson<{ runs: AgentRLRun[] }>(`${AGENTRL_URL}/runs`, { cache: "no-store" }).then((d) => d.runs);
}

export async function getAgentRLRun(id: string): Promise<AgentRLRun> {
  return fetchJson<AgentRLRun>(`${AGENTRL_URL}/runs/${id}`, { cache: "no-store" });
}

export async function deleteAgentRLRun(id: string): Promise<void> {
  const res = await fetch(`${AGENTRL_URL}/runs/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API ${res.status} ${res.statusText}`);
}
