import { createServer } from "node:http";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { config as loadDotenv } from "dotenv";
import { Pool } from "pg";
import type { EventBus } from "@opentalos/core-types";
import { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import { PostgresEventBus } from "@opentalos/postgres-tracing";
import { TenantStore } from "@opentalos/postgres-tenancy";
import { GraphRegistry, Worker } from "@opentalos/scheduler";
import { buildChatAgentGraph, createChatAgentToolRegistry } from "@opentalos/chat-agent";
import { createModelProviderFromEnv } from "@opentalos/model-providers";
import { createTenantConcurrencyResolver } from "./tenant-quota.js";

/** Builds and registers every graph this worker process knows how to run. Split out from the
 * bootstrap below so it can be exercised directly in tests without needing to start the
 * continuous polling loop or the health-check HTTP server. */
export function buildWorkerRegistry(eventBus: EventBus): GraphRegistry {
  const registry = new GraphRegistry();
  const modelProvider = createModelProviderFromEnv();
  registry.register("chat-agent", {
    buildGraph: () => buildChatAgentGraph(modelProvider, createChatAgentToolRegistry()),
    buildDeps: () => ({ toolRegistry: createChatAgentToolRegistry(), eventBus }),
  });
  return registry;
}

function isMain(): boolean {
  return import.meta.url === pathToFileURL(process.argv[1]).href;
}

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

if (isMain()) {
  // Repo-root .env, shared by apps/worker and apps/api, so MODEL_* vars don't silently diverge
  // between the two processes (see README). Only fills in vars not already set in the
  // environment, so an explicit `FOO=bar pnpm start` still wins over the .env file.
  loadDotenv({ path: resolve(dirname(fileURLToPath(import.meta.url)), "../../../.env") });

  const pool = new Pool({
    connectionString: process.env.DATABASE_URL ?? "postgres://postgres:postgres@localhost:5432/opentalos",
  });
  pool.on("error", (error) => {
    console.error(`apps/worker: unexpected Postgres pool error: ${error.message}`);
  });

  const checkpointStore = new PostgresCheckpointStore(pool);
  const tenantStore = new TenantStore(pool);
  const eventBus = new PostgresEventBus(pool);
  const registry = buildWorkerRegistry(eventBus);

  const defaultTenantConcurrency = parsePositiveInt("WORKER_TENANT_CONCURRENCY", 5);
  const worker = new Worker(pool, registry, checkpointStore, {
    globalConcurrency: parsePositiveInt("WORKER_GLOBAL_CONCURRENCY", 10),
    tenantConcurrency: defaultTenantConcurrency,
    resolveTenantConcurrency: createTenantConcurrencyResolver(tenantStore, defaultTenantConcurrency),
  });
  worker.start();
  console.log("apps/worker: started, polling for tasks...");

  const healthPort = parsePositiveInt("HEALTH_PORT", 3002);
  const healthServer = createServer((_req, res) => {
    res.writeHead(200, { "Content-Type": "text/plain" });
    res.end("ok");
  });
  healthServer.on("error", (error) => {
    console.error(`apps/worker: health check server error: ${error.message}`);
  });
  healthServer.listen(healthPort, () => {
    console.log(`apps/worker: health check listening on :${healthPort}`);
  });

  async function shutdown(): Promise<void> {
    worker.stop();
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
}
