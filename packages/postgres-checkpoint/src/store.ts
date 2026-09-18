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
      steerMessage: checkpoint.steerMessage ?? null,
      error: checkpoint.error ?? null,
      createdAt: new Date(checkpoint.createdAt),
    };
    await this.db
      .insert(checkpoints)
      .values(values)
      .onConflictDoUpdate({
        target: checkpoints.runId,
        // cancelRequested and steerMessage are deliberately NOT included here: the engine calls
        // save() with whatever in-memory Checkpoint object it's holding, which was loaded/created
        // once and never re-reads either field mid-run (both are opaque to the engine). If an
        // UPDATE here wrote values.cancelRequested/values.steerMessage on every save, a concurrent
        // requestCancel()/requestSteer() (each a targeted UPDATE, not routed through save() for
        // exactly this reason) could be silently clobbered back to the save()'s stale value the
        // moment the engine's next node-boundary save lands. requestCancel()/requestSteer() must
        // be the only writers of these columns after the initial INSERT above (which correctly
        // seeds cancelRequested from whatever start() set, i.e. false, and steerMessage as null).
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
      steerMessage: row.steerMessage ?? undefined,
      error: row.error ?? undefined,
    };
  }

  async requestCancel(runId: string): Promise<void> {
    await this.db.update(checkpoints).set({ cancelRequested: true }).where(eq(checkpoints.runId, runId));
  }

  async requestSteer(runId: string, message: string): Promise<void> {
    await this.db.update(checkpoints).set({ steerMessage: message }).where(eq(checkpoints.runId, runId));
  }

  async clearSteerMessage(runId: string): Promise<void> {
    await this.db.update(checkpoints).set({ steerMessage: null }).where(eq(checkpoints.runId, runId));
  }

  /** 两层过滤：SQL 里显式 `AND tenant_id = $2`（任何数据库角色下都生效，包括本地/CI 常见的超级
   * 用户连接），同一个事务里再设置 `app.tenant_id` 会话变量，给数据库层的 RLS 策略（一旦 Task 5
   * 建好）做第二层背书——只有当未来某次新查询忘了写显式的 tenant_id 条件时，这一层才会真正体现
   * 出跟第一层不一样的效果。`set_config` 的第三个参数必须是 `true`（`is_local`），让这个设置只在
   * 当前事务内生效，事务提交后自动失效，避免连接池复用把这个值残留给下一个租户的请求。 */
  async loadForTenant(runId: string, tenantId: string): Promise<Checkpoint | undefined> {
    return this.db.transaction(async (tx) => {
      await tx.execute(sql`select set_config('app.tenant_id', ${tenantId}, true)`);
      const rows = await tx
        .select()
        .from(checkpoints)
        .where(and(eq(checkpoints.runId, runId), eq(checkpoints.tenantId, tenantId)))
        .limit(1);
      return rows[0] ? this.toCheckpoint(rows[0]) : undefined;
    });
  }

  async requestCancelForTenant(runId: string, tenantId: string): Promise<void> {
    await this.db.transaction(async (tx) => {
      await tx.execute(sql`select set_config('app.tenant_id', ${tenantId}, true)`);
      await tx
        .update(checkpoints)
        .set({ cancelRequested: true })
        .where(and(eq(checkpoints.runId, runId), eq(checkpoints.tenantId, tenantId)));
    });
  }

  async requestSteerForTenant(runId: string, message: string, tenantId: string): Promise<void> {
    await this.db.transaction(async (tx) => {
      await tx.execute(sql`select set_config('app.tenant_id', ${tenantId}, true)`);
      await tx
        .update(checkpoints)
        .set({ steerMessage: message })
        .where(and(eq(checkpoints.runId, runId), eq(checkpoints.tenantId, tenantId)));
    });
  }

  async clearSteerMessageForTenant(runId: string, tenantId: string): Promise<void> {
    await this.db.transaction(async (tx) => {
      await tx.execute(sql`select set_config('app.tenant_id', ${tenantId}, true)`);
      await tx
        .update(checkpoints)
        .set({ steerMessage: null })
        .where(and(eq(checkpoints.runId, runId), eq(checkpoints.tenantId, tenantId)));
    });
  }
}
