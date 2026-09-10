import type { FastifyInstance } from "fastify";
import type { TenantStore } from "@opentalos/postgres-tenancy";

export interface AdminRouteDeps {
  tenantStore: TenantStore;
}

interface CreateTenantBody {
  name?: string;
  maxConcurrency?: number;
}

interface UpdateTenantBody {
  status?: string;
  maxConcurrency?: number | null;
}

export function registerAdminRoutes(app: FastifyInstance, deps: AdminRouteDeps): void {
  const { tenantStore } = deps;

  app.post<{ Body: CreateTenantBody }>("/tenants", async (request, reply) => {
    const name = request.body?.name;
    if (typeof name !== "string" || name.trim().length === 0) {
      return reply.code(400).send({ error: "name body field is required and must be a non-empty string" });
    }
    const maxConcurrency = request.body?.maxConcurrency;
    if (
      maxConcurrency !== undefined &&
      (typeof maxConcurrency !== "number" || !Number.isFinite(maxConcurrency) || maxConcurrency <= 0)
    ) {
      return reply.code(400).send({ error: "maxConcurrency must be a positive number if provided" });
    }
    const tenant = await tenantStore.createTenant(name, maxConcurrency);
    return reply.code(201).send(tenant);
  });

  app.get("/tenants", async (_request, reply) => {
    return reply.send(await tenantStore.listTenants());
  });

  app.patch<{ Params: { id: string }; Body: UpdateTenantBody }>("/tenants/:id", async (request, reply) => {
    const tenant = await tenantStore.getTenant(request.params.id);
    if (!tenant) {
      return reply.code(404).send({ error: `Tenant "${request.params.id}" not found` });
    }

    if (request.body?.status !== undefined) {
      if (request.body.status !== "active" && request.body.status !== "disabled") {
        return reply.code(400).send({ error: 'status must be "active" or "disabled"' });
      }
      await tenantStore.setTenantStatus(request.params.id, request.body.status);
    }

    if (request.body?.maxConcurrency !== undefined) {
      const maxConcurrency = request.body.maxConcurrency;
      if (
        maxConcurrency !== null &&
        (typeof maxConcurrency !== "number" || !Number.isFinite(maxConcurrency) || maxConcurrency <= 0)
      ) {
        return reply.code(400).send({ error: "maxConcurrency must be a positive number or null" });
      }
      await tenantStore.setTenantQuota(request.params.id, maxConcurrency);
    }

    return reply.send(await tenantStore.getTenant(request.params.id));
  });

  app.post<{ Params: { id: string } }>("/tenants/:id/api-keys", async (request, reply) => {
    const tenant = await tenantStore.getTenant(request.params.id);
    if (!tenant) {
      return reply.code(404).send({ error: `Tenant "${request.params.id}" not found` });
    }
    return reply.code(201).send(await tenantStore.createApiKey(request.params.id));
  });

  app.get<{ Params: { id: string } }>("/tenants/:id/api-keys", async (request, reply) => {
    const tenant = await tenantStore.getTenant(request.params.id);
    if (!tenant) {
      return reply.code(404).send({ error: `Tenant "${request.params.id}" not found` });
    }
    return reply.send(await tenantStore.listApiKeys(request.params.id));
  });

  app.delete<{ Params: { id: string } }>("/api-keys/:id", async (request, reply) => {
    await tenantStore.revokeApiKey(request.params.id);
    return reply.code(204).send();
  });
}
