import { API_URL } from "./api";

export interface MCPToolInfo {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface MCPServer {
  id: string;
  created_at: string;
  name: string;
  transport: "stdio" | "http";
  config: { command?: string; args?: string[]; url?: string };
  enabled: boolean;
  cached_tools: MCPToolInfo[];
  last_error: string | null;
}

export interface CreateMCPServerInput {
  name: string;
  transport: "stdio" | "http";
  command?: string;
  args?: string[];
  url?: string;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(detail || `API ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function createMCPServer(input: CreateMCPServerInput): Promise<MCPServer> {
  return fetchJson<MCPServer>(`${API_URL}/api/mcp/servers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function listMCPServers(): Promise<MCPServer[]> {
  return fetchJson<{ servers: MCPServer[] }>(`${API_URL}/api/mcp/servers`, { cache: "no-store" }).then(
    (d) => d.servers
  );
}

export async function setMCPServerEnabled(id: string, enabled: boolean): Promise<MCPServer> {
  return fetchJson<MCPServer>(`${API_URL}/api/mcp/servers/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
}

export async function refreshMCPServer(id: string): Promise<MCPServer> {
  return fetchJson<MCPServer>(`${API_URL}/api/mcp/servers/${id}/refresh`, { method: "POST" });
}

export async function deleteMCPServer(id: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/mcp/servers/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API ${res.status} ${res.statusText}`);
}
