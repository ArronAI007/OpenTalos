import type { FastifyReply, FastifyRequest } from "fastify";
import { timingSafeEqual } from "node:crypto";
import type { TenantStore } from "@opentalos/postgres-tenancy";

export interface AuthenticatedTenant {
  tenantId: string;
}

declare module "fastify" {
  interface FastifyRequest {
    tenant?: AuthenticatedTenant;
  }
}

interface ApiKeyQuery {
  apiKey?: string;
}

function extractApiKey(request: FastifyRequest): string | undefined {
  const authHeader = request.headers.authorization;
  if (authHeader?.startsWith("Bearer ")) {
    return authHeader.slice("Bearer ".length);
  }
  // EventSource (used by apps/web's SSE endpoint) cannot set custom request headers, so the key
  // may also arrive as a query parameter — supported uniformly here (not just on the events
  // route) to keep this one auth check simple and consistent across every route.
  const query = request.query as ApiKeyQuery;
  if (typeof query.apiKey === "string" && query.apiKey.length > 0) {
    return query.apiKey;
  }
  return undefined;
}

/** Reads the tenant's request, attaches `request.tenant` on success. 401 for a missing or
 * genuinely invalid key (unknown/revoked); 403 for a key that's valid but whose tenant has since
 * been disabled — the request already proved possession of a real credential, so telling it
 * plainly that it's blocked doesn't leak anything a true attacker could exploit. */
export function createTenantAuthHook(tenantStore: TenantStore) {
  return async (request: FastifyRequest, reply: FastifyReply): Promise<void> => {
    const rawKey = extractApiKey(request);
    if (!rawKey) {
      return reply.code(401).send({ error: "Missing API key" });
    }
    const result = await tenantStore.lookupApiKey(rawKey);
    if (result.outcome === "invalid_key") {
      return reply.code(401).send({ error: "Invalid API key" });
    }
    if (result.outcome === "tenant_disabled") {
      return reply.code(403).send({ error: "Tenant is disabled" });
    }
    request.tenant = { tenantId: result.tenant.id };
  };
}

/** Reads `request.tenant`, set by the tenant-auth preHandler hook that always runs before any
 * route protected by it. Throwing here (rather than silently proceeding with an undefined
 * tenantId) surfaces a genuine wiring bug loudly if this is ever reached without that hook
 * having run, instead of masking it as a confusing downstream failure. */
export function requireTenantId(request: FastifyRequest): string {
  if (!request.tenant) {
    throw new Error("Route handler reached without an authenticated tenant — auth hook misconfigured");
  }
  return request.tenant.tenantId;
}

function safeEqual(a: string, b: string): boolean {
  const bufA = Buffer.from(a);
  const bufB = Buffer.from(b);
  if (bufA.length !== bufB.length) return false;
  return timingSafeEqual(bufA, bufB);
}

/** Protects /admin/* routes with a single bootstrap secret (the ADMIN_API_KEY environment
 * variable) — a separate, independent check from tenant API keys; a tenant's own key can never
 * satisfy this hook. */
export function createAdminAuthHook(adminApiKey: string) {
  return async (request: FastifyRequest, reply: FastifyReply): Promise<void> => {
    const authHeader = request.headers.authorization;
    const provided = authHeader?.startsWith("Bearer ") ? authHeader.slice("Bearer ".length) : undefined;
    if (!provided || !safeEqual(provided, adminApiKey)) {
      return reply.code(401).send({ error: "Missing or invalid admin API key" });
    }
  };
}
