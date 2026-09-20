import { and, eq, inArray, sql } from "drizzle-orm";
import { drizzle } from "drizzle-orm/node-postgres";
import type { Pool } from "pg";
import { memories, rawMemories } from "./schema.js";

export type MemoryType = "profile" | "preference" | "context";

export interface RawMemoryRecord {
  id: string;
  tenantId: string;
  sessionId: string;
  runId: string;
  content: string;
  createdAt: Date;
}

export interface MemoryEntry {
  id: string;
  tenantId: string;
  type: MemoryType;
  title: string;
  content: string;
  createdAt: Date;
  updatedAt: Date;
  lastConfirmedAt: Date;
}

export interface NewMemory {
  type: MemoryType;
  title: string;
  content: string;
}

export interface MemoryUpdate {
  id: string;
  content: string;
}

/** 提取阶段（Phase 1）写入一条原始观察。跟 set_config 事务包装是因为这张表也在 RLS 保护下——
 * 见 scripts/migrations/2026-09-20-add-memories-rls.sql（Task 3）。 */
export async function insertRawMemory(
  pool: Pool,
  params: { tenantId: string; sessionId: string; runId: string; content: string },
): Promise<void> {
  const db = drizzle(pool);
  await db.transaction(async (tx) => {
    await tx.execute(sql`select set_config('app.tenant_id', ${params.tenantId}, true)`);
    await tx.insert(rawMemories).values({
      id: crypto.randomUUID(),
      tenantId: params.tenantId,
      sessionId: params.sessionId,
      runId: params.runId,
      content: params.content,
    });
  });
}

/** 找出"有未处理原始记忆"的全部租户。不能直接对 raw_memories 表做一次跨租户 DISTINCT 查询——
 * 那张表本身受 RLS 保护，在 opentalos_app 角色下任何没设置 app.tenant_id 的查询永远只返回空结果
 * （这是 RLS 该有的行为，不是 bug）。调用方（apps/worker 的定期整合循环，见 Task 7）先从
 * packages/postgres-tenancy 的 TenantStore.listTenants()（tenants 表明确排除在 RLS 范围之外）拿到
 * 全部租户 id 列表，传进来逐个检查。在几千个租户以内可以接受；如果这个定期扫描本身开始耗时明显
 * 变长（比如超过几秒），需要换一个不依赖逐租户扫描的机制。 */
export async function listTenantsWithUnconsolidatedRawMemories(pool: Pool, allTenantIds: string[]): Promise<string[]> {
  const db = drizzle(pool);
  const results = await Promise.all(
    allTenantIds.map(async (tenantId) => {
      const hasWork = await db.transaction(async (tx) => {
        await tx.execute(sql`select set_config('app.tenant_id', ${tenantId}, true)`);
        const rows = await tx.select({ id: rawMemories.id }).from(rawMemories).where(eq(rawMemories.tenantId, tenantId)).limit(1);
        return rows.length > 0;
      });
      return hasWork ? tenantId : null;
    }),
  );
  return results.filter((id): id is string => id !== null);
}

export async function listRawMemoriesForTenant(pool: Pool, tenantId: string): Promise<RawMemoryRecord[]> {
  const db = drizzle(pool);
  return db.transaction(async (tx) => {
    await tx.execute(sql`select set_config('app.tenant_id', ${tenantId}, true)`);
    return tx.select().from(rawMemories).where(eq(rawMemories.tenantId, tenantId));
  });
}

export async function deleteRawMemories(pool: Pool, tenantId: string, ids: string[]): Promise<void> {
  if (ids.length === 0) return;
  const db = drizzle(pool);
  await db.transaction(async (tx) => {
    await tx.execute(sql`select set_config('app.tenant_id', ${tenantId}, true)`);
    await tx.delete(rawMemories).where(and(eq(rawMemories.tenantId, tenantId), inArray(rawMemories.id, ids)));
  });
}

export async function listMemoriesForTenant(pool: Pool, tenantId: string): Promise<MemoryEntry[]> {
  const db = drizzle(pool);
  return db.transaction(async (tx) => {
    await tx.execute(sql`select set_config('app.tenant_id', ${tenantId}, true)`);
    const rows = await tx.select().from(memories).where(eq(memories.tenantId, tenantId));
    return rows.map((row) => ({ ...row, type: row.type as MemoryType }));
  });
}

/** 整合阶段（Phase 2）的批量新增/更新入口。newEntries 是全新记忆（分配新 id），updates 是对
 * 已有记忆的改写（只更新 content，同时刷新 updatedAt/lastConfirmedAt）。 */
export async function upsertMemories(
  pool: Pool,
  tenantId: string,
  changes: { newEntries: NewMemory[]; updates: MemoryUpdate[] },
): Promise<void> {
  const db = drizzle(pool);
  await db.transaction(async (tx) => {
    await tx.execute(sql`select set_config('app.tenant_id', ${tenantId}, true)`);
    // Deliberately no onConflictDoUpdate here (unlike store.ts's write()): concurrent consolidation
    // runs for the same tenant deciding the same title is "new" at the same time will throw on the
    // (tenantId, title) unique constraint rather than gracefully merging. Accepted for now — Task 7's
    // consolidation loop processes one tenant at a time from a single worker process, so this can't
    // actually happen yet; revisit if/when multiple worker instances run consolidation concurrently.
    for (const entry of changes.newEntries) {
      await tx.insert(memories).values({ id: crypto.randomUUID(), tenantId, type: entry.type, title: entry.title, content: entry.content });
    }
    for (const update of changes.updates) {
      await tx
        .update(memories)
        .set({ content: update.content, updatedAt: new Date(), lastConfirmedAt: new Date() })
        .where(and(eq(memories.tenantId, tenantId), eq(memories.id, update.id)));
    }
  });
}

export async function deleteMemories(pool: Pool, tenantId: string, ids: string[]): Promise<void> {
  if (ids.length === 0) return;
  const db = drizzle(pool);
  await db.transaction(async (tx) => {
    await tx.execute(sql`select set_config('app.tenant_id', ${tenantId}, true)`);
    await tx.delete(memories).where(and(eq(memories.tenantId, tenantId), inArray(memories.id, ids)));
  });
}
