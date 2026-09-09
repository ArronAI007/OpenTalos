import type { MemoryRecord, MemoryStore, TenantContext } from "@opentalos/core-types";

export class InMemoryMemoryStore implements MemoryStore {
  private readonly data = new Map<string, unknown>();

  private scopedKey(key: string, ctx: TenantContext): string {
    return `${ctx.tenantId}:${ctx.sessionId}:${key}`;
  }

  async read(key: string, ctx: TenantContext): Promise<unknown | undefined> {
    return this.data.get(this.scopedKey(key, ctx));
  }

  async write(key: string, value: unknown, ctx: TenantContext): Promise<void> {
    this.data.set(this.scopedKey(key, ctx), value);
  }

  async search(query: string, ctx: TenantContext): Promise<MemoryRecord[]> {
    const prefix = `${ctx.tenantId}:${ctx.sessionId}:`;
    const lowerQuery = query.toLowerCase();
    const results: MemoryRecord[] = [];
    for (const [scopedKey, value] of this.data.entries()) {
      if (!scopedKey.startsWith(prefix)) continue;
      const haystack = JSON.stringify(value).toLowerCase();
      if (haystack.includes(lowerQuery)) {
        results.push({ key: scopedKey.slice(prefix.length), value });
      }
    }
    return results;
  }
}
