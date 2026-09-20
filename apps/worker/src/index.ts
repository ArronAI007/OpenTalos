import { createServer } from "node:http";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { config as loadDotenv } from "dotenv";
import { Pool } from "pg";
import type { EventBus, ModelProvider } from "@opentalos/core-types";
import { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import { PostgresEventBus } from "@opentalos/postgres-tracing";
import { TenantStore } from "@opentalos/postgres-tenancy";
import { GraphRegistry, Worker } from "@opentalos/scheduler";
import { buildChatAgentGraph, createChatAgentToolRegistry, type ChatState } from "@opentalos/chat-agent";
import { createModelProviderFromEnv } from "@opentalos/model-providers";
import { loadSkills, BUNDLED_SKILLS_DIR } from "@opentalos/skills";
import { extractMemory } from "@opentalos/memory-agent";
import { createTenantConcurrencyResolver } from "./tenant-quota.js";

/** Builds and registers every graph this worker process knows how to run. Split out from the
 * bootstrap below so it can be exercised directly in tests without needing to start the
 * continuous polling loop or the health-check HTTP server. */
export function buildWorkerRegistry(eventBus: EventBus, modelProvider: ModelProvider): GraphRegistry {
  const registry = new GraphRegistry();
  const skills = loadSkills(BUNDLED_SKILLS_DIR);
  const toolRegistryOptions = { modelProvider: process.env.MODEL_PROVIDER, skills };
  registry.register("chat-agent", {
    buildGraph: () => buildChatAgentGraph(modelProvider, createChatAgentToolRegistry(toolRegistryOptions)),
    buildDeps: () => ({ toolRegistry: createChatAgentToolRegistry(toolRegistryOptions), eventBus }),
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
  const modelProvider = createModelProviderFromEnv();
  const registry = buildWorkerRegistry(eventBus, modelProvider);

  const defaultTenantConcurrency = parsePositiveInt("WORKER_TENANT_CONCURRENCY", 5);
  const worker = new Worker(pool, registry, checkpointStore, {
    globalConcurrency: parsePositiveInt("WORKER_GLOBAL_CONCURRENCY", 10),
    tenantConcurrency: defaultTenantConcurrency,
    resolveTenantConcurrency: createTenantConcurrencyResolver(tenantStore, defaultTenantConcurrency),
    // Fire-and-forget: a failed/slow extraction must never affect the main run's own success, and
    // a process restart mid-extraction just loses that one turn's worth of memory — acceptable,
    // since memory is a nice-to-have on top of the core chat functionality, not load-bearing.
    onRunDone: (checkpoint) => {
      const state = checkpoint.state as ChatState;
      void extractMemory(pool, modelProvider, {
        tenantId: checkpoint.tenantId,
        sessionId: checkpoint.sessionId,
        runId: checkpoint.runId,
        userMessage: state.message,
        assistantReply: state.reply ?? "",
      }).catch((error) => {
        console.error(`apps/worker: memory extraction failed for run "${checkpoint.runId}": ${error instanceof Error ? error.message : String(error)}`);
      });
    },
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
