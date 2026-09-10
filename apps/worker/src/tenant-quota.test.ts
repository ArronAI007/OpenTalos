import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";
import { TenantStore } from "@opentalos/postgres-tenancy";
import { createTenantConcurrencyResolver } from "./tenant-quota.js";

let container: StartedPostgreSqlContainer;
let pool: Pool;
let tenantStore: TenantStore;

beforeAll(async () => {
  container = await new PostgreSqlContainer("postgres:16-alpine").start();
  pool = new Pool({ connectionString: container.getConnectionUri() });
  await pool.query(`
    CREATE TABLE tenants (
      id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL, max_concurrency INTEGER,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE api_keys (
      id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, key_hash TEXT NOT NULL, key_prefix TEXT NOT NULL,
      status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_used_at TIMESTAMPTZ
    );
  `);
  tenantStore = new TenantStore(pool);
}, 120_000);

afterAll(async () => {
  await pool.end();
  await container.stop();
});

describe("createTenantConcurrencyResolver", () => {
  it("returns the tenant's configured quota when one is set", async () => {
    const tenant = await tenantStore.createTenant("quota-resolver-tenant", 7);
    const resolve = createTenantConcurrencyResolver(tenantStore, 5);
    expect(await resolve(tenant.id)).toBe(7);
  });

  it("falls back to the provided default when the tenant has no quota set", async () => {
    const tenant = await tenantStore.createTenant("no-quota-resolver-tenant");
    const resolve = createTenantConcurrencyResolver(tenantStore, 5);
    expect(await resolve(tenant.id)).toBe(5);
  });

  it("falls back to the provided default for an unknown tenantId", async () => {
    const resolve = createTenantConcurrencyResolver(tenantStore, 5);
    expect(await resolve("does-not-exist")).toBe(5);
  });

  it("caches a resolved value for the configured TTL instead of re-querying every call", async () => {
    const tenant = await tenantStore.createTenant("cached-quota-tenant", 2);
    const resolve = createTenantConcurrencyResolver(tenantStore, 5, 60_000);
    expect(await resolve(tenant.id)).toBe(2);

    // Change the underlying quota directly — a cached resolver should NOT see this change until
    // its TTL expires, since the whole point is to avoid a database round trip on every single
    // poll cycle for every tenant that's ever appeared in a batch.
    await tenantStore.setTenantQuota(tenant.id, 99);
    expect(await resolve(tenant.id)).toBe(2);
  });
});
