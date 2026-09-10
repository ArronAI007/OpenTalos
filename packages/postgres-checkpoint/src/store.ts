import { and, eq } from "drizzle-orm";
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
      createdAt: new Date(checkpoint.createdAt),
    };
    await this.db
      .insert(checkpoints)
      .values(values)
      .onConflictDoUpdate({
        target: checkpoints.runId,
        set: {
          graphId: values.graphId,
          tenantId: values.tenantId,
          sessionId: values.sessionId,
          nodeCursor: values.nodeCursor,
          state: values.state,
          pendingYields: values.pendingYields,
          status: values.status,
          updatedAt: new Date(),
        },
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
    };
  }
}
