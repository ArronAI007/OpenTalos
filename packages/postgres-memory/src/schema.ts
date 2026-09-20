import { pgTable, text, timestamp, uniqueIndex } from "drizzle-orm/pg-core";

// 暂存区：提取阶段（Phase 1）写入的原始观察，整合阶段（Phase 2）消费后即删除，不留历史。
export const rawMemories = pgTable("raw_memories", {
  id: text("id").primaryKey(),
  tenantId: text("tenant_id").notNull(),
  sessionId: text("session_id").notNull(),
  runId: text("run_id").notNull(),
  content: text("content").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

// 正式记忆：整合阶段的产出，是召回时实际读取的表。
// tenant_id + title 上的唯一索引是 store.ts 里 write() 做 onConflictDoUpdate 原子 upsert 的基础，
// 防止并发 write() 同时读到"不存在"而各自 INSERT，产生重复行。
export const memories = pgTable(
  "memories",
  {
    id: text("id").primaryKey(),
    tenantId: text("tenant_id").notNull(),
    type: text("type").notNull(), // "profile" | "preference" | "context"
    scope: text("scope").notNull().default("private"), // 预留字段，本轮不做隔离逻辑
    title: text("title").notNull(),
    content: text("content").notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
    lastConfirmedAt: timestamp("last_confirmed_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => [uniqueIndex("memories_tenant_id_title_idx").on(table.tenantId, table.title)],
);
