import type { Checkpoint, CheckpointQuery, CheckpointStore } from "@opentalos/core-types";

export class InMemoryCheckpointStore implements CheckpointStore {
  private readonly checkpoints = new Map<string, Checkpoint>();

  async save(checkpoint: Checkpoint): Promise<void> {
    const existing = this.checkpoints.get(checkpoint.runId);

    // Once a checkpoint has been recorded "failed" (Worker.execute()'s final-failure branch,
    // after retries are exhausted), that is a terminal, authoritative decision — no ordinary
    // save() call should be able to silently downgrade it back to "running"/"paused"/"done".
    // This matters most for the TIMEOUT-triggered failure path: runWithTimeout() races the node
    // execution against a timeout via Promise.race and aborts on timeout, but the original node
    // promise isn't cancelled — it keeps running unowned in the background. If that orphaned
    // execution's node handles the abort signal gracefully and finishes normally (rather than
    // throwing), GraphEngine reaches its ordinary completeNode() path and calls save() with a
    // perfectly normal, non-failed checkpoint. Without this guard, that stale save would land
    // after (and silently overwrite) the failure Worker.execute() already persisted. A
    // "failed" -> "failed" re-save, or any save whose incoming status IS "failed", is still a
    // legitimate terminal write and must go through normally.
    if (existing?.status === "failed" && checkpoint.status !== "failed") {
      return;
    }

    // Preserve whatever cancelRequested/steerMessage values are currently stored (set only by
    // requestCancel()/requestSteer() after the first save) rather than blindly overwriting them
    // with the incoming checkpoint's own fields. The engine calls save() with an in-memory
    // Checkpoint object that was loaded/created once and never re-reads either field mid-run, so a
    // full-object replace here would silently clobber a concurrent requestCancel()/requestSteer()
    // the moment the engine's next node-boundary save() lands. Fall back to the incoming value only
    // when there's no existing row yet (the very first save for this runId), so a brand-new
    // checkpoint is still seeded correctly.
    this.checkpoints.set(checkpoint.runId, {
      ...checkpoint,
      cancelRequested: existing ? existing.cancelRequested : checkpoint.cancelRequested,
      steerMessage: existing ? existing.steerMessage : checkpoint.steerMessage,
    });
  }

  async load(runId: string): Promise<Checkpoint | undefined> {
    return this.checkpoints.get(runId);
  }

  async list(query: CheckpointQuery): Promise<Checkpoint[]> {
    return [...this.checkpoints.values()].filter((checkpoint) => {
      if (query.tenantId && checkpoint.tenantId !== query.tenantId) return false;
      if (query.sessionId && checkpoint.sessionId !== query.sessionId) return false;
      return true;
    });
  }

  async requestCancel(runId: string): Promise<void> {
    const checkpoint = this.checkpoints.get(runId);
    if (checkpoint) this.checkpoints.set(runId, { ...checkpoint, cancelRequested: true });
  }

  async requestSteer(runId: string, message: string): Promise<void> {
    const checkpoint = this.checkpoints.get(runId);
    if (checkpoint) this.checkpoints.set(runId, { ...checkpoint, steerMessage: message });
  }

  async clearSteerMessage(runId: string): Promise<void> {
    const checkpoint = this.checkpoints.get(runId);
    if (checkpoint) this.checkpoints.set(runId, { ...checkpoint, steerMessage: undefined });
  }

  async loadForTenant(runId: string, tenantId: string): Promise<Checkpoint | undefined> {
    const checkpoint = this.checkpoints.get(runId);
    return checkpoint?.tenantId === tenantId ? checkpoint : undefined;
  }

  async requestCancelForTenant(runId: string, tenantId: string): Promise<void> {
    const checkpoint = this.checkpoints.get(runId);
    if (checkpoint?.tenantId === tenantId) {
      this.checkpoints.set(runId, { ...checkpoint, cancelRequested: true });
    }
  }

  async requestSteerForTenant(runId: string, message: string, tenantId: string): Promise<void> {
    const checkpoint = this.checkpoints.get(runId);
    if (checkpoint?.tenantId === tenantId) {
      this.checkpoints.set(runId, { ...checkpoint, steerMessage: message });
    }
  }

  async clearSteerMessageForTenant(runId: string, tenantId: string): Promise<void> {
    const checkpoint = this.checkpoints.get(runId);
    if (checkpoint?.tenantId === tenantId) {
      this.checkpoints.set(runId, { ...checkpoint, steerMessage: undefined });
    }
  }
}
