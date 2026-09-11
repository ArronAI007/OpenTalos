import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { config as loadDotenv } from "dotenv";
import { Pool } from "pg";
import { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import { PostgresEventBus, listEventsSince } from "@opentalos/postgres-tracing";
import { GraphRegistry, Scheduler } from "@opentalos/scheduler";
import { TenantStore } from "@opentalos/postgres-tenancy";
import { buildChatAgentGraph, createChatAgentToolRegistry } from "@opentalos/chat-agent";
import { createModelProviderFromEnv } from "@opentalos/model-providers";
import { buildServer } from "./server.js";
import { closeAllSseConnections } from "./routes/runs.js";

// Repo-root .env, shared by apps/worker and apps/api, so MODEL_* vars don't silently diverge
// between the two processes (see README). Only fills in vars not already set in the
// environment, so an explicit `FOO=bar pnpm start` still wins over the .env file.
loadDotenv({ path: resolve(dirname(fileURLToPath(import.meta.url)), "../../../.env") });

/** Parses a positive-integer environment variable, throwing a clear error rather than
 * silently falling back to NaN (which would disable concurrency caps or break `.listen()`). */
function parsePositiveInt(envVar: string, defaultValue: number): number {
  const raw = process.env[envVar];
  if (raw === undefined) return defaultValue;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`Invalid ${envVar}: "${raw}" is not a positive number`);
  }
  return parsed;
}

// No default: running with no admin protection at all would be a real security hole, not a
// convenience worth silently falling back for — fail fast and loud instead.
const adminApiKey = process.env.ADMIN_API_KEY;
if (!adminApiKey) {
  throw new Error("ADMIN_API_KEY environment variable is required");
}

const pool = new Pool({
  connectionString: process.env.DATABASE_URL ?? "postgres://postgres:postgres@localhost:5432/opentalos",
});
pool.on("error", (error) => {
  console.error(`apps/api: unexpected Postgres pool error: ${error.message}`);
});

const checkpointStore = new PostgresCheckpointStore(pool);
const eventBus = new PostgresEventBus(pool);
const tenantStore = new TenantStore(pool);
const modelProvider = createModelProviderFromEnv();
const registry = new GraphRegistry();
registry.register("chat-agent", {
  buildGraph: () => buildChatAgentGraph(modelProvider, createChatAgentToolRegistry()),
  buildDeps: () => ({ toolRegistry: createChatAgentToolRegistry(), eventBus }),
});
const scheduler = new Scheduler(pool, registry, checkpointStore);

const app = buildServer({
  pool,
  checkpointStore,
  scheduler,
  listEventsSince: (runId, afterId) => listEventsSince(pool, runId, afterId),
  tenantStore,
  adminApiKey,
});

const port = parsePositiveInt("PORT", 3001);
app.listen({ port, host: "0.0.0.0" }).then(() => {
  console.log(`apps/api: listening on :${port}`);
});

// No separate health-check endpoint here (unlike apps/worker): apps/api already has an easy,
// meaningful health check — any of its real REST routes responding is proof of life (e.g.
// GET /runs/some-id?sessionId=x, where even a 404 response means the process is up). This will
// be used directly as Playwright's `webServer` readiness check in a later task.
// Defense in depth: app.close() waits for all connections to finish naturally, but a hijacked
// SSE response (see routes/runs.ts) stays open until its run completes or the client
// disconnects. closeAllSseConnections() below proactively ends every tracked SSE stream before
// close() is even called, but this timeout guarantees shutdown proceeds regardless, in case any
// connection was somehow missed.
const APP_CLOSE_TIMEOUT_MS = 5000;

async function shutdown(): Promise<void> {
  closeAllSseConnections();
  await Promise.race([app.close(), new Promise((resolve) => setTimeout(resolve, APP_CLOSE_TIMEOUT_MS))]);
  await eventBus.flush();
  await pool.end();
  process.exit(0);
}

process.on("SIGTERM", () => {
  void shutdown();
});
process.on("SIGINT", () => {
  void shutdown();
});
