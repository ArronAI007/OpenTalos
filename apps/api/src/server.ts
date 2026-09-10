import Fastify, { type FastifyInstance } from "fastify";
import type { Pool } from "pg";
import type { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import type { StoredTraceEvent } from "@opentalos/postgres-tracing";
import type { Scheduler } from "@opentalos/scheduler";
import type { TenantStore } from "@opentalos/postgres-tenancy";
import { registerRunRoutes } from "./routes/runs.js";
import { registerAdminRoutes } from "./routes/admin.js";
import { createAdminAuthHook, createTenantAuthHook } from "./auth.js";

export interface ServerDeps {
  pool: Pool;
  checkpointStore: PostgresCheckpointStore;
  scheduler: Scheduler;
  listEventsSince: (runId: string, afterId: number) => Promise<StoredTraceEvent[]>;
  tenantStore: TenantStore;
  adminApiKey: string;
}

/** Factory instead of a module-level singleton so tests can inject a testcontainers Pool
 * without touching environment variables or binding a real network port (via Fastify's
 * `.inject()`). */
export function buildServer(deps: ServerDeps): FastifyInstance {
  const app = Fastify({ logger: false });

  // Fastify's encapsulation model: a hook added with addHook() inside a register() callback
  // only applies to routes registered within that SAME encapsulated context, not the parent app
  // or sibling registrations — this is what lets /runs* and /admin/* have two completely
  // independent auth checks without either accidentally leaking into the other.
  app.register(async (tenantScope) => {
    tenantScope.addHook("preHandler", createTenantAuthHook(deps.tenantStore));
    registerRunRoutes(tenantScope, deps);
  });

  app.register(
    async (adminScope) => {
      adminScope.addHook("preHandler", createAdminAuthHook(deps.adminApiKey));
      registerAdminRoutes(adminScope, { tenantStore: deps.tenantStore });
    },
    { prefix: "/admin" },
  );

  return app;
}
