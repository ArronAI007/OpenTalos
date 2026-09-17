import Fastify, { type FastifyInstance } from "fastify";
import type { Pool } from "pg";
import type { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import type { StoredTraceEvent } from "@opentalos/postgres-tracing";
import type { Scheduler } from "@opentalos/scheduler";
import type { TenantStore, UserStore } from "@opentalos/postgres-tenancy";
import { registerRunRoutes } from "./routes/runs.js";
import { registerAdminRoutes } from "./routes/admin.js";
import { registerAuthRoutes } from "./routes/auth.js";
import { createAdminAuthHook, createTenantAuthHook } from "./auth.js";

export interface ServerDeps {
  pool: Pool;
  checkpointStore: PostgresCheckpointStore;
  scheduler: Scheduler;
  listEventsSince: (runId: string, afterId: number) => Promise<StoredTraceEvent[]>;
  tenantStore: TenantStore;
  userStore: UserStore;
  adminApiKey: string;
}

/** Factory instead of a module-level singleton so tests can inject a testcontainers Pool
 * without touching environment variables or binding a real network port (via Fastify's
 * `.inject()`). */
export function buildServer(deps: ServerDeps): FastifyInstance {
  // Fastify's default bodyLimit is 1MB — too small for a chat message carrying base64-encoded
  // image attachments (see POST /runs's own per-image/per-message size caps in routes/runs.ts,
  // which are the real UX-facing limits; this is just a generous outer safety net so Fastify
  // itself never rejects a within-limits request before it even reaches that validation).
  const app = Fastify({ logger: false, bodyLimit: 20 * 1024 * 1024 });

  // Fastify's encapsulation model: a hook added with addHook() inside a register() callback
  // only applies to routes registered within that SAME encapsulated context, not the parent app
  // or sibling registrations — this is what lets /runs*, /admin/* and /auth/* have independent
  // (or in /auth/*'s case, absent) auth checks without any of them leaking into the others.
  app.register(async (tenantScope) => {
    tenantScope.addHook("preHandler", createTenantAuthHook(deps.tenantStore));
    registerRunRoutes(tenantScope, deps);
  });

  app.register(
    async (adminScope) => {
      adminScope.addHook("preHandler", createAdminAuthHook(deps.adminApiKey));
      registerAdminRoutes(adminScope, { tenantStore: deps.tenantStore, userStore: deps.userStore });
    },
    { prefix: "/admin" },
  );

  // No preHandler here — registration/login are how a client obtains credentials in the first
  // place, so requiring one would be a contradiction.
  app.register(async (authScope) => {
    registerAuthRoutes(authScope, { userStore: deps.userStore });
  });

  return app;
}
