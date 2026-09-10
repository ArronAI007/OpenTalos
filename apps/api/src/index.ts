import { Pool } from "pg";
import { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import { PostgresEventBus, listEventsSince } from "@opentalos/postgres-tracing";
import { GraphRegistry, Scheduler } from "@opentalos/scheduler";
import { buildChatDemoAgentGraph, createChatDemoAgentToolRegistry } from "@opentalos/example-chat-demo-agent";
import { buildServer } from "./server.js";

/** Parses a positive-integer environment variable, throwing a clear error rather than
 * silently falling back to NaN (which would disable concurrency caps or break `.listen()`).
 * Mirrors apps/worker's parsePositiveInt — duplicated locally since there's no shared utils
 * package yet; a future refactor task can consolidate if a third copy comes up. */
function parsePositiveInt(envVar: string, defaultValue: number): number {
  const raw = process.env[envVar];
  if (raw === undefined) return defaultValue;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`Invalid ${envVar}: "${raw}" is not a positive number`);
  }
  return parsed;
}

const pool = new Pool({
  connectionString: process.env.DATABASE_URL ?? "postgres://postgres:postgres@localhost:5432/opentalos",
});
pool.on("error", (error) => {
  console.error(`apps/api: unexpected Postgres pool error: ${error.message}`);
});

const checkpointStore = new PostgresCheckpointStore(pool);
const eventBus = new PostgresEventBus(pool);
const registry = new GraphRegistry();
registry.register("chat-demo-agent", {
  buildGraph: buildChatDemoAgentGraph,
  buildDeps: () => ({ toolRegistry: createChatDemoAgentToolRegistry(), eventBus }),
});
const scheduler = new Scheduler(pool, registry, checkpointStore);

const app = buildServer({
  pool,
  checkpointStore,
  scheduler,
  listEventsSince: (runId, afterId) => listEventsSince(pool, runId, afterId),
});

const port = parsePositiveInt("PORT", 3001);
app.listen({ port, host: "0.0.0.0" }).then(() => {
  console.log(`apps/api: listening on :${port}`);
});

// No separate health-check endpoint here (unlike apps/worker): apps/api already has an easy,
// meaningful health check — any of its real REST routes responding is proof of life (e.g.
// GET /runs/some-id?sessionId=x, where even a 404 response means the process is up). This will
// be used directly as Playwright's `webServer` readiness check in a later task.
async function shutdown(): Promise<void> {
  await app.close();
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
