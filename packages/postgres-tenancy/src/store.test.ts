import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";
import { TenantStore } from "./store.js";

let container: StartedPostgreSqlContainer;
let pool: Pool;
let store: TenantStore;

beforeAll(async () => {
  container = await new PostgreSqlContainer("postgres:16-alpine").start();
  pool = new Pool({ connectionString: container.getConnectionUri() });
  await pool.query(`
    CREATE TABLE tenants (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      status TEXT NOT NULL,
      max_concurrency INTEGER,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE api_keys (
      id TEXT PRIMARY KEY,
      tenant_id TEXT NOT NULL,
      key_hash TEXT NOT NULL,
      key_prefix TEXT NOT NULL,
      status TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      last_used_at TIMESTAMPTZ
    );
  `);
  store = new TenantStore(pool);
}, 120_000);

afterAll(async () => {
  await pool.end();
  await container.stop();
});

describe("TenantStore", () => {
  it("creates a tenant and round-trips it via getTenant", async () => {
    const created = await store.createTenant("acme");
    expect(created.status).toBe("active");
    expect(created.maxConcurrency).toBeNull();

    const loaded = await store.getTenant(created.id);
    expect(loaded?.name).toBe("acme");
  });

  it("creates a tenant with an initial quota", async () => {
    const created = await store.createTenant("acme-vip", 20);
    expect(created.maxConcurrency).toBe(20);
  });

  it("lists all tenants", async () => {
    const a = await store.createTenant("list-tenant-a");
    const b = await store.createTenant("list-tenant-b");
    const all = await store.listTenants();
    const ids = all.map((t) => t.id);
    expect(ids).toContain(a.id);
    expect(ids).toContain(b.id);
  });

  it("updates tenant status and quota", async () => {
    const created = await store.createTenant("mutable-tenant");
    await store.setTenantStatus(created.id, "disabled");
    await store.setTenantQuota(created.id, 7);
    const updated = await store.getTenant(created.id);
    expect(updated?.status).toBe("disabled");
    expect(updated?.maxConcurrency).toBe(7);
  });

  it("issues an API key whose raw value authenticates back to its tenant", async () => {
    const tenant = await store.createTenant("keyed-tenant");
    const { rawKey, keyPrefix } = await store.createApiKey(tenant.id);
    expect(rawKey.startsWith("tk_")).toBe(true);
    expect(keyPrefix.length).toBeGreaterThan(0);

    const result = await store.lookupApiKey(rawKey);
    expect(result.outcome).toBe("valid");
    if (result.outcome === "valid") {
      expect(result.tenant.id).toBe(tenant.id);
    }
  });

  it("lookupApiKey returns invalid_key for an unknown key", async () => {
    const result = await store.lookupApiKey("tk_does-not-exist");
    expect(result.outcome).toBe("invalid_key");
  });

  it("lookupApiKey returns invalid_key for a revoked key", async () => {
    const tenant = await store.createTenant("revoke-tenant");
    const { id: keyId, rawKey } = await store.createApiKey(tenant.id);
    await store.revokeApiKey(keyId);

    const result = await store.lookupApiKey(rawKey);
    expect(result.outcome).toBe("invalid_key");
  });

  it("lookupApiKey returns tenant_disabled for a valid key whose tenant has been disabled", async () => {
    const tenant = await store.createTenant("soon-disabled-tenant");
    const { rawKey } = await store.createApiKey(tenant.id);
    await store.setTenantStatus(tenant.id, "disabled");

    const result = await store.lookupApiKey(rawKey);
    expect(result.outcome).toBe("tenant_disabled");
  });

  it("listApiKeys never exposes the raw key or its hash", async () => {
    const tenant = await store.createTenant("list-keys-tenant");
    await store.createApiKey(tenant.id);
    const keys = await store.listApiKeys(tenant.id);
    expect(keys).toHaveLength(1);
    expect(keys[0]).not.toHaveProperty("rawKey");
    expect(keys[0]).not.toHaveProperty("keyHash");
    expect(keys[0].keyPrefix.length).toBeGreaterThan(0);
  });

  it("getMaxConcurrency returns undefined when no quota is set, and the number when one is", async () => {
    const withoutQuota = await store.createTenant("no-quota-tenant");
    expect(await store.getMaxConcurrency(withoutQuota.id)).toBeUndefined();

    const withQuota = await store.createTenant("with-quota-tenant", 3);
    expect(await store.getMaxConcurrency(withQuota.id)).toBe(3);
  });
});
