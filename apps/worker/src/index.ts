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
import {
  consolidateTenant,
  extractMemory,
  HttpMemoryStore,
  listMemorySummary,
  listTenantsWithPendingMemories,
} from "./memory-client.js";
import { createTenantConcurrencyResolver } from "./tenant-quota.js";

/** Builds and registers every graph this worker process knows how to run. Split out from the
 * bootstrap below so it can be exercised directly in tests without needing to start the
 * continuous polling loop or the health-check HTTP server. */
export function buildWorkerRegistry(eventBus: EventBus, modelProvider: ModelProvider, pool: Pool): GraphRegistry {
  const registry = new GraphRegistry();
  const skills = loadSkills(BUNDLED_SKILLS_DIR);
  const memoryStore = new HttpMemoryStore();
  const toolRegistryOptions = { modelProvider: process.env.MODEL_PROVIDER, skills, memoryStore };
  registry.register("chat-agent", {
    buildGraph: () =>
      buildChatAgentGraph(modelProvider, createChatAgentToolRegistry(toolRegistryOptions), listMemorySummary),
    buildDeps: () => ({ toolRegistry: createChatAgentToolRegistry(toolRegistryOptions), eventBus }),
  });
  return registry;
}

/** One consolidation pass across every tenant with pending raw memories. Exported (like
 * buildWorkerRegistry above) so it can be tested directly without needing a running timer. */
export async function runMemoryConsolidationSweep(pool: Pool, tenantStore: TenantStore): Promise<void> {
  const allTenants = await tenantStore.listTenants();
  const tenantIds = await listTenantsWithPendingMemories(allTenants.map((t) => t.id));
  for (const tenantId of tenantIds) {
    try {
      await consolidateTenant(tenantId);
    } catch (error) {
      console.error(`apps/worker: memory consolidation failed for tenant "${tenantId}": ${error instanceof Error ? error.message : String(error)}`);
    }
  }
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
  const registry = buildWorkerRegistry(eventBus, modelProvider, pool);

  const defaultTenantConcurrency = parsePositiveInt("WORKER_TENANT_CONCURRENCY", 5);
  const worker = new Worker(pool, registry, checkpointStore, {
    globalConcurrency: parsePositiveInt("WORKER_GLOBAL_CONCURRENCY", 10),
    tenantConcurrency: defaultTenantConcurrency,
    resolveTenantConcurrency: createTenantConcurrencyResolver(tenantStore, defaultTenantConcurrency),
    // Fire-and-forget: a failed/slow extraction must never affect the main run's own success, and
    // a process restart mid-extraction just loses that one turn's worth of memory — acceptable,
    // since memory is a nice-to-have on top of the core chat functionality, not load-bearing.
    //
    // The graphId check matters: onRunDone is a single, worker-wide hook, not scoped to any one
    // registered graph. Right now "chat-agent" is the only graph this Worker runs, so this guard
    // is a no-op in practice — but without it, registering a second graph in the future would
    // silently start casting ITS checkpoint.state to ChatState too.
    onRunDone: (checkpoint) => {
      if (checkpoint.graphId !== "chat-agent") return;
      const state = checkpoint.state as ChatState;
      void extractMemory({
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

  // 记忆整合是一类跟任务调度完全独立的定时循环。周期由 MEMORY_CONSOLIDATION_INTERVAL_MS 控制，
  // 默认 1 小时。失败只打日志，不影响下一次循环。跟 Worker.scheduleNextPoll 用的是同一种
  // setTimeout 自重排模式（而不是 setInterval）：只有上一轮 sweep 真正 settle 之后才会重新排下
  // 一轮，保证任意时刻最多只有一轮 sweep 在跑。
  const consolidationIntervalMs = parsePositiveInt("MEMORY_CONSOLIDATION_INTERVAL_MS", 3_600_000);
  let consolidationStopped = false;
  let consolidationTimer: ReturnType<typeof setTimeout> | undefined;
  function scheduleNextConsolidationSweep(delayMs: number): void {
    if (consolidationStopped) return;
    consolidationTimer = setTimeout(() => {
      runMemoryConsolidationSweep(pool, tenantStore)
        .catch((error) => {
          console.error(`apps/worker: memory consolidation sweep failed: ${error instanceof Error ? error.message : String(error)}`);
        })
        .finally(() => scheduleNextConsolidationSweep(consolidationIntervalMs));
    }, delayMs);
  }
  scheduleNextConsolidationSweep(consolidationIntervalMs);

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

  // Known, accepted gap: worker.stop() only cancels the NEXT poll tick — it doesn't wait for any
  // fire-and-forget extraction already in flight from onRunDone above. On a normal graceful
  // SIGTERM/SIGINT (not just a crash), pool.end() below can close the connection out from under
  // an in-flight extractMemory() call, surfacing as a network error logged via that callback's
  // own .catch() — expected noise on every graceful restart, not a real failure.
  async function shutdown(): Promise<void> {
    worker.stop();
    consolidationStopped = true;
    if (consolidationTimer) clearTimeout(consolidationTimer);
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
