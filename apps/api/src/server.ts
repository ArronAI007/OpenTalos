import Fastify, { type FastifyInstance } from "fastify";
import type { Pool } from "pg";
import type { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import type { StoredTraceEvent } from "@opentalos/postgres-tracing";
import type { Scheduler } from "@opentalos/scheduler";
import { registerRunRoutes } from "./routes/runs.js";

export interface ServerDeps {
  pool: Pool;
  checkpointStore: PostgresCheckpointStore;
  scheduler: Scheduler;
  listEventsSince: (runId: string, afterId: number) => Promise<StoredTraceEvent[]>;
}

/** Factory instead of a module-level singleton so tests can inject a testcontainers Pool
 * without touching environment variables or binding a real network port (via Fastify's
 * `.inject()`). */
export function buildServer(deps: ServerDeps): FastifyInstance {
  const app = Fastify({ logger: false });
  registerRunRoutes(app, deps);
  return app;
}
