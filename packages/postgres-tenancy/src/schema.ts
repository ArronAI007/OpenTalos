import { integer, pgTable, text, timestamp } from "drizzle-orm/pg-core";

export const tenants = pgTable("tenants", {
  id: text("id").primaryKey(),
  name: text("name").notNull(),
  status: text("status").notNull(), // "active" | "disabled"
  maxConcurrency: integer("max_concurrency"), // null = 使用全局默认值
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

export const apiKeys = pgTable("api_keys", {
  id: text("id").primaryKey(),
  tenantId: text("tenant_id").notNull(),
  keyHash: text("key_hash").notNull(), // sha256(原始 key)，永不存明文
  keyPrefix: text("key_prefix").notNull(), // 原始 key 的前若干位，仅用于展示识别
  status: text("status").notNull(), // "active" | "revoked"
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  lastUsedAt: timestamp("last_used_at", { withTimezone: true }),
});
