import { and, asc, desc, eq, lte, sql } from "drizzle-orm";
import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import type { Pool } from "pg";
import type { NodeResumeValue } from "@opentalos/core-graph";
import type { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import { buildEngine } from "./build-engine.js";
import type { GraphRegistry } from "./graph-registry.js";
import { tasks } from "./schema.js";

type TaskRow = typeof tasks.$inferSelect;

export interface WorkerOptions {
  globalConcurrency: number;
  tenantConcurrency: number;
  pollIntervalMs?: number;
  batchSize?: number;
}

export class Worker {
  private readonly db: NodePgDatabase;
  private stopped = true;
  private pollTimer: ReturnType<typeof setTimeout> | undefined;

  constructor(
    private readonly pool: Pool,
    private readonly registry: GraphRegistry,
    private readonly checkpointStore: PostgresCheckpointStore,
    private readonly options: WorkerOptions,
  ) {
    this.db = drizzle(pool);
  }

  /** Starts continuous polling on a timer. Call stop() to end it. */
  start(): void {
    this.stopped = false;
    this.scheduleNextPoll(0);
  }

  stop(): void {
    this.stopped = true;
    if (this.pollTimer) clearTimeout(this.pollTimer);
  }

  private scheduleNextPoll(delayMs: number): void {
    if (this.stopped) return;
    this.pollTimer = setTimeout(() => {
      this.pollOnce()
        .catch((error) => {
          // Never silently swallow errors: this is the continuous-polling path (start()/stop()),
          // untested directly, so at minimum make a poll-cycle failure visible instead of
          // discarding it entirely. A full EventBus-based reporting path is a larger API change
          // than this fix warrants.
          console.error(`Worker poll cycle failed: ${error instanceof Error ? error.message : String(error)}`);
        })
        .finally(() => this.scheduleNextPoll(this.options.pollIntervalMs ?? 100));
    }, delayMs);
  }

  /**
   * Claims up to `batchSize` queued, due tasks (respecting global/tenant concurrency caps),
   * then runs all claimed tasks to completion before returning. Concurrency caps therefore
   * apply per poll cycle, not continuously across overlapping cycles — see the design spec
   * for why this simplification is acceptable for a single-process worker.
   */
  async pollOnce(): Promise<void> {
    const batchSize = this.options.batchSize ?? 10;
    const claimed = await this.db.transaction(async (tx) => {
      // Compare availableAt against the database's own clock (sql`now()`), not a client-computed
      // `new Date()`. availableAt is itself set server-side (defaultNow() on insert, or a
      // client-supplied value on retry — see execute() below). Comparing it against a Node-side
      // timestamp introduces a real race: if the Postgres server's clock is even slightly ahead
      // of the polling process's clock (container clock skew, or just query round-trip latency),
      // a row inserted moments ago via defaultNow() can appear "not yet available" to a client
      // timestamp computed just before the query is sent — causing pollOnce() to intermittently
      // claim nothing for a task that was, by the server's own clock, already due.
      const candidates = await tx
        .select()
        .from(tasks)
        .where(and(eq(tasks.status, "queued"), lte(tasks.availableAt, sql`now()`)))
        .orderBy(desc(tasks.priority), asc(tasks.createdAt))
        .limit(batchSize)
        .for("update", { skipLocked: true });

      const toRun: TaskRow[] = [];
      const tenantCounts = new Map<string, number>();
      for (const candidate of candidates) {
        if (toRun.length >= this.options.globalConcurrency) break;
        const tenantCount = tenantCounts.get(candidate.tenantId) ?? 0;
        if (tenantCount >= this.options.tenantConcurrency) continue;
        toRun.push(candidate);
        tenantCounts.set(candidate.tenantId, tenantCount + 1);
      }

      for (const candidate of toRun) {
        await tx.update(tasks).set({ status: "running", lockedAt: new Date() }).where(eq(tasks.id, candidate.id));
      }
      return toRun;
    });

    await Promise.all(claimed.map((task) => this.execute(task)));
  }

  private async execute(task: TaskRow): Promise<void> {
    try {
      await this.runWithTimeout(task);
      // Clear a previously-set `error` from an earlier failed attempt — a task that fails once
      // and then succeeds on retry must not still show the stale error message once "done".
      await this.db
        .update(tasks)
        .set({ status: "done", error: null, updatedAt: new Date() })
        .where(eq(tasks.id, task.id));
    } catch (error) {
      const attempts = task.attempts + 1;
      if (attempts >= task.maxAttempts) {
        await this.db
          .update(tasks)
          .set({ status: "failed", attempts, error: errorMessage(error), updatedAt: new Date() })
          .where(eq(tasks.id, task.id));
      } else {
        const backoffMs = 2 ** attempts * 1000;
        await this.db
          .update(tasks)
          .set({
            status: "queued",
            attempts,
            error: errorMessage(error),
            availableAt: new Date(Date.now() + backoffMs),
            updatedAt: new Date(),
          })
          .where(eq(tasks.id, task.id));
      }
    }
  }

  private async runWithTimeout(task: TaskRow): Promise<void> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error(`Task ${task.id} timed out after ${task.timeoutMs}ms`)), task.timeoutMs);
    });
    try {
      await Promise.race([this.runTask(task), timeout]);
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  private async runTask(task: TaskRow): Promise<void> {
    const engine = buildEngine(this.registry, this.checkpointStore, task.graphId);

    const checkpoint = await this.checkpointStore.load(task.runId);
    if (!checkpoint) {
      throw new Error(`No checkpoint found for run "${task.runId}"`);
    }

    // Dispatch on the CHECKPOINT's actual status, not blindly on task.kind: a "resume" task
    // whose first attempt already replayed past the paused node (advancing the checkpoint to
    // "running") must continue via run(), not resumeFromCheckpoint() again — the latter requires
    // status "paused" and would otherwise throw "not in a resumable paused state" on every retry,
    // destroying the real error and getting the run permanently stuck. See Fix 1 in the
    // post-review notes for the full failure mode.
    if (checkpoint.status === "done") {
      return; // Already complete (e.g. a prior attempt finished after this attempt's timeout raced it); nothing to do.
    }
    if (task.kind === "resume" && checkpoint.status === "paused") {
      await engine.resumeFromCheckpoint(checkpoint, task.resumeValue as NodeResumeValue);
      return;
    }
    await engine.run(checkpoint);
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
