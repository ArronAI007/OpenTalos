import { integer, jsonb, pgTable, serial, text, timestamp } from "drizzle-orm/pg-core";

export const tasks = pgTable("tasks", {
  id: serial("id").primaryKey(),
  runId: text("run_id").notNull(),
  graphId: text("graph_id").notNull(),
  tenantId: text("tenant_id").notNull(),
  sessionId: text("session_id").notNull(),
  kind: text("kind").notNull(), // "start" | "resume"
  resumeValue: jsonb("resume_value"),
  status: text("status").notNull(), // "queued" | "running" | "done" | "failed"
  attempts: integer("attempts").notNull().default(0),
  maxAttempts: integer("max_attempts").notNull().default(3),
  timeoutMs: integer("timeout_ms").notNull().default(30_000),
  priority: integer("priority").notNull().default(0),
  availableAt: timestamp("available_at", { withTimezone: true }).notNull().defaultNow(),
  lockedAt: timestamp("locked_at", { withTimezone: true }),
  error: text("error"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});
