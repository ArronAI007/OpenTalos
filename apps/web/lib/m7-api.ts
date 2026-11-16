export const M7_API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8400";

export interface PrivacySettings {
  enabled: boolean;
  fail_closed: boolean;
  placeholder_ttl_seconds: number;
}

export interface PrivacyRule {
  id: string;
  title: string;
  pattern: string;
  action: "mask" | "warn" | "block";
  category: string;
  builtin: boolean;
  enabled: boolean;
}

export interface PrivacyAuditEntry {
  id: string;
  request_id: string | null;
  scope: string;
  rule_id: string;
  category: string;
  action: string;
  placeholder: string | null;
  restored: boolean;
  details: Record<string, unknown>;
  created_at: string;
}

export interface SharingConfig {
  enabled: boolean;
  bind_host: string;
  port: number;
  exposure_warning_acknowledged: boolean;
  tls_mode: "off" | "custom" | "mtls";
  cert_file: string | null;
  key_file: string | null;
  ca_file: string | null;
  require_client_cert: boolean;
  warning: string;
}

export interface GatewayKey {
  id: string;
  name: string;
  key_prefix: string;
  status: string;
  scopes: string[];
  allowed_models: string[];
  allowed_accounts: string[];
  allowed_groups: string[];
  allowed_mcp_servers: string[];
  read_only: boolean;
  daily_requests: number | null;
  weekly_requests: number | null;
  monthly_requests: number | null;
  token_limit: number | null;
  cost_limit_micros: number | null;
  cache_limit: number | null;
  concurrency_limit: number | null;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
}

export interface CreatedGatewayKey extends GatewayKey {
  key: string;
}

export interface SubscriptionAccount {
  id: string;
  provider: string;
  name: string;
  source: string;
  signed_in: boolean;
  project_id: string | null;
  models: string[];
  quota: Record<string, unknown>;
  metadata: Record<string, unknown>;
  last_refreshed_at: string;
}

export interface WarmupSchedule {
  id: string;
  account_id: string;
  mode: "daily" | "reset";
  at_time: string;
  enabled: boolean;
  last_run_at: string | null;
  next_run_at: string;
}

export interface SearchKey {
  id: string;
  provider: string;
  name: string;
  api_key_masked: string;
  enabled: boolean;
  priority: number;
  successes: number;
  failures: number;
  refusals: number;
  cooldown_until: string | null;
  last_error: string | null;
}

export interface PluginRecord {
  id: string;
  name: string;
  version: string;
  type: string;
  runtime: string;
  enabled: boolean;
  integrity_hash: string;
  capabilities: string[];
  ui: {
    pages?: Array<{ id: string; title: string }>;
    slots?: Array<{ id: string; title: string }>;
  };
  description: string;
}

export interface DiscoveredPlugin {
  id: string;
  name: string;
  version: string;
  type: string;
  description: string;
  installed: boolean;
  path: string;
}

