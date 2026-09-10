import type { EngineDeps, GraphDefinition } from "@opentalos/core-graph";

export interface GraphRegistration<TState> {
  buildGraph: () => GraphDefinition<TState>;
  /** Everything the graph's own nodes need except checkpoint storage — the scheduler always
   * injects its own PostgresCheckpointStore, so registrations never provide one. */
  buildDeps: () => Omit<EngineDeps, "checkpointStore">;
}

export class GraphRegistry {
  private readonly registrations = new Map<string, GraphRegistration<unknown>>();

  register<TState>(graphId: string, registration: GraphRegistration<TState>): void {
    this.registrations.set(graphId, registration as GraphRegistration<unknown>);
  }

  get(graphId: string): GraphRegistration<unknown> | undefined {
    return this.registrations.get(graphId);
  }

  getOrThrow(graphId: string): GraphRegistration<unknown> {
    const registration = this.registrations.get(graphId);
    if (!registration) {
      throw new Error(`Unknown graphId: "${graphId}" is not registered`);
    }
    return registration;
  }
}
