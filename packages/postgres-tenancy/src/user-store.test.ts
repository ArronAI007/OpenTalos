import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";
import { TenantStore } from "./store.js";
import { UserStore } from "./user-store.js";

let container: StartedPostgreSqlContainer;
let pool: Pool;
let tenantStore: TenantStore;
let userStore: UserStore;

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
    CREATE TABLE users (
      id TEXT PRIMARY KEY,
      tenant_id TEXT NOT NULL UNIQUE,
      username TEXT NOT NULL,
      password_hash TEXT NOT NULL,
      status TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX users_username_lower_idx ON users (lower(username));
  `);
  tenantStore = new TenantStore(pool);
  userStore = new UserStore(pool, tenantStore);
}, 120_000);

afterAll(async () => {
  await pool.end();
  await container.stop();
});

describe("UserStore.register", () => {
  it("creates a user with its own dedicated tenant and API key", async () => {
    const result = await userStore.register("alice", "correct-horse-battery");
    expect(result.outcome).toBe("created");
    if (result.outcome !== "created") return;
    expect(result.user.username).toBe("alice");
    expect(result.user.status).toBe("active");
    expect(result.rawApiKey.startsWith("tk_")).toBe(true);

    const tenant = await tenantStore.getTenant(result.user.tenantId);
    expect(tenant?.status).toBe("active");

    const lookup = await tenantStore.lookupApiKey(result.rawApiKey);
    expect(lookup.outcome).toBe("valid");
  });

  it("rejects a duplicate username (case-insensitive) and disables the orphaned tenant", async () => {
    const first = await userStore.register("bob", "password123");
    expect(first.outcome).toBe("created");

    const second = await userStore.register("BOB", "different-password");
    expect(second.outcome).toBe("username_taken");

    // No leftover active tenant from the failed attempt.
    const allTenants = await tenantStore.listTenants();
    const bobTenants = allTenants.filter((t) => t.name.includes("bob") || t.name.includes("BOB"));
    for (const tenant of bobTenants) {
      if (first.outcome === "created" && tenant.id === first.user.tenantId) continue; // the successful one
      expect(tenant.status).toBe("disabled");
    }
  });
});

describe("UserStore.login", () => {
  it("returns a fresh API key for correct credentials", async () => {
    await userStore.register("carol", "carol-password");
    const result = await userStore.login("carol", "carol-password");
    expect(result.outcome).toBe("success");
    if (result.outcome !== "success") return;
    const lookup = await tenantStore.lookupApiKey(result.rawApiKey);
    expect(lookup.outcome).toBe("valid");
  });

  it("logging in twice issues two different API keys, both valid", async () => {
    await userStore.register("dave", "dave-password");
    const first = await userStore.login("dave", "dave-password");
    const second = await userStore.login("dave", "dave-password");
    expect(first.outcome).toBe("success");
    expect(second.outcome).toBe("success");
    if (first.outcome !== "success" || second.outcome !== "success") return;
    expect(first.rawApiKey).not.toBe(second.rawApiKey);
    expect((await tenantStore.lookupApiKey(first.rawApiKey)).outcome).toBe("valid");
    expect((await tenantStore.lookupApiKey(second.rawApiKey)).outcome).toBe("valid");
  });

  it("rejects a wrong password", async () => {
    await userStore.register("erin", "erin-password");
    const result = await userStore.login("erin", "wrong-password");
    expect(result.outcome).toBe("invalid_credentials");
  });

  it("rejects an unknown username", async () => {
    const result = await userStore.login("nobody-registered", "whatever");
    expect(result.outcome).toBe("invalid_credentials");
  });

  it("username lookup is case-insensitive", async () => {
    await userStore.register("Frank", "frank-password");
    const result = await userStore.login("frank", "frank-password");
    expect(result.outcome).toBe("success");
  });

  it("rejects login for a banned user", async () => {
    const registered = await userStore.register("grace", "grace-password");
    if (registered.outcome !== "created") throw new Error("setup failed");
    await userStore.setUserStatus(registered.user.id, "banned");
    await tenantStore.setTenantStatus(registered.user.tenantId, "disabled");

    const result = await userStore.login("grace", "grace-password");
    expect(result.outcome).toBe("account_blocked");
  });
});

describe("UserStore admin operations", () => {
  it("lists all registered users", async () => {
    const registered = await userStore.register("henry", "henry-password");
    if (registered.outcome !== "created") throw new Error("setup failed");
    const all = await userStore.listUsers();
    const ids = all.map((u) => u.id);
    expect(ids).toContain(registered.user.id);
  });

  it("setUserStatus updates the status field", async () => {
    const registered = await userStore.register("iris", "iris-password");
    if (registered.outcome !== "created") throw new Error("setup failed");
    await userStore.setUserStatus(registered.user.id, "deleted");
    const loaded = await userStore.getUser(registered.user.id);
    expect(loaded?.status).toBe("deleted");
  });
});
