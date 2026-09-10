import { eq } from "drizzle-orm";
import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import type { Pool } from "pg";
import { apiKeys, tenants } from "./schema.js";
import { generateApiKey, hashApiKey } from "./crypto.js";

export interface TenantRecord {
  id: string;
  name: string;
  status: "active" | "disabled";
  maxConcurrency: number | null;
  createdAt: string;
  updatedAt: string;
}

export interface ApiKeyRecord {
  id: string;
  tenantId: string;
  keyPrefix: string;
  status: "active" | "revoked";
  createdAt: string;
  lastUsedAt: string | null;
}

export type ApiKeyLookupResult =
  | { outcome: "valid"; tenant: TenantRecord }
  | { outcome: "invalid_key" }
  | { outcome: "tenant_disabled"; tenant: TenantRecord };

type TenantRow = typeof tenants.$inferSelect;
type ApiKeyRow = typeof apiKeys.$inferSelect;

export class TenantStore {
  private readonly db: NodePgDatabase;

  constructor(pool: Pool) {
    this.db = drizzle(pool);
  }

  async createTenant(name: string, maxConcurrency?: number): Promise<TenantRecord> {
    const id = crypto.randomUUID();
    const [row] = await this.db
      .insert(tenants)
      .values({ id, name, status: "active", maxConcurrency: maxConcurrency ?? null })
      .returning();
    return this.toTenantRecord(row);
  }

  async listTenants(): Promise<TenantRecord[]> {
    const rows = await this.db.select().from(tenants);
    return rows.map((row) => this.toTenantRecord(row));
  }

  async getTenant(tenantId: string): Promise<TenantRecord | undefined> {
    const rows = await this.db.select().from(tenants).where(eq(tenants.id, tenantId)).limit(1);
    return rows[0] ? this.toTenantRecord(rows[0]) : undefined;
  }

  async setTenantStatus(tenantId: string, status: "active" | "disabled"): Promise<void> {
    await this.db.update(tenants).set({ status, updatedAt: new Date() }).where(eq(tenants.id, tenantId));
  }

  async setTenantQuota(tenantId: string, maxConcurrency: number | null): Promise<void> {
    await this.db.update(tenants).set({ maxConcurrency, updatedAt: new Date() }).where(eq(tenants.id, tenantId));
  }

  async createApiKey(tenantId: string): Promise<{ id: string; rawKey: string; keyPrefix: string }> {
    const { id, rawKey, keyPrefix, keyHash } = generateApiKey();
    await this.db.insert(apiKeys).values({ id, tenantId, keyHash, keyPrefix, status: "active" });
    return { id, rawKey, keyPrefix };
  }

  async listApiKeys(tenantId: string): Promise<ApiKeyRecord[]> {
    const rows = await this.db.select().from(apiKeys).where(eq(apiKeys.tenantId, tenantId));
    return rows.map((row) => this.toApiKeyRecord(row));
  }

  async revokeApiKey(keyId: string): Promise<void> {
    await this.db.update(apiKeys).set({ status: "revoked" }).where(eq(apiKeys.id, keyId));
  }

  /** Distinguishes "the key itself is invalid" (unknown, revoked, or — should never happen in
   * practice — pointing at a tenant row that no longer exists) from "the key is valid but its
   * tenant has since been disabled", so the caller (apps/api's auth middleware) can return 401
   * for the former and 403 for the latter: a request that already proved possession of a real
   * credential gets told plainly that it's blocked, rather than being lumped in with "you have
   * no idea what you're doing". */
  async lookupApiKey(rawKey: string): Promise<ApiKeyLookupResult> {
    const keyHash = hashApiKey(rawKey);
    const keyRows = await this.db.select().from(apiKeys).where(eq(apiKeys.keyHash, keyHash)).limit(1);
    const keyRow = keyRows[0];
    if (!keyRow || keyRow.status !== "active") {
      return { outcome: "invalid_key" };
    }

    const tenant = await this.getTenant(keyRow.tenantId);
    if (!tenant) {
      return { outcome: "invalid_key" };
    }

    await this.db.update(apiKeys).set({ lastUsedAt: new Date() }).where(eq(apiKeys.id, keyRow.id));

    if (tenant.status !== "active") {
      return { outcome: "tenant_disabled", tenant };
    }
    return { outcome: "valid", tenant };
  }

  /** Worker 的 resolveTenantConcurrency 用：查不到租户或该租户未设置配额时返回 undefined，
   * 调用方负责决定 fallback 到全局默认值。 */
  async getMaxConcurrency(tenantId: string): Promise<number | undefined> {
    const tenant = await this.getTenant(tenantId);
    return tenant?.maxConcurrency ?? undefined;
  }

  private toTenantRecord(row: TenantRow): TenantRecord {
    return {
      id: row.id,
      name: row.name,
      status: row.status as "active" | "disabled",
      maxConcurrency: row.maxConcurrency,
      createdAt: row.createdAt.toISOString(),
      updatedAt: row.updatedAt.toISOString(),
    };
  }

  private toApiKeyRecord(row: ApiKeyRow): ApiKeyRecord {
    return {
      id: row.id,
      tenantId: row.tenantId,
      keyPrefix: row.keyPrefix,
      status: row.status as "active" | "revoked",
      createdAt: row.createdAt.toISOString(),
      lastUsedAt: row.lastUsedAt ? row.lastUsedAt.toISOString() : null,
    };
  }
}
