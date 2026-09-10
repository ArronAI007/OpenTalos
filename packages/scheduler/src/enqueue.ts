import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import type { Pool } from "pg";
import type { TenantContext } from "@opentalos/core-types";
import type { NodeResumeValue } from "@opentalos/core-graph";
import type { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import { buildEngine } from "./build-engine.js";
import type { GraphRegistry } from "./graph-registry.js";
import { tasks } from "./schema.js";

export interface EnqueueOptions {
  maxAttempts?: number;
  timeoutMs?: number;
  priority?: number;
}

export class Scheduler {
  private readonly db: NodePgDatabase;

  constructor(
    pool: Pool,
    private readonly registry: GraphRegistry,
    private readonly checkpointStore: PostgresCheckpointStore,
  ) {
    this.db = drizzle(pool);
  }

  async enqueueStart<TState>(
    graphId: string,
    initialState: TState,
    tenant: TenantContext,
    runId: string,
    options: EnqueueOptions = {},
  ): Promise<void> {
    // Guard against a reused runId silently destroying an in-flight or paused run:
    // PostgresCheckpointStore.save() upserts on the run_id primary key, so without this check a
    // second enqueueStart() call with the same runId would silently overwrite a live checkpoint
    // with a fresh initial state (losing an awaiting-approval run with no error) and queue a
    // duplicate task row.
    const existing = await this.checkpointStore.load(runId);
    if (existing) {
      throw new Error(`Cannot enqueue start: run "${runId}" already exists (status: "${existing.status}")`);
    }

    const engine = buildEngine(this.registry, this.checkpointStore, graphId);
    const checkpoint = engine.start(initialState, tenant, runId);
    // checkpointStore.save() and the tasks insert below are two independent writes (no shared
    // transaction) — if the task insert fails after the checkpoint save succeeds, the run is left
    // "running" with no queued task to claim it. Accepted simplification for this phase; a real fix
    // would require PostgresCheckpointStore to accept an externally-supplied transaction/client.
    await this.checkpointStore.save(checkpoint);

    await this.db.insert(tasks).values({
      runId,
      graphId,
      tenantId: tenant.tenantId,
      sessionId: tenant.sessionId,
      kind: "start",
      status: "queued",
      maxAttempts: options.maxAttempts ?? 3,
      timeoutMs: options.timeoutMs ?? 30_000,
      priority: options.priority ?? 0,
    });
  }

  async enqueueResume(
    runId: string,
    resumeValue: NodeResumeValue,
    tenant: TenantContext,
    options: EnqueueOptions = {},
  ): Promise<void> {
    const checkpoint = await this.checkpointStore.load(runId);
    if (!checkpoint) {
      throw new Error(`Cannot enqueue resume: no checkpoint found for run "${runId}"`);
    }
    if (checkpoint.status !== "paused") {
      throw new Error(`Cannot enqueue resume: run "${runId}" is not paused (status: "${checkpoint.status}")`);
    }
    // Tenant authorization: resumeFromCheckpoint() itself performs no tenant check (see its
    // JSDoc), delegating that responsibility to whoever loads the checkpoint and calls it — i.e.
    // here. Match resume()'s own tenant-mismatch granularity in core-graph's engine.ts, which
    // checks both tenantId and sessionId, not just tenantId.
    if (checkpoint.tenantId !== tenant.tenantId || checkpoint.sessionId !== tenant.sessionId) {
      throw new Error(`Cannot enqueue resume: run "${runId}" belongs to a different tenant`);
    }
    await this.db.insert(tasks).values({
      runId,
      graphId: checkpoint.graphId,
      tenantId: checkpoint.tenantId,
      sessionId: checkpoint.sessionId,
      kind: "resume",
      resumeValue: resumeValue as object | undefined,
      status: "queued",
      maxAttempts: options.maxAttempts ?? 3,
      timeoutMs: options.timeoutMs ?? 30_000,
      priority: options.priority ?? 0,
    });
  }
}
