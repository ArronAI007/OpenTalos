import type { Checkpoint, CheckpointQuery, CheckpointStore } from "@opentalos/core-types";

export class InMemoryCheckpointStore implements CheckpointStore {
  private readonly checkpoints = new Map<string, Checkpoint>();

  async save(checkpoint: Checkpoint): Promise<void> {
    // Preserve whatever cancelRequested value is currently stored (set only by requestCancel()
    // after the first save) rather than blindly overwriting it with the incoming checkpoint's own
    // field. The engine calls save() with an in-memory Checkpoint object that was loaded/created
    // once and never re-reads cancelRequested mid-run, so a full-object replace here would
    // silently clobber a concurrent requestCancel() the moment the engine's next node-boundary
    // save() lands. Fall back to the incoming value only when there's no existing row yet (the
    // very first save for this runId), so a brand-new checkpoint is still seeded correctly.
    const existing = this.checkpoints.get(checkpoint.runId);
    this.checkpoints.set(checkpoint.runId, {
      ...checkpoint,
      cancelRequested: existing ? existing.cancelRequested : checkpoint.cancelRequested,
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
}
