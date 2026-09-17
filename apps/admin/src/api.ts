import type { ApiKeyRecord, TenantRecord, UserRecord } from "./types.js";

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

export async function listTenants(): Promise<TenantRecord[]> {
  const res = await adminFetch("/tenants");
  if (!res.ok) throw new Error(`Failed to list tenants: ${res.status}`);
  return res.json();
}

export async function createTenant(name: string, maxConcurrency?: number): Promise<TenantRecord> {
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
): Promise<TenantRecord> {
  const res = await adminFetch(`/tenants/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    // Surfaces the backend's specific message when there is one (e.g. the 409 guidance to use
    // the Users tab for a user-backed tenant) instead of a bare status code that leaves the admin
    // guessing why the toggle was refused.
    const body = await res.json().catch(() => ({}) as { error?: string });
    throw new Error(body.error ?? `Failed to update tenant: ${res.status}`);
  }
  return res.json();
}

export async function listApiKeys(tenantId: string): Promise<ApiKeyRecord[]> {
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

export async function listUsers(): Promise<UserRecord[]> {
  const res = await adminFetch("/users");
  if (!res.ok) throw new Error(`Failed to list users: ${res.status}`);
  return res.json();
}

export async function banUser(id: string): Promise<UserRecord> {
  const res = await adminFetch(`/users/${id}/ban`, { method: "PATCH" });
  if (!res.ok) throw new Error(`Failed to ban user: ${res.status}`);
  return res.json();
}

export async function unbanUser(id: string): Promise<UserRecord> {
  const res = await adminFetch(`/users/${id}/unban`, { method: "PATCH" });
  if (!res.ok) throw new Error(`Failed to unban user: ${res.status}`);
  return res.json();
}

export async function deleteUser(id: string): Promise<UserRecord> {
  const res = await adminFetch(`/users/${id}/delete`, { method: "PATCH" });
  if (!res.ok) throw new Error(`Failed to delete user: ${res.status}`);
  return res.json();
}
