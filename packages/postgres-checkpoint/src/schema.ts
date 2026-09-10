import { jsonb, pgTable, text, timestamp } from "drizzle-orm/pg-core";

export const checkpoints = pgTable("checkpoints", {
  runId: text("run_id").primaryKey(),
  graphId: text("graph_id").notNull(),
  tenantId: text("tenant_id").notNull(),
  sessionId: text("session_id").notNull(),
  nodeCursor: jsonb("node_cursor").notNull(),
  state: jsonb("state").notNull(),
  pendingYields: jsonb("pending_yields").notNull(),
  status: text("status").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});
