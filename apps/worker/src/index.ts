import { createServer } from "node:http";
import { Pool } from "pg";
import type { EventBus } from "@opentalos/core-types";
import { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import { PostgresEventBus } from "@opentalos/postgres-tracing";
import { GraphRegistry, Worker } from "@opentalos/scheduler";
import { buildChatDemoAgentGraph, createChatDemoAgentToolRegistry } from "@opentalos/example-chat-demo-agent";

/** Builds and registers every graph this worker process knows how to run. Split out from the
 * bootstrap below so it can be exercised directly in tests without needing to start the
 * continuous polling loop or the health-check HTTP server. */
export function buildWorkerRegistry(eventBus: EventBus): GraphRegistry {
  const registry = new GraphRegistry();
  registry.register("chat-demo-agent", {
    buildGraph: buildChatDemoAgentGraph,
    buildDeps: () => ({ toolRegistry: createChatDemoAgentToolRegistry(), eventBus }),
  });
  return registry;
}

function isMain(): boolean {
  return process.argv[1] === new URL(import.meta.url).pathname;
}

if (isMain()) {
  const pool = new Pool({
    connectionString: process.env.DATABASE_URL ?? "postgres://postgres:postgres@localhost:5432/opentalos",
  });
  const checkpointStore = new PostgresCheckpointStore(pool);
  const eventBus = new PostgresEventBus(pool);
  const registry = buildWorkerRegistry(eventBus);

  const worker = new Worker(pool, registry, checkpointStore, {
    globalConcurrency: Number(process.env.WORKER_GLOBAL_CONCURRENCY ?? 10),
    tenantConcurrency: Number(process.env.WORKER_TENANT_CONCURRENCY ?? 5),
  });
  worker.start();
  console.log("apps/worker: started, polling for tasks...");

  const healthPort = Number(process.env.HEALTH_PORT ?? 3002);
  createServer((_req, res) => {
    res.writeHead(200, { "Content-Type": "text/plain" });
    res.end("ok");
  }).listen(healthPort, () => {
    console.log(`apps/worker: health check listening on :${healthPort}`);
  });

  process.on("SIGTERM", () => {
    worker.stop();
    process.exit(0);
  });
}
