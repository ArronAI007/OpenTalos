import type { TenantStore } from "@opentalos/postgres-tenancy";

interface CacheEntry {
  value: number | undefined;
  expiresAt: number;
}

const DEFAULT_CACHE_TTL_MS = 5000;

/** Builds a `resolveTenantConcurrency` function (the hook `Worker` from `@opentalos/scheduler`
 * accepts) backed by a real `TenantStore`, with a short in-process TTL cache so a poll cycle
 * touching many tenants doesn't issue one database round trip per tenant per tick — each
 * resolved value (including "no quota set", cached as `undefined`) is reused for `cacheTtlMs`
 * before the next call re-queries. Cross-process cache consistency is intentionally not
 * addressed here — a brief staleness window after an admin changes a tenant's quota is an
 * accepted trade-off for this phase. */
export function createTenantConcurrencyResolver(
  tenantStore: TenantStore,
  defaultConcurrency: number,
  cacheTtlMs = DEFAULT_CACHE_TTL_MS,
): (tenantId: string) => Promise<number> {
  const cache = new Map<string, CacheEntry>();

  return async (tenantId: string): Promise<number> => {
    const cached = cache.get(tenantId);
    if (cached && cached.expiresAt > Date.now()) {
      return cached.value ?? defaultConcurrency;
    }
    const value = await tenantStore.getMaxConcurrency(tenantId);
    cache.set(tenantId, { value, expiresAt: Date.now() + cacheTtlMs });
    return value ?? defaultConcurrency;
  };
}
