import { eq, inArray, sql } from "drizzle-orm";
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
 * 全部租户 id 列表，传进来逐个检查。租户规模不大时这个 N+1 查询完全够用；如果未来租户规模变大，
 * 需要换一个不依赖逐租户扫描的机制。 */
export async function listTenantsWithUnconsolidatedRawMemories(pool: Pool, allTenantIds: string[]): Promise<string[]> {
  const db = drizzle(pool);
  const result: string[] = [];
  for (const tenantId of allTenantIds) {
    const hasWork = await db.transaction(async (tx) => {
      await tx.execute(sql`select set_config('app.tenant_id', ${tenantId}, true)`);
      const rows = await tx.select({ id: rawMemories.id }).from(rawMemories).where(eq(rawMemories.tenantId, tenantId)).limit(1);
      return rows.length > 0;
    });
    if (hasWork) result.push(tenantId);
  }
  return result;
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
    await tx.delete(rawMemories).where(inArray(rawMemories.id, ids));
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
    for (const entry of changes.newEntries) {
      await tx.insert(memories).values({ id: crypto.randomUUID(), tenantId, type: entry.type, title: entry.title, content: entry.content });
    }
    for (const update of changes.updates) {
      await tx
        .update(memories)
        .set({ content: update.content, updatedAt: new Date(), lastConfirmedAt: new Date() })
        .where(eq(memories.id, update.id));
    }
  });
}

export async function deleteMemories(pool: Pool, tenantId: string, ids: string[]): Promise<void> {
  if (ids.length === 0) return;
  const db = drizzle(pool);
  await db.transaction(async (tx) => {
    await tx.execute(sql`select set_config('app.tenant_id', ${tenantId}, true)`);
    await tx.delete(memories).where(inArray(memories.id, ids));
  });
}
