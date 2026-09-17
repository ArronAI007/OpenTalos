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

export const users = pgTable("users", {
  id: text("id").primaryKey(),
  tenantId: text("tenant_id").notNull(), // 1:1 绑定一个自动创建的专属 tenant（唯一性由 DDL 里的 UNIQUE 约束保证，不在这里的 drizzle schema 定义里声明——这个仓库的 DDL 都是手写 SQL，schema.ts 只用来做类型安全的查询构建，不负责生成建表语句）
  username: text("username").notNull(), // 大小写不敏感的唯一性同样由 DDL 里 `lower(username)` 的唯一索引保证
  passwordHash: text("password_hash").notNull(),
  status: text("status").notNull(), // "active" | "banned" | "deleted"
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});
