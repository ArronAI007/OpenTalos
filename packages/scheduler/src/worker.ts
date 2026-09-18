import { and, asc, desc, eq, lte, sql } from "drizzle-orm";
import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import type { Pool } from "pg";
import type { NodeResumeValue } from "@opentalos/core-graph";
import type { PostgresCheckpointStore } from "@opentalos/postgres-checkpoint";
import { buildEngine } from "./build-engine.js";
import type { GraphRegistry } from "./graph-registry.js";
import { tasks } from "./schema.js";
import { SteerChannelImpl } from "./steer-channel.js";

type TaskRow = typeof tasks.$inferSelect;

export interface WorkerOptions {
  globalConcurrency: number;
  tenantConcurrency: number;
  /** 可选：按 tenantId 动态解析每租户并发上限。提供时优先于静态的 tenantConcurrency；不提供
   * 时行为和不存在这个字段完全一样（用 tenantConcurrency 这个静态数字）。如果这个函数对某个
   * tenantId 抛出异常，该租户这一批次退回使用静态默认值，不会让整个 pollOnce() 失败——一次
   * 配额查询的瞬时故障不应该阻塞其他租户的任务被正常领取执行。 */
  resolveTenantConcurrency?: (tenantId: string) => Promise<number>;
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

      const tenantCaps = await this.resolveTenantCaps(candidates);
      const toRun: TaskRow[] = [];
      const tenantCounts = new Map<string, number>();
      for (const candidate of candidates) {
        if (toRun.length >= this.options.globalConcurrency) break;
        const cap = tenantCaps.get(candidate.tenantId) ?? this.options.tenantConcurrency;
        const tenantCount = tenantCounts.get(candidate.tenantId) ?? 0;
        if (tenantCount >= cap) continue;
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

  /** Resolves each DISTINCT tenantId appearing in this batch to its per-tenant concurrency cap,
   * via the injected resolveTenantConcurrency hook — called at most once per distinct tenantId
   * per poll cycle, not once per candidate task. Returns an empty map (falling through to the
   * static tenantConcurrency default for every tenant) when no resolver is configured at all,
   * preserving Phase 2's original behavior exactly. */
  private async resolveTenantCaps(candidates: TaskRow[]): Promise<Map<string, number>> {
    const caps = new Map<string, number>();
    if (!this.options.resolveTenantConcurrency) return caps;

    const resolve = this.options.resolveTenantConcurrency;
    const distinctTenantIds = [...new Set(candidates.map((c) => c.tenantId))];
    await Promise.all(
      distinctTenantIds.map(async (tenantId) => {
        try {
          caps.set(tenantId, await resolve(tenantId));
        } catch (error) {
          console.error(
            `Worker: resolveTenantConcurrency failed for tenant "${tenantId}", falling back to the static default: ${error instanceof Error ? error.message : String(error)}`,
          );
        }
      }),
    );
    return caps;
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

        // Also surface the failure on the run's checkpoint — without this, the checkpoint's
        // status stays "running" forever (GraphEngine only ever transitions it to "done"/"paused"
        // on success, and rethrows on error without touching the checkpoint at all), so
        // GET /runs/:runId and the SSE stream would otherwise never learn the run failed.
        const checkpoint = await this.checkpointStore.loadForTenant(task.runId, task.tenantId);
        if (checkpoint) {
          await this.checkpointStore.save({ ...checkpoint, status: "failed", error: errorMessage(error) });
        }
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
    // An AbortController wired to a poll loop that re-reads this run's own checkpoint row every
    // ~500ms: once a POST /runs/:runId/cancel request has flipped `cancelRequested` to true
    // (Task 6), this is what actually stops the in-flight engine.run()/resumeFromCheckpoint()
    // call — the signal is forwarded all the way down into the model provider's HTTP call
    // (Tasks 2-5). `checkingCancel` is a reentrancy guard: if a single checkpointStore.loadForTenant()
    // takes longer than 500ms, we skip overlapping ticks rather than piling up concurrent loads.
    //
    // This lives here (not inside runTask()) so that the `finally` below — which always runs,
    // since runWithTimeout directly awaits the Promise.race — is the one thing responsible for
    // clearing the interval, regardless of which side of the race settles. If it lived inside
    // runTask() instead, a timeout winning the race would orphan runTask()'s promise (and its own
    // finally) indefinitely for a genuinely hung task, leaking the interval forever — and worse,
    // execute()'s retry would start a second runTask() call on top, leaking a second interval.
    const controller = new AbortController();
    const steerChannel = new SteerChannelImpl();
    let checkingCancel = false;
    const cancelPoll = setInterval(() => {
      if (controller.signal.aborted) {
        // Already aborted (either by a cancel request or by the timeout below) — stop polling for
        // the remainder of the run instead of doing redundant work.
        clearInterval(cancelPoll);
        return;
      }
      if (checkingCancel) return;
      checkingCancel = true;
      this.checkpointStore
        .loadForTenant(task.runId, task.tenantId)
        .then(async (latest) => {
          if (latest?.cancelRequested) controller.abort();
          if (latest?.steerMessage) {
            steerChannel.deliver(latest.steerMessage);
            await this.checkpointStore.clearSteerMessageForTenant(task.runId, task.tenantId);
          }
        })
        .catch(() => {
          // Best-effort: a transient DB error here just means this tick doesn't check; the next
          // tick tries again. Not fatal to the run.
        })
        .finally(() => {
          checkingCancel = false;
        });
    }, 500);

    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(() => {
        // Interrupt the in-flight model call on timeout too, not just fail the task — otherwise a
        // timed-out task's engine.run()/resumeFromCheckpoint() call keeps running (and billing)
        // in the background even after runWithTimeout itself has moved on. The controller/interval
        // now live here (not inside runTask) specifically so this "finally always clears the
        // interval regardless of which side of the race settles" guarantee holds even when
        // runTask's own promise is orphaned by the race.
        controller.abort();
        reject(new Error(`Task ${task.id} timed out after ${task.timeoutMs}ms`));
      }, task.timeoutMs);
    });
    try {
      await Promise.race([this.runTask(task, controller, steerChannel), timeout]);
    } finally {
      if (timer) clearTimeout(timer);
      clearInterval(cancelPoll);
    }
  }

  private async runTask(task: TaskRow, controller: AbortController, steer: SteerChannelImpl): Promise<void> {
    const engine = buildEngine(this.registry, this.checkpointStore, task.graphId);

    const checkpoint = await this.checkpointStore.loadForTenant(task.runId, task.tenantId);
    if (!checkpoint) {
      throw new Error(`No checkpoint found for run "${task.runId}"`);
    }

    if (checkpoint.status === "done") {
      return; // Already complete (e.g. a prior attempt finished after this attempt's timeout raced it); nothing to do.
    }

    // Dispatch on the CHECKPOINT's actual status, not blindly on task.kind: a "resume" task
    // whose first attempt already replayed past the paused node (advancing the checkpoint to
    // "running") must continue via run(), not resumeFromCheckpoint() again — the latter requires
    // status "paused" and would otherwise throw "not in a resumable paused state" on every retry,
    // destroying the real error and getting the run permanently stuck. See Fix 1 in the
    // post-review notes for the full failure mode.
    if (task.kind === "resume" && checkpoint.status === "paused") {
      await engine.resumeFromCheckpoint(checkpoint, task.resumeValue as NodeResumeValue, {
        signal: controller.signal,
        steer,
      });
      return;
    }
    await engine.run(checkpoint, { signal: controller.signal, steer });
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
