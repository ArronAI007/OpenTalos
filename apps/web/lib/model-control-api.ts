import { API_URL } from "./api";

export interface ProviderPreset {
  id: string;
  label: string;
  backend: "openai-compatible" | "openai-responses" | "anthropic" | "gemini" | "mock";
  default_base_url: string | null;
  api_key_label: string;
  supports_model_discovery: boolean;
}

export interface ProviderAccount {
  id: string;
  created_at: string;
  updated_at: string;
  provider: string;
  name: string;
  backend: "openai-compatible" | "openai-responses" | "anthropic" | "gemini" | "mock";
  base_url: string | null;
  api_key_masked: string;
  proxy_url: string | null;
  enabled: boolean;
  model_count: number;
}

export interface ModelDescriptor {
  id: string;
  account_id: string;
  provider: string;
  account_name: string;
  model_id: string;
  display_name: string;
  protocol: string;
  context_window: number | null;
  supports_tools: boolean;
  supports_thinking: boolean;
  source: string;
  fetched_at: string;
}

export interface ControlPlaneProfile {
  id: string;
  name: string;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CreateProviderAccountInput {
  provider: string;
  name: string;
  backend: ProviderPreset["backend"];
  base_url?: string;
  api_key: string;
  proxy_url?: string;
}

export interface UpdateProviderAccountInput {
  name?: string;
  base_url?: string;
  api_key?: string;
  proxy_url?: string;
  enabled?: boolean;
}

export function modelControlPresetDefaults(preset: ProviderPreset): {
  backend: ProviderPreset["backend"];
  baseUrl: string;
} {
  return {
    backend: preset.backend,
    baseUrl: preset.default_base_url ?? "",
  };
}

export function modelControlModelsUrl(
  apiUrl: string,
  accountId?: string,
  query?: string
): string {
  const params = new URLSearchParams();
  if (accountId) params.set("account_id", accountId);
  if (query) params.set("q", query);
  const suffix = params.size ? `?${params.toString()}` : "";
  return `${apiUrl.replace(/\/$/, "")}/api/model-control/models${suffix}`;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = data && typeof data.detail === "string" ? data.detail : null;
    throw new Error(detail ?? `API ${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export async function listModelControlPresets(): Promise<ProviderPreset[]> {
  return fetchJson<{ presets: ProviderPreset[] }>(
    `${API_URL}/api/model-control/presets`,
    { cache: "no-store" }
  ).then((data) => data.presets);
}

export async function listProviderAccounts(): Promise<ProviderAccount[]> {
  return fetchJson<{ accounts: ProviderAccount[] }>(
    `${API_URL}/api/model-control/accounts`,
    { cache: "no-store" }
  ).then((data) => data.accounts);
}

export async function createProviderAccount(
  input: CreateProviderAccountInput
): Promise<ProviderAccount> {
  return fetchJson<ProviderAccount>(`${API_URL}/api/model-control/accounts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function updateProviderAccount(
  accountId: string,
  input: UpdateProviderAccountInput
): Promise<ProviderAccount> {
  return fetchJson<ProviderAccount>(
    `${API_URL}/api/model-control/accounts/${accountId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }
  );
}

export async function deleteProviderAccount(accountId: string): Promise<void> {
  const response = await fetch(
    `${API_URL}/api/model-control/accounts/${accountId}`,
    { method: "DELETE" }
  );
  if (!response.ok) throw new Error(`API ${response.status} ${response.statusText}`);
}

export async function discoverProviderModels(
  accountId: string
): Promise<ModelDescriptor[]> {
  return fetchJson<{ models: ModelDescriptor[] }>(
    `${API_URL}/api/model-control/accounts/${accountId}/discover`,
    { method: "POST" }
  ).then((data) => data.models);
}

export async function listControlPlaneModels(
  accountId?: string,
  query?: string
): Promise<ModelDescriptor[]> {
  return fetchJson<{ models: ModelDescriptor[] }>(
    modelControlModelsUrl(API_URL, accountId, query),
    { cache: "no-store" }
  ).then((data) => data.models);
}

export async function importLegacyProviderConfigs(): Promise<number> {
  return fetchJson<{ imported: number }>(
    `${API_URL}/api/model-control/imports/legacy`,
    { method: "POST" }
  ).then((data) => data.imported);
}

export async function listControlPlaneProfiles(): Promise<ControlPlaneProfile[]> {
  return fetchJson<{ profiles: ControlPlaneProfile[] }>(
    `${API_URL}/api/model-control/profiles`,
    { cache: "no-store" }
  ).then((data) => data.profiles);
}

export async function saveControlPlaneProfile(
  name: string,
  payload: Record<string, unknown>
): Promise<ControlPlaneProfile> {
  return fetchJson<ControlPlaneProfile>(`${API_URL}/api/model-control/profiles`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, payload }),
  });
}

export async function deleteControlPlaneProfile(profileId: string): Promise<void> {
  const response = await fetch(`${API_URL}/api/model-control/profiles/${profileId}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(`API ${response.status} ${response.statusText}`);
}
