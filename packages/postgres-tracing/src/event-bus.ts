import { and, asc, eq, gt, sql } from "drizzle-orm";
import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import type { Pool } from "pg";
import type { EventBus, EventHandler, TraceEvent, TraceEventType } from "@opentalos/core-types";
import { traceEvents } from "./schema.js";

export interface StoredTraceEvent extends TraceEvent {
  id: number;
}

export class PostgresEventBus implements EventBus {
  private readonly db: NodePgDatabase;
  // EventBus.emit() is synchronous by interface — it can't await the insert. Chaining every
  // write onto this promise instead of firing them independently guarantees the INSERT
  // statements reach Postgres in the same order emit() was called, which is what makes the
  // auto-increment `id` a valid cursor for listEventsSince(). A failed write's .catch() below
  // resolves the chain (rather than rejecting it), so one bad write never blocks subsequent ones.
  private writeChain: Promise<void> = Promise.resolve();

  constructor(pool: Pool) {
    this.db = drizzle(pool);
  }

  emit(event: TraceEvent): void {
    this.writeChain = this.writeChain
      .then(() =>
        this.db.transaction(async (tx) => {
          await tx.execute(sql`select set_config('app.tenant_id', ${event.tenantId}, true)`);
          await tx.insert(traceEvents).values({
            runId: event.runId,
            tenantId: event.tenantId,
            sessionId: event.sessionId,
            type: event.type,
            payload: event.payload ?? null,
          });
        }),
      )
      .then(() => undefined)
      .catch((error) => {
        console.error(`PostgresEventBus: failed to persist trace event: ${error instanceof Error ? error.message : String(error)}`);
      });
  }

  /** Cross-process consumers can't be notified via an in-process callback — there is no live
   * subscriber to call back into from a different process. Real-time delivery across the
   * process boundary goes through listEventsSince() polling instead (see apps/api). */
  subscribe(_handler: EventHandler): () => void {
    return () => {};
  }

  /** Waits for every write issued so far to complete. Useful in tests (assert against what's
   * actually persisted) and for graceful shutdown (avoid losing buffered events on exit). */
  async flush(): Promise<void> {
    await this.writeChain;
  }
}

export async function listEventsSince(
  pool: Pool,
  runId: string,
  afterId: number,
  tenantId: string,
): Promise<StoredTraceEvent[]> {
  const db = drizzle(pool);
  return db.transaction(async (tx) => {
    await tx.execute(sql`select set_config('app.tenant_id', ${tenantId}, true)`);
    const rows = await tx
      .select()
      .from(traceEvents)
      .where(and(eq(traceEvents.runId, runId), eq(traceEvents.tenantId, tenantId), gt(traceEvents.id, afterId)))
      .orderBy(asc(traceEvents.id));
    return rows.map((row) => ({
      id: row.id,
      type: row.type as TraceEventType,
      runId: row.runId,
      tenantId: row.tenantId,
      sessionId: row.sessionId,
      timestamp: row.createdAt.toISOString(),
      payload: (row.payload ?? undefined) as Record<string, unknown> | undefined,
    }));
  });
}
