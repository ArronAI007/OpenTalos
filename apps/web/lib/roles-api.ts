import { API_URL } from "./api";

export interface AgentRole {
  id: string;
  created_at: string;
  name: string;
  description: string;
  peer_url: string;
  enabled: boolean;
}

export interface CreateAgentRoleInput {
  name: string;
  description: string;
  peer_url: string;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(detail || `API ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function createAgentRole(input: CreateAgentRoleInput): Promise<AgentRole> {
  return fetchJson<AgentRole>(`${API_URL}/api/roles`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function listAgentRoles(): Promise<AgentRole[]> {
  return fetchJson<{ roles: AgentRole[] }>(`${API_URL}/api/roles`, { cache: "no-store" }).then((d) => d.roles);
}

export async function setAgentRoleEnabled(id: string, enabled: boolean): Promise<AgentRole> {
  return fetchJson<AgentRole>(`${API_URL}/api/roles/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
}

export async function deleteAgentRole(id: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/roles/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API ${res.status} ${res.statusText}`);
}
