import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";
import type { FastifyInstance } from "fastify";
import { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import { PostgresEventBus, listEventsSince } from "@opentalos/postgres-tracing";
import { GraphRegistry, Scheduler } from "@opentalos/scheduler";
import { TenantStore } from "@opentalos/postgres-tenancy";
import { buildChatDemoAgentGraph, createChatDemoAgentToolRegistry } from "@opentalos/example-chat-demo-agent";
import { buildServer } from "../server.js";

const ADMIN_API_KEY = "test-admin-key";

let container: StartedPostgreSqlContainer;
let pool: Pool;
let app: FastifyInstance;
let tenantStore: TenantStore;

beforeAll(async () => {
  container = await new PostgreSqlContainer("postgres:16-alpine").start();
  pool = new Pool({ connectionString: container.getConnectionUri() });
  await pool.query(`
    CREATE TABLE checkpoints (
      run_id TEXT PRIMARY KEY, graph_id TEXT NOT NULL, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
      node_cursor JSONB NOT NULL, state JSONB NOT NULL, pending_yields JSONB NOT NULL, status TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE tasks (
      id SERIAL PRIMARY KEY, run_id TEXT NOT NULL, graph_id TEXT NOT NULL, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
      kind TEXT NOT NULL, resume_value JSONB, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
      max_attempts INTEGER NOT NULL DEFAULT 3, timeout_ms INTEGER NOT NULL DEFAULT 30000, priority INTEGER NOT NULL DEFAULT 0,
      available_at TIMESTAMPTZ NOT NULL DEFAULT now(), locked_at TIMESTAMPTZ, error TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE trace_events (
      id SERIAL PRIMARY KEY, run_id TEXT NOT NULL, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
      type TEXT NOT NULL, payload JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
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
  const checkpointStore = new PostgresCheckpointStore(pool);
  const eventBus = new PostgresEventBus(pool);
  const registry = new GraphRegistry();
  registry.register("chat-demo-agent", {
    buildGraph: buildChatDemoAgentGraph,
    buildDeps: () => ({ toolRegistry: createChatDemoAgentToolRegistry(), eventBus }),
  });
  const scheduler = new Scheduler(pool, registry, checkpointStore);
  app = buildServer({
    pool,
    checkpointStore,
    scheduler,
    listEventsSince: (runId, afterId) => listEventsSince(pool, runId, afterId),
    tenantStore,
    adminApiKey: ADMIN_API_KEY,
  });
}, 120_000);

afterAll(async () => {
  await app.close();
  await pool.end();
  await container.stop();
});

function adminHeaders() {
  return { authorization: `Bearer ${ADMIN_API_KEY}` };
}

describe("admin routes auth", () => {
  it("returns 401 for a missing admin key", async () => {
    const res = await app.inject({ method: "GET", url: "/admin/tenants" });
    expect(res.statusCode).toBe(401);
  });

  it("returns 401 for a wrong admin key", async () => {
    const res = await app.inject({
      method: "GET",
      url: "/admin/tenants",
      headers: { authorization: "Bearer wrong-key" },
    });
    expect(res.statusCode).toBe(401);
  });

  it("a tenant's own API key cannot access admin routes", async () => {
    const tenant = await tenantStore.createTenant("not-an-admin");
    const { rawKey } = await tenantStore.createApiKey(tenant.id);
    const res = await app.inject({
      method: "GET",
      url: "/admin/tenants",
      headers: { authorization: `Bearer ${rawKey}` },
    });
    expect(res.statusCode).toBe(401);
  });
});

describe("POST /admin/tenants", () => {
  it("creates a tenant", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/admin/tenants",
      headers: adminHeaders(),
      payload: { name: "acme", maxConcurrency: 5 },
    });
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body.name).toBe("acme");
    expect(body.maxConcurrency).toBe(5);
    expect(body.status).toBe("active");
  });

  it("returns 400 for a missing name", async () => {
    const res = await app.inject({ method: "POST", url: "/admin/tenants", headers: adminHeaders(), payload: {} });
    expect(res.statusCode).toBe(400);
  });

  it("returns 400 for a non-finite maxConcurrency instead of leaking a DB error", async () => {
    // Sent as raw JSON text (not a JS object payload) because `Infinity` does not survive
    // JSON.stringify (it becomes `null`) — the real-world exploit is a raw JSON numeral like
    // `1e400`, which JSON.parse turns directly into Infinity server-side without ever round
    // tripping through JSON.stringify. Using a JS object here would falsely "pass" via the
    // pre-existing null check instead of actually exercising the Number.isFinite guard.
    const res = await app.inject({
      method: "POST",
      url: "/admin/tenants",
      headers: { ...adminHeaders(), "content-type": "application/json" },
      payload: '{"name":"infinity-test","maxConcurrency":1e400}',
    });
    expect(res.statusCode).toBe(400);
  });
});

describe("GET /admin/tenants", () => {
  it("lists created tenants", async () => {
    const created = await tenantStore.createTenant("list-me");
    const res = await app.inject({ method: "GET", url: "/admin/tenants", headers: adminHeaders() });
    expect(res.statusCode).toBe(200);
    const ids = res.json().map((t: { id: string }) => t.id);
    expect(ids).toContain(created.id);
  });
});

describe("PATCH /admin/tenants/:id", () => {
  it("updates status and quota", async () => {
    const tenant = await tenantStore.createTenant("patch-me");
    const res = await app.inject({
      method: "PATCH",
      url: `/admin/tenants/${tenant.id}`,
      headers: adminHeaders(),
      payload: { status: "disabled", maxConcurrency: 9 },
    });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.status).toBe("disabled");
    expect(body.maxConcurrency).toBe(9);
  });

  it("returns 404 for an unknown tenant", async () => {
    const res = await app.inject({
      method: "PATCH",
      url: "/admin/tenants/does-not-exist",
      headers: adminHeaders(),
      payload: { status: "disabled" },
    });
    expect(res.statusCode).toBe(404);
  });

  it("returns 400 for a non-finite maxConcurrency on update", async () => {
    // Raw JSON text for the same reason as the POST /admin/tenants version of this test above:
    // `Infinity` does not survive JSON.stringify (it becomes `null`, which is a legitimate
    // "clear the quota" value for PATCH), so a JS object payload would falsely pass this test
    // without ever exercising the Number.isFinite guard.
    const tenant = await tenantStore.createTenant("patch-infinity-test");
    const res = await app.inject({
      method: "PATCH",
      url: `/admin/tenants/${tenant.id}`,
      headers: { ...adminHeaders(), "content-type": "application/json" },
      payload: '{"maxConcurrency":1e400}',
    });
    expect(res.statusCode).toBe(400);
  });
});

describe("API key admin routes", () => {
  it("creates and lists an API key without ever exposing its raw value in the list endpoint", async () => {
    const tenant = await tenantStore.createTenant("key-admin-tenant");
    const createRes = await app.inject({
      method: "POST",
      url: `/admin/tenants/${tenant.id}/api-keys`,
      headers: adminHeaders(),
    });
    expect(createRes.statusCode).toBe(201);
    const created = createRes.json();
    expect(created.rawKey).toBeTypeOf("string");

    const listRes = await app.inject({
      method: "GET",
      url: `/admin/tenants/${tenant.id}/api-keys`,
      headers: adminHeaders(),
    });
    expect(listRes.statusCode).toBe(200);
    const listed = listRes.json();
    expect(listed).toHaveLength(1);
    expect(listed[0]).not.toHaveProperty("rawKey");
  });

  it("revokes a key so it can no longer authenticate", async () => {
    const tenant = await tenantStore.createTenant("revoke-admin-tenant");
    const { id: keyId, rawKey } = await tenantStore.createApiKey(tenant.id);

    const revokeRes = await app.inject({
      method: "DELETE",
      url: `/admin/api-keys/${keyId}`,
      headers: adminHeaders(),
    });
    expect(revokeRes.statusCode).toBe(204);

    const lookupResult = await tenantStore.lookupApiKey(rawKey);
    expect(lookupResult.outcome).toBe("invalid_key");
  });
});
