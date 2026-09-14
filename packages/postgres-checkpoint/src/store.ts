import { and, eq, sql } from "drizzle-orm";
import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import type { Pool } from "pg";
import type { Checkpoint, CheckpointQuery, CheckpointStore } from "@opentalos/core-types";
import { checkpoints } from "./schema.js";

type CheckpointRow = typeof checkpoints.$inferSelect;

export class PostgresCheckpointStore implements CheckpointStore {
  private readonly db: NodePgDatabase;

  constructor(pool: Pool) {
    this.db = drizzle(pool);
  }

  async save(checkpoint: Checkpoint): Promise<void> {
    const values = {
      runId: checkpoint.runId,
      graphId: checkpoint.graphId,
      tenantId: checkpoint.tenantId,
      sessionId: checkpoint.sessionId,
      nodeCursor: checkpoint.nodeCursor,
      state: checkpoint.state,
      pendingYields: checkpoint.pendingYields,
      status: checkpoint.status,
      cancelRequested: checkpoint.cancelRequested,
      error: checkpoint.error ?? null,
      createdAt: new Date(checkpoint.createdAt),
    };
    await this.db
      .insert(checkpoints)
      .values(values)
      .onConflictDoUpdate({
        target: checkpoints.runId,
        // cancelRequested is deliberately NOT included here: the engine calls save() with
        // whatever in-memory Checkpoint object it's holding, which was loaded/created once and
        // never re-reads cancelRequested mid-run (it's opaque to the engine). If an UPDATE here
        // wrote values.cancelRequested on every save, a concurrent requestCancel() (a targeted
        // UPDATE, not routed through save() for exactly this reason) could be silently clobbered
        // back to the save()'s stale value the moment the engine's next node-boundary save lands.
        // requestCancel() must be the only writer of this column after the initial INSERT above
        // (which correctly seeds it from whatever start() set, i.e. false).
        set: {
          graphId: values.graphId,
          tenantId: values.tenantId,
          sessionId: values.sessionId,
          nodeCursor: values.nodeCursor,
          state: values.state,
          pendingYields: values.pendingYields,
          status: values.status,
          error: values.error,
          updatedAt: new Date(),
        },
        // setWhere renders as `ON CONFLICT (...) DO UPDATE SET ... WHERE <condition>` (Postgres
        // native syntax; supported by drizzle-orm's PgInsertOnConflictDoUpdateConfig). Bare column
        // references here (checkpoints.status) resolve to the EXISTING row's current value, not
        // the proposed one - exactly like in a plain UPDATE's WHERE clause.
        //
        // Once a checkpoint is "failed" (only ever written by Worker.execute()'s final-failure
        // branch, after retries are exhausted), that is a terminal, authoritative decision - no
        // ordinary save() call should be able to silently downgrade it back to
        // "running"/"paused"/"done". This matters most for the TIMEOUT-triggered failure path:
        // runWithTimeout() races the node execution against a timeout via Promise.race and aborts
        // on timeout, but the original node promise isn't cancelled - it keeps running unowned in
        // the background. If that orphaned execution's node handles the abort signal gracefully
        // and finishes normally (rather than throwing), GraphEngine reaches its ordinary
        // completeNode() path and calls save() with a perfectly normal, non-failed checkpoint.
        // Without this guard, that stale save would land after (and silently overwrite) the
        // failure Worker.execute() already persisted.
        //
        // The condition only SKIPS the update when we'd be downgrading an existing "failed" row
        // to a non-failed status - a "failed" -> "failed" re-save, or any save whose incoming
        // status IS "failed", is still a legitimate terminal write and must go through normally.
        setWhere: sql`${checkpoints.status} != 'failed' OR ${values.status} = 'failed'`,
      });
  }

  async load(runId: string): Promise<Checkpoint | undefined> {
    const rows = await this.db.select().from(checkpoints).where(eq(checkpoints.runId, runId)).limit(1);
    return rows[0] ? this.toCheckpoint(rows[0]) : undefined;
  }

  async list(query: CheckpointQuery): Promise<Checkpoint[]> {
    const conditions = [];
    if (query.tenantId) conditions.push(eq(checkpoints.tenantId, query.tenantId));
    if (query.sessionId) conditions.push(eq(checkpoints.sessionId, query.sessionId));
    const rows =
      conditions.length > 0
        ? await this.db.select().from(checkpoints).where(and(...conditions))
        : await this.db.select().from(checkpoints);
    return rows.map((row) => this.toCheckpoint(row));
  }

  private toCheckpoint(row: CheckpointRow): Checkpoint {
    return {
      runId: row.runId,
      graphId: row.graphId,
      tenantId: row.tenantId,
      sessionId: row.sessionId,
      nodeCursor: row.nodeCursor,
      state: row.state,
      pendingYields: row.pendingYields as unknown[],
      status: row.status as Checkpoint["status"],
      createdAt: row.createdAt.toISOString(),
      cancelRequested: row.cancelRequested,
      error: row.error ?? undefined,
    };
  }

  async requestCancel(runId: string): Promise<void> {
    await this.db.update(checkpoints).set({ cancelRequested: true }).where(eq(checkpoints.runId, runId));
  }
}
