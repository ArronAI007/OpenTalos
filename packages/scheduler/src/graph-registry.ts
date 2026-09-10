import type { EngineDeps, GraphDefinition } from "@opentalos/core-graph";

export interface GraphRegistration<TState> {
  buildGraph: () => GraphDefinition<TState>;
  /** Everything the graph's own nodes need except checkpoint storage — the scheduler always
   * injects its own PostgresCheckpointStore, so registrations never provide one. */
  buildDeps: () => Omit<EngineDeps, "checkpointStore">;
}

// Type safety note: `register<TState>` erases to `GraphRegistration<unknown>` internally, so
// nothing here (or in Scheduler.enqueueStart) checks that a caller's initialState actually
// matches the graph registered under a given graphId — a mismatch fails at runtime inside node
// execution, not at compile time. Inherent to a string-keyed heterogeneous registry; not fixable
// without giving up the plain-string graphId that needs to persist in a DB row.
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
