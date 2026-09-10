const ADMIN_KEY_STORAGE_KEY = "opentalos-admin-key";

export function getAdminKey(): string | null {
  return sessionStorage.getItem(ADMIN_KEY_STORAGE_KEY);
}

export function setAdminKey(key: string): void {
  sessionStorage.setItem(ADMIN_KEY_STORAGE_KEY, key);
}

export function clearAdminKey(): void {
  sessionStorage.removeItem(ADMIN_KEY_STORAGE_KEY);
}

export class AdminAuthError extends Error {
  constructor() {
    super("Admin key rejected");
    this.name = "AdminAuthError";
  }
}

async function adminFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const key = getAdminKey();
  const res = await fetch(`/admin${path}`, {
    ...init,
    headers: { ...init.headers, Authorization: `Bearer ${key}` },
  });
  if (res.status === 401) {
    clearAdminKey();
    throw new AdminAuthError();
  }
  return res;
}

export async function listTenants(): Promise<import("./types.js").TenantRecord[]> {
  const res = await adminFetch("/tenants");
  if (!res.ok) throw new Error(`Failed to list tenants: ${res.status}`);
  return res.json();
}

export async function createTenant(name: string, maxConcurrency?: number): Promise<import("./types.js").TenantRecord> {
  const res = await adminFetch("/tenants", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, maxConcurrency }),
  });
  if (!res.ok) throw new Error(`Failed to create tenant: ${res.status}`);
  return res.json();
}

export async function updateTenant(
  id: string,
  patch: { status?: "active" | "disabled"; maxConcurrency?: number | null },
): Promise<import("./types.js").TenantRecord> {
  const res = await adminFetch(`/tenants/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`Failed to update tenant: ${res.status}`);
  return res.json();
}

export async function listApiKeys(tenantId: string): Promise<import("./types.js").ApiKeyRecord[]> {
  const res = await adminFetch(`/tenants/${tenantId}/api-keys`);
  if (!res.ok) throw new Error(`Failed to list API keys: ${res.status}`);
  return res.json();
}

export async function createApiKey(tenantId: string): Promise<{ id: string; rawKey: string; keyPrefix: string }> {
  const res = await adminFetch(`/tenants/${tenantId}/api-keys`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to create API key: ${res.status}`);
  return res.json();
}

export async function revokeApiKey(keyId: string): Promise<void> {
  const res = await adminFetch(`/api-keys/${keyId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to revoke API key: ${res.status}`);
}
