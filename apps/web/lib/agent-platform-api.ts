export const AGENT_PLATFORM_API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8400";

export type AgentCompatibility = "native" | "manual";
export type AgentLibraryKind =
  | "instructions"
  | "mcp"
  | "skills"
  | "hooks"
  | "env"
  | "subagents"
  | "commands"
  | "plugins";

export interface AgentBinding {
  agent_id: string;
  model: string;
  shortlist: string[];
  routing_preference: string | null;
  updated_at: string;
}

export interface AgentPlatformAgent {
  id: string;
  name: string;
  commands: string[];
  config_format: string;
  compatibility: AgentCompatibility;
  compatibility_path: string;
  install_hint: string;
  supports_configuration: boolean;
  capabilities: string[];
  config_path: string | null;
  resource_paths: Record<string, string>;
  catalog_source: string;
  installed: boolean;
  version: string | null;
  install_path: string | null;
  install_source: string | null;
  platform: string | null;
  discovered_at?: string;
  configuration_ready: boolean;
  binding: AgentBinding | null;
}

export interface AgentModelOption {
  value: string;
  label: string;
  kind: "model" | "group";
  model_id: string | null;
  provider: string | null;
  account_id: string | null;
  account_name: string | null;
  protocol: string;
  context_window: number | null;
  supports_tools: boolean | null;
  eligible: boolean;
  reason: string | null;
}

export interface AgentConfigPreview {
  agent_id: string;
  path: string;
  existed: boolean;
  changed: boolean;
  before: string;
  after: string;
  diff: string;
}

export interface AgentPlatformProfile {
  id: string;
  name: string;
  payload: {
    bindings: Record<string, AgentBinding>;
  };
  created_at: string;
  updated_at: string;
}

export interface AgentLibraryItem {
  id: string;
  kind: AgentLibraryKind;
  name: string;
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  bindings: Array<{ item_id: string; agent_id: string; path: string; applied_at: string }>;
}

export interface AgentUpdatePlan {
  agent_id: string;
  installed: boolean;
  install_source: string | null;
  update_method?: string | null;
  command: string[] | null;
  display_command: string | null;
  install_hint: string;
  automatic: boolean;
}

export interface AgentLocalResource {
  id: string;
  kind: AgentLibraryKind;
  name: string;
  description: string;
  content: string;
  agent_id: string;
  agent_name: string;
  path: string;
  source: "local";
  metadata: Record<string, unknown>;
}

export interface AgentResourceIndex {
  home: string;
  resources: AgentLocalResource[];
  agents: Array<{
    id: string;
    name: string;
    version: string | null;
    compatibility: string | null;
    configuration_ready: boolean;
    capabilities: string[];
    resource_paths: Record<string, string>;
  }>;
}

export function agentCatalogUrl(
  baseUrl: string,
  options?: { installedOnly?: boolean; query?: string }
): string {
  const params = new URLSearchParams();
  if (options?.installedOnly) params.set("installed_only", "true");
  if (options?.query?.trim()) params.set("q", options.query.trim());
  const suffix = params.size ? `?${params.toString()}` : "";
  return `${baseUrl.replace(/\/$/, "")}/api/agent-platform/catalog${suffix}`;
}

async function fetchJson<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail =
      data && typeof data.detail === "string" ? data.detail : null;
    throw new Error(detail ?? `API ${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export async function listAgentCatalog(options?: {
  installedOnly?: boolean;
  query?: string;
}): Promise<AgentPlatformAgent[]> {
  return fetchJson<{ agents: AgentPlatformAgent[] }>(
    agentCatalogUrl(AGENT_PLATFORM_API_URL, options),
    { cache: "no-store" }
  ).then((data) => data.agents);
}

export async function discoverAgents(): Promise<AgentPlatformAgent[]> {
  return fetchJson<{ agents: AgentPlatformAgent[] }>(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/discover`,
    { method: "POST" }
  ).then((data) => data.agents);
}

