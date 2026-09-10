import { jsonb, pgTable, serial, text, timestamp } from "drizzle-orm/pg-core";

export const traceEvents = pgTable("trace_events", {
  id: serial("id").primaryKey(),
  runId: text("run_id").notNull(),
  tenantId: text("tenant_id").notNull(),
  sessionId: text("session_id").notNull(),
  type: text("type").notNull(),
  payload: jsonb("payload"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});
