import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import type { Pool } from "pg";
import type { TenantContext } from "@opentalos/core-types";
import { GraphEngine, type NodeResumeValue } from "@opentalos/core-graph";
import type { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
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
    const registration = this.registry.getOrThrow(graphId);
    const graph = registration.buildGraph();
    const deps = registration.buildDeps();
    const engine = new GraphEngine(graph, { ...deps, checkpointStore: this.checkpointStore });
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

  async enqueueResume(runId: string, resumeValue: NodeResumeValue, options: EnqueueOptions = {}): Promise<void> {
    const checkpoint = await this.checkpointStore.load(runId);
    if (!checkpoint) {
      throw new Error(`Cannot enqueue resume: no checkpoint found for run "${runId}"`);
    }
    if (checkpoint.status !== "paused") {
      throw new Error(`Cannot enqueue resume: run "${runId}" is not paused (status: "${checkpoint.status}")`);
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
