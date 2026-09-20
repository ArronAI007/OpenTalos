import { and, eq, ilike, or, sql } from "drizzle-orm";
import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import type { Pool } from "pg";
import type { MemoryRecord, MemoryStore, TenantContext } from "@opentalos/core-types";
import { memories } from "./schema.js";

const DEFAULT_TYPE = "context";

/** 实现 core-types 里已经定义好、但至今没有真实持久化实现的 MemoryStore 接口。关键点：只按
 * ctx.tenantId 过滤，故意忽略 ctx.sessionId —— 记忆本来就是要跨会话召回的，这是这次重设计跟旧的
 * InMemoryMemoryStore（把 sessionId 拼进 key，导致记忆困在单个会话内）最核心的区别。
 *
 * read/write 按 title === key 在该租户的 memories 表里查找/upsert 一行，保持接口完整可用；但注意
 * 本模块实际的写入路径（提取/整合，见 packages/memory-agent）不经过这两个方法 —— 它们走
 * bulk.ts 里更贴合批量操作需求的辅助函数。read/write 目前唯一的用途是保持接口完整，search()
 * 才是真正有调用方的方法（chat-agent 的 search_memory 工具，见 Task 8）。 */
export class PostgresMemoryStore implements MemoryStore {
  private readonly db: NodePgDatabase;

  constructor(pool: Pool) {
    this.db = drizzle(pool);
  }

  async read(key: string, ctx: TenantContext): Promise<unknown | undefined> {
    const rows = await this.db
      .select()
      .from(memories)
      .where(and(eq(memories.tenantId, ctx.tenantId), eq(memories.title, key)))
      .limit(1);
    return rows[0]?.content;
  }

  /** A real DB-level upsert via onConflictDoUpdate (targeting the memories_tenant_id_title_idx
   * unique index — see schema.ts) rather than a select-then-branch: two concurrent write() calls
   * for the same (tenantId, key) racing a plain SELECT-then-INSERT/UPDATE could both observe "not
   * found" and both INSERT, producing duplicate rows. A single atomic INSERT ... ON CONFLICT
   * closes that race entirely, matching how packages/postgres-checkpoint's save() upserts on
   * checkpoints.runId. */
  async write(key: string, value: unknown, ctx: TenantContext): Promise<void> {
    const content = typeof value === "string" ? value : JSON.stringify(value);
    await this.db.transaction(async (tx) => {
      await tx.execute(sql`select set_config('app.tenant_id', ${ctx.tenantId}, true)`);
      await tx
        .insert(memories)
        .values({
          id: crypto.randomUUID(),
          tenantId: ctx.tenantId,
          type: DEFAULT_TYPE,
          title: key,
          content,
        })
        .onConflictDoUpdate({
          target: [memories.tenantId, memories.title],
          set: { content, updatedAt: new Date() },
        });
    });
  }

  async search(query: string, ctx: TenantContext): Promise<MemoryRecord[]> {
    const rows = await this.db
      .select()
      .from(memories)
      .where(
        and(
          eq(memories.tenantId, ctx.tenantId),
          or(ilike(memories.title, `%${query}%`), ilike(memories.content, `%${query}%`)),
        ),
      );
    return rows.map((row) => ({ key: row.title, value: row.content }));
  }
}