export interface MediaJob {
  id: string;
  job_id: string;
  kind: "image" | "video";
  status: string;
  prompt: string;
  mime_type: string | null;
  path: string | null;
  progress: number;
  metadata: Record<string, unknown>;
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

export async function getPrivacySettings(): Promise<PrivacySettings> {
  return fetchJson(`${M7_API_URL}/api/m7/privacy/settings`, {
    cache: "no-store",
  });
}

export async function updatePrivacySettings(
  patch: Partial<PrivacySettings>
): Promise<PrivacySettings> {
  return fetchJson(`${M7_API_URL}/api/m7/privacy/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function listPrivacyRules(): Promise<PrivacyRule[]> {
  return fetchJson<{ rules: PrivacyRule[] }>(
    `${M7_API_URL}/api/m7/privacy/rules`,
    { cache: "no-store" }
  ).then((data) => data.rules);
}

export async function savePrivacyRule(input: {
  id: string;
  title: string;
  pattern: string;
  action: "mask" | "warn" | "block";
  category?: string;
}): Promise<PrivacyRule> {
  return fetchJson(`${M7_API_URL}/api/m7/privacy/rules`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function deletePrivacyRule(ruleId: string): Promise<void> {
  const response = await fetch(
    `${M7_API_URL}/api/m7/privacy/rules/${encodeURIComponent(ruleId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) throw new Error(`API ${response.status} ${response.statusText}`);
}

export async function testPrivacy(
  text: string,
  scope = "ui-test"
): Promise<{ text: string; matches: unknown[]; warnings: unknown[] }> {
  return fetchJson(`${M7_API_URL}/api/m7/privacy/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, scope }),
  });
}

export async function listPrivacyAudit(): Promise<PrivacyAuditEntry[]> {
  return fetchJson<{ audit: PrivacyAuditEntry[] }>(
    `${M7_API_URL}/api/m7/privacy/audit`,
    { cache: "no-store" }
  ).then((data) => data.audit);
}

export async function getSharingConfig(): Promise<SharingConfig> {
  return fetchJson(`${M7_API_URL}/api/m7/sharing/config`, {
    cache: "no-store",
  });
}

export async function updateSharingConfig(
  patch: Partial<SharingConfig>
): Promise<SharingConfig> {
  const { warning, ...body } = patch;
  void warning;
  return fetchJson(`${M7_API_URL}/api/m7/sharing/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function listGatewayKeys(): Promise<GatewayKey[]> {
  return fetchJson<{ keys: GatewayKey[] }>(
    `${M7_API_URL}/api/m7/sharing/keys`,
    { cache: "no-store" }
  ).then((data) => data.keys);
}

export async function createGatewayKey(input: {
  name: string;
  scopes: string[];
  allowed_models?: string[];
  daily_requests?: number | null;
  concurrency_limit?: number | null;
}): Promise<CreatedGatewayKey> {
  return fetchJson(`${M7_API_URL}/api/m7/sharing/keys`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function rotateGatewayKey(keyId: string): Promise<CreatedGatewayKey> {
  return fetchJson(
    `${M7_API_URL}/api/m7/sharing/keys/${encodeURIComponent(keyId)}/rotate`,
    { method: "POST" }
  );
}

export async function revokeGatewayKey(keyId: string): Promise<void> {
  const response = await fetch(
    `${M7_API_URL}/api/m7/sharing/keys/${encodeURIComponent(keyId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) throw new Error(`API ${response.status} ${response.statusText}`);
}

export async function discoverSubscriptions(): Promise<SubscriptionAccount[]> {
  return fetchJson<{ accounts: SubscriptionAccount[] }>(
    `${M7_API_URL}/api/m7/subscriptions/discover`,
    { method: "POST" }
  ).then((data) => data.accounts);
}

export async function listSubscriptions(): Promise<SubscriptionAccount[]> {
  return fetchJson<{ accounts: SubscriptionAccount[] }>(
    `${M7_API_URL}/api/m7/subscriptions`,
    { cache: "no-store" }
  ).then((data) => data.accounts);
}

export async function refreshSubscription(
  accountId: string
): Promise<SubscriptionAccount> {
  return fetchJson(
    `${M7_API_URL}/api/m7/subscriptions/${encodeURIComponent(accountId)}/refresh`,
    { method: "POST" }
  );
}

export async function scheduleSubscriptionWarmup(input: {
  account_id: string;
  mode: "daily" | "reset";
  at_time: string;
}): Promise<WarmupSchedule> {
  return fetchJson(`${M7_API_URL}/api/m7/subscriptions/warmups`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function listSearchKeys(): Promise<SearchKey[]> {
  return fetchJson<{ keys: SearchKey[] }>(
    `${M7_API_URL}/api/m7/tools/search-keys`,
    { cache: "no-store" }
  ).then((data) => data.keys);
}

export async function createSearchKey(input: {
  provider: string;
  name: string;
  api_key: string;
  priority?: number;
}): Promise<SearchKey> {
  return fetchJson(`${M7_API_URL}/api/m7/tools/search-keys`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function setSearchKeyEnabled(
  keyId: string,
  enabled: boolean
): Promise<SearchKey> {
  return fetchJson(
    `${M7_API_URL}/api/m7/tools/search-keys/${encodeURIComponent(keyId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }
  );
}

export async function deleteSearchKey(keyId: string): Promise<void> {
  const response = await fetch(
    `${M7_API_URL}/api/m7/tools/search-keys/${encodeURIComponent(keyId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) throw new Error(`API ${response.status} ${response.statusText}`);
}

export async function listPlugins(): Promise<PluginRecord[]> {
  return fetchJson<{ plugins: PluginRecord[] }>(
    `${M7_API_URL}/api/m7/plugins`,
    { cache: "no-store" }
  ).then((data) => data.plugins);
}

export async function discoverPlugins(
  repository: string
): Promise<DiscoveredPlugin[]> {
  return fetchJson<{ plugins: DiscoveredPlugin[] }>(
    `${M7_API_URL}/api/m7/plugins/discover`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repository }),
    }
  ).then((data) => data.plugins);
}

export async function installPlugin(
  source: string,
  allowUpdate = false
): Promise<PluginRecord> {
  return fetchJson(`${M7_API_URL}/api/m7/plugins/install`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, allow_update: allowUpdate }),
  });
}

export async function setPluginEnabled(
  pluginId: string,
  enabled: boolean
): Promise<PluginRecord> {
  return fetchJson(`${M7_API_URL}/api/m7/plugins/${encodeURIComponent(pluginId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
}

export async function verifyPlugin(pluginId: string): Promise<{ ok: boolean }> {
  return fetchJson(
    `${M7_API_URL}/api/m7/plugins/${encodeURIComponent(pluginId)}/verify`,
    { method: "POST" }
  );
}

export async function deletePlugin(pluginId: string): Promise<void> {
  const response = await fetch(
    `${M7_API_URL}/api/m7/plugins/${encodeURIComponent(pluginId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) throw new Error(`API ${response.status} ${response.statusText}`);
}

export async function listMediaJobs(): Promise<MediaJob[]> {
  return fetchJson<{ jobs: MediaJob[] }>(
    `${M7_API_URL}/api/m7/media/jobs`,
    { cache: "no-store" }
  ).then((data) => data.jobs);
}

export async function generateImage(prompt: string): Promise<MediaJob> {
  return fetchJson(`${M7_API_URL}/api/m7/media/images`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
}

export async function startVideo(prompt: string): Promise<MediaJob> {
  return fetchJson(`${M7_API_URL}/api/m7/media/videos`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
}

export function m7Endpoint(path: string): string {
  return `${M7_API_URL.replace(/\/$/, "")}/api/m7/${path.replace(/^\//, "")}`;
}
