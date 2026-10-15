import { API_URL } from "./api";

export interface ProviderConfig {
  id: string;
  created_at: string;
  name: string;
  purpose: "chat" | "embedding";
  backend: "anthropic" | "openai-compatible" | "mock" | null;
  base_url: string | null;
  api_key_masked: string;
  model_name: string;
  active: boolean;
}

export interface CreateProviderConfigInput {
  name: string;
  purpose: "chat" | "embedding";
  backend?: "anthropic" | "openai-compatible" | "mock";
  base_url?: string;
  api_key: string;
  model_name: string;
}

export interface UpdateProviderConfigInput {
  name?: string;
  base_url?: string;
  api_key?: string;
  model_name?: string;
  active?: boolean;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(detail || `API ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function createProviderConfig(input: CreateProviderConfigInput): Promise<ProviderConfig> {
  return fetchJson<ProviderConfig>(`${API_URL}/api/providers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function listProviderConfigs(purpose?: "chat" | "embedding"): Promise<ProviderConfig[]> {
  const query = purpose ? `?purpose=${purpose}` : "";
  return fetchJson<{ providers: ProviderConfig[] }>(`${API_URL}/api/providers${query}`, { cache: "no-store" }).then(
    (d) => d.providers
  );
}

export async function updateProviderConfig(id: string, input: UpdateProviderConfigInput): Promise<ProviderConfig> {
  return fetchJson<ProviderConfig>(`${API_URL}/api/providers/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function activateProviderConfig(id: string): Promise<ProviderConfig> {
  return updateProviderConfig(id, { active: true });
}

export async function deleteProviderConfig(id: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/providers/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API ${res.status} ${res.statusText}`);
}
