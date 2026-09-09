import type { Checkpoint, CheckpointQuery, CheckpointStore } from "@opentalos/core-types";

export class InMemoryCheckpointStore implements CheckpointStore {
  private readonly checkpoints = new Map<string, Checkpoint>();

  async save(checkpoint: Checkpoint): Promise<void> {
    this.checkpoints.set(checkpoint.runId, checkpoint);
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
}
