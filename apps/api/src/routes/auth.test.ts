import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";
import type { FastifyInstance } from "fastify";
import { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import { PostgresEventBus, listEventsSince } from "@opentalos/postgres-tracing";
import { GraphRegistry, Scheduler } from "@opentalos/scheduler";
import { TenantStore, UserStore } from "@opentalos/postgres-tenancy";
import { buildChatAgentGraph, createChatAgentToolRegistry } from "@opentalos/chat-agent";
import { createMockProvider } from "@opentalos/model-providers";
import { buildServer } from "../server.js";

const ADMIN_API_KEY = "test-admin-key";

let container: StartedPostgreSqlContainer;
let pool: Pool;
let app: FastifyInstance;
let tenantStore: TenantStore;
let userStore: UserStore;

beforeAll(async () => {
  container = await new PostgreSqlContainer("postgres:16-alpine").start();
  pool = new Pool({ connectionString: container.getConnectionUri() });
  await pool.query(`
    CREATE TABLE checkpoints (
      run_id TEXT PRIMARY KEY, graph_id TEXT NOT NULL, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
      node_cursor JSONB NOT NULL, state JSONB NOT NULL, pending_yields JSONB NOT NULL, status TEXT NOT NULL,
      cancel_requested BOOLEAN NOT NULL DEFAULT false, steer_message TEXT, error TEXT,
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
    CREATE TABLE users (
      id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL UNIQUE, username TEXT NOT NULL, password_hash TEXT NOT NULL,
      status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX users_username_lower_idx ON users (lower(username));
  `);

  tenantStore = new TenantStore(pool);
  userStore = new UserStore(pool, tenantStore);
  const checkpointStore = new PostgresCheckpointStore(pool);
  const eventBus = new PostgresEventBus(pool);
  const registry = new GraphRegistry();
  const modelProvider = createMockProvider();
  registry.register("chat-agent", {
    buildGraph: () => buildChatAgentGraph(modelProvider, createChatAgentToolRegistry()),
    buildDeps: () => ({ toolRegistry: createChatAgentToolRegistry(), eventBus }),
  });
  const scheduler = new Scheduler(pool, registry, checkpointStore);
  app = buildServer({
    pool,
    checkpointStore,
    scheduler,
    listEventsSince: (runId, afterId, tenantId) => listEventsSince(pool, runId, afterId, tenantId),
    tenantStore,
    userStore,
    adminApiKey: ADMIN_API_KEY,
  });
}, 120_000);

afterAll(async () => {
  await app.close();
  await pool.end();
  await container.stop();
});

describe("POST /auth/register", () => {
  it("registers a new user and returns a working API key", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/auth/register",
      payload: { username: "newuser", password: "password123" },
    });
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body.apiKey).toBeTypeOf("string");

    const lookup = await tenantStore.lookupApiKey(body.apiKey);
    expect(lookup.outcome).toBe("valid");
  });

  it("rejects a username shorter than 3 characters", async () => {
    const res = await app.inject({ method: "POST", url: "/auth/register", payload: { username: "ab", password: "password123" } });
    expect(res.statusCode).toBe(400);
  });

  it("rejects a password shorter than 8 characters", async () => {
    const res = await app.inject({ method: "POST", url: "/auth/register", payload: { username: "shortpw", password: "short" } });
    expect(res.statusCode).toBe(400);
  });

  it("rejects a duplicate username with 409", async () => {
    await app.inject({ method: "POST", url: "/auth/register", payload: { username: "duplicate", password: "password123" } });
    const res = await app.inject({ method: "POST", url: "/auth/register", payload: { username: "duplicate", password: "different-pw" } });
    expect(res.statusCode).toBe(409);
  });

  it("does not require any auth header (public route)", async () => {
    const res = await app.inject({ method: "POST", url: "/auth/register", payload: { username: "no-auth-needed", password: "password123" } });
    expect(res.statusCode).toBe(201);
  });
});

describe("POST /auth/login", () => {
  it("logs in with correct credentials and returns a working API key", async () => {
    await app.inject({ method: "POST", url: "/auth/register", payload: { username: "loginuser", password: "correct-pw-123" } });
    const res = await app.inject({ method: "POST", url: "/auth/login", payload: { username: "loginuser", password: "correct-pw-123" } });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    const lookup = await tenantStore.lookupApiKey(body.apiKey);
    expect(lookup.outcome).toBe("valid");
  });

  it("returns 401 for a wrong password", async () => {
    await app.inject({ method: "POST", url: "/auth/register", payload: { username: "wrongpwuser", password: "correct-pw-123" } });
    const res = await app.inject({ method: "POST", url: "/auth/login", payload: { username: "wrongpwuser", password: "wrong-pw" } });
    expect(res.statusCode).toBe(401);
  });

  it("returns 401 for an unknown username", async () => {
    const res = await app.inject({ method: "POST", url: "/auth/login", payload: { username: "does-not-exist", password: "whatever123" } });
    expect(res.statusCode).toBe(401);
  });

  it("returns 403 for a banned user", async () => {
    const registerRes = await app.inject({ method: "POST", url: "/auth/register", payload: { username: "bannedviaauth", password: "password123" } });
    const { apiKey } = registerRes.json();
    const lookup = await tenantStore.lookupApiKey(apiKey);
    if (lookup.outcome !== "valid") throw new Error("setup failed");
    await userStore.setUserStatus((await userStore.listUsers()).find((u) => u.username === "bannedviaauth")!.id, "banned");
    await tenantStore.setTenantStatus(lookup.tenant.id, "disabled");

    const res = await app.inject({ method: "POST", url: "/auth/login", payload: { username: "bannedviaauth", password: "password123" } });
    expect(res.statusCode).toBe(403);
  });
});