export async function listAgentResources(): Promise<AgentResourceIndex> {
  return fetchJson<AgentResourceIndex>(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/resources`,
    { cache: "no-store" }
  );
}

export async function listAgentModels(agentId: string): Promise<AgentModelOption[]> {
  return fetchJson<{ models: AgentModelOption[] }>(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/agents/${encodeURIComponent(agentId)}/models`,
    { cache: "no-store" }
  ).then((data) => data.models);
}

export async function bindAgentModel(
  agentId: string,
  binding: { model: string; shortlist: string[]; routing_preference?: string | null }
): Promise<AgentBinding> {
  return fetchJson<AgentBinding>(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/agents/${encodeURIComponent(agentId)}/binding`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(binding),
    }
  );
}

export async function previewAgentConfiguration(
  agentId: string
): Promise<AgentConfigPreview> {
  return fetchJson<AgentConfigPreview>(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/agents/${encodeURIComponent(agentId)}/configuration/preview`,
    { method: "POST" }
  );
}

export async function applyAgentConfiguration(agentId: string): Promise<{
  status: string;
  agent_id: string;
  path: string;
}> {
  return fetchJson(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/agents/${encodeURIComponent(agentId)}/configuration/apply`,
    { method: "POST" }
  );
}

export async function restoreAgentConfiguration(agentId: string): Promise<{
  agent_id: string;
  restored: Array<{ path: string; restored: boolean; existed: boolean }>;
}> {
  return fetchJson(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/agents/${encodeURIComponent(agentId)}/restore`,
    { method: "POST" }
  );
}

export async function listAgentProfiles(): Promise<AgentPlatformProfile[]> {
  return fetchJson<{ profiles: AgentPlatformProfile[] }>(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/profiles`,
    { cache: "no-store" }
  ).then((data) => data.profiles);
}

export async function saveAgentProfile(name: string): Promise<AgentPlatformProfile> {
  return fetchJson<AgentPlatformProfile>(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/profiles`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }
  );
}

export async function applyAgentProfile(profileId: string): Promise<void> {
  await fetchJson(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/profiles/${encodeURIComponent(profileId)}/apply`,
    { method: "POST" }
  );
}

export async function deleteAgentProfile(profileId: string): Promise<void> {
  const response = await fetch(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/profiles/${encodeURIComponent(profileId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) throw new Error(`API ${response.status} ${response.statusText}`);
}

export async function listAgentLibrary(): Promise<AgentLibraryItem[]> {
  return fetchJson<{ items: AgentLibraryItem[] }>(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/library`,
    { cache: "no-store" }
  ).then((data) => data.items);
}

export async function createAgentLibraryItem(input: {
  kind: AgentLibraryKind;
  name: string;
  content: string;
  metadata?: Record<string, unknown>;
}): Promise<AgentLibraryItem> {
  return fetchJson<AgentLibraryItem>(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/library`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...input, metadata: input.metadata ?? {} }),
    }
  );
}

export async function deleteAgentLibraryItem(itemId: string): Promise<void> {
  const response = await fetch(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/library/${encodeURIComponent(itemId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) throw new Error(`API ${response.status} ${response.statusText}`);
}

export async function applyAgentLibraryItem(
  agentId: string,
  itemId: string
): Promise<void> {
  await fetchJson(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/agents/${encodeURIComponent(agentId)}/library/${encodeURIComponent(itemId)}/apply`,
    { method: "POST" }
  );
}

export async function removeAgentLibraryItem(
  agentId: string,
  itemId: string
): Promise<void> {
  await fetchJson(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/agents/${encodeURIComponent(agentId)}/library/${encodeURIComponent(itemId)}`,
    { method: "DELETE" }
  );
}

export async function getAgentUpdatePlan(agentId: string): Promise<AgentUpdatePlan> {
  return fetchJson<AgentUpdatePlan>(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/agents/${encodeURIComponent(agentId)}/update-plan`,
    { cache: "no-store" }
  );
}

export async function executeAgentUpdate(agentId: string): Promise<AgentUpdatePlan & {
  status: string;
  output: string;
}> {
  return fetchJson(
    `${AGENT_PLATFORM_API_URL}/api/agent-platform/agents/${encodeURIComponent(agentId)}/update?confirm=true`,
    { method: "POST" }
  );
}
