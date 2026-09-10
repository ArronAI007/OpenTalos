import type { Checkpoint, CheckpointStore, EventBus, Guardrail, TenantContext, ToolRegistry } from "@opentalos/core-types";
import type { GraphDefinition, NodeCursor, NodeFn, NodeGenerator, NodeResumeValue } from "./types.js";

export interface EngineDeps {
  toolRegistry: ToolRegistry;
  eventBus: EventBus;
  checkpointStore: CheckpointStore;
  /** Optional cross-cutting before/after hooks; see wrapWithGuardrails for how they compose with a node's own yields. */
  guardrails?: Guardrail[];
}

/** Thrown when a node body (or a guardrail wrapping it) throws; never swallowed, always paired with an "error" trace event. */
export class NodeError extends Error {
  constructor(
    public readonly nodeId: string,
    public readonly cause: unknown,
    public readonly recoverable: boolean,
  ) {
    super(`Node "${nodeId}" failed: ${cause instanceof Error ? cause.message : String(cause)}`);
    this.name = "NodeError";
  }
}

type NodeOutcome<TState> = { status: "done"; partial: Partial<TState> } | { status: "paused"; reason: string };

interface PausedEntry<TState> {
  tenant: TenantContext;
  generator: NodeGenerator<TState>;
}

export class GraphEngine<TState> {
  // The one deliberate exception to "the engine holds no cross-call state": a live, paused
  // generator can only be resumed within the same process (see the "Cross-process resume is
  // not supported" error in resume() below). Keyed by runId, with the originating tenant
  // recorded alongside it so resume() can refuse a runId reused/spoofed under a different
  // tenant — see resume()'s tenant-match check.
  private readonly paused = new Map<string, PausedEntry<TState>>();

  constructor(
    private readonly graph: GraphDefinition<TState>,
    private readonly deps: EngineDeps,
  ) {}

  start(initialState: TState, tenant: TenantContext, runId: string): Checkpoint<TState> {
    return {
      graphId: this.graph.id,
      runId,
      tenantId: tenant.tenantId,
      sessionId: tenant.sessionId,
      nodeCursor: this.graph.entryNode,
      state: initialState,
      pendingYields: [],
      status: "running",
      createdAt: new Date().toISOString(),
    };
  }

  async run(checkpoint: Checkpoint<TState>): Promise<Checkpoint<TState>> {
    let current = checkpoint;
    while (current.status === "running") {
      current = await this.step(current);
    }
    return current;
  }

  async resume(checkpoint: Checkpoint<TState>, resumeValue: NodeResumeValue): Promise<Checkpoint<TState>> {
    if (checkpoint.status !== "paused" || typeof checkpoint.nodeCursor !== "string") {
      throw new Error(`Run ${checkpoint.runId} is not in a resumable paused state`);
    }
    const nodeId = checkpoint.nodeCursor;
    const pausedEntry = this.paused.get(checkpoint.runId);
    if (!pausedEntry) {
      throw new Error(
        `No in-memory paused generator found for run ${checkpoint.runId}. Cross-process resume is not supported in this version.`,
      );
    }
    const tenant: TenantContext = { tenantId: checkpoint.tenantId, sessionId: checkpoint.sessionId };
    if (pausedEntry.tenant.tenantId !== tenant.tenantId || pausedEntry.tenant.sessionId !== tenant.sessionId) {
      throw new Error(`Run ${checkpoint.runId} was paused under a different tenant/session; refusing to resume`);
    }
    // Tentatively remove; re-added below (via onApprovalPause) if the node pauses again.
    this.paused.delete(checkpoint.runId);
    const outcome = await this.runNodeToCompletion(nodeId, pausedEntry.generator, tenant, checkpoint.runId, resumeValue, (g) => {
      this.paused.set(checkpoint.runId, { tenant, generator: g });
    });

    if (outcome.status === "paused") {
      // A node (or a guardrail wrapping it) can legitimately pause more than once within a
      // single logical execution — e.g. a guardrail requiring approval both before and after
      // the node body runs. Each pause is persisted exactly like step()'s own pause handling.
      this.emitTrace("hitl_interrupt", checkpoint.runId, tenant, { nodeId, reason: outcome.reason });
      const pausedCheckpoint: Checkpoint<TState> = {
        ...checkpoint,
        nodeCursor: nodeId,
        status: "paused",
        pendingYields: [{ type: "awaiting_approval", reason: outcome.reason }],
      };
      await this.deps.checkpointStore.save(pausedCheckpoint);
      return pausedCheckpoint;
    }

    this.emitTrace("node_exit", checkpoint.runId, tenant, { nodeId });
    const advanced = await this.completeNode(nodeId, outcome.partial, checkpoint);
    return advanced.status === "running" ? this.run(advanced) : advanced;
  }

  /**
   * Resumes a paused checkpoint WITHOUT requiring the original in-memory generator — instead
   * it reconstructs a fresh generator from the checkpoint's saved (pre-node) state and replays
   * the node function from the top, in order feeding back every previously-resolved approval
   * (recorded in `checkpoint.pendingYields`, everything but the last element) before applying
   * the newly-supplied `resumeValue` at the current pending yield. This is what makes durable,
   * cross-process resume possible (see resume() for the same-process, in-memory-generator
   * alternative, which is faster but only works within one process's lifetime).
   * Relies on node functions being replay-safe: no non-idempotent side effects before their first yield.
   */
  async resumeFromCheckpoint(checkpoint: Checkpoint<TState>, resumeValue: NodeResumeValue): Promise<Checkpoint<TState>> {
    if (checkpoint.status !== "paused" || typeof checkpoint.nodeCursor !== "string") {
      throw new Error(`Run ${checkpoint.runId} is not in a resumable paused state`);
    }
    const nodeId = checkpoint.nodeCursor;
    const nodeFn = this.graph.nodes[nodeId];
    if (!nodeFn) {
      throw new Error(`Unknown node: ${nodeId}`);
    }
    const tenant: TenantContext = { tenantId: checkpoint.tenantId, sessionId: checkpoint.sessionId };
    const guardedNodeFn = this.wrapWithGuardrails(nodeId, nodeFn);
    const generator = guardedNodeFn(checkpoint.state, { tenant, eventBus: this.deps.eventBus });

    // pendingYields is either length 1 (a "fresh" pause produced by step(), no replay history
    // yet — the common case) or length > 1 (a pause produced by an earlier resumeFromCheckpoint
    // call, where every element but the last is a resume value already fed to an earlier yield
    // during a previous replay of this same node execution). Either way, everything but the
    // last element is the prior-answers history to replay before applying the new resumeValue.
    const priorAnswers = checkpoint.pendingYields.slice(0, -1) as NodeResumeValue[];
    const replayQueue = [...priorAnswers, resumeValue];

    const outcome = await this.runNodeToCompletion(
      nodeId,
      generator,
      tenant,
      checkpoint.runId,
      undefined,
      () => {
        // No live generator to persist here — resumeFromCheckpoint always reconstructs a fresh
        // generator by replay next time too, so there is nothing useful to keep in `this.paused`.
      },
      replayQueue,
    );

    if (outcome.status === "paused") {
      this.emitTrace("hitl_interrupt", checkpoint.runId, tenant, { nodeId, reason: outcome.reason });
      const pausedCheckpoint: Checkpoint<TState> = {
        ...checkpoint,
        nodeCursor: nodeId,
        status: "paused",
        pendingYields: [...replayQueue, { type: "awaiting_approval", reason: outcome.reason }],
      };
      await this.deps.checkpointStore.save(pausedCheckpoint);
      return pausedCheckpoint;
    }

    this.emitTrace("node_exit", checkpoint.runId, tenant, { nodeId });
    const advanced = await this.completeNode(nodeId, outcome.partial, checkpoint);
    return advanced.status === "running" ? this.run(advanced) : advanced;
  }

  private async step(checkpoint: Checkpoint<TState>): Promise<Checkpoint<TState>> {
    const cursor = checkpoint.nodeCursor as NodeCursor;
    if (typeof cursor !== "string") {
      return this.stepParallel(checkpoint, cursor);
    }

    const nodeId = cursor;
    const nodeFn = this.graph.nodes[nodeId];
    if (!nodeFn) {
      throw new Error(`Unknown node: ${nodeId}`);
    }
    const tenant: TenantContext = { tenantId: checkpoint.tenantId, sessionId: checkpoint.sessionId };
    this.emitTrace("node_enter", checkpoint.runId, tenant, { nodeId });

    const guardedNodeFn = this.wrapWithGuardrails(nodeId, nodeFn);
    const generator = guardedNodeFn(checkpoint.state, { tenant, eventBus: this.deps.eventBus });
    const outcome = await this.runNodeToCompletion(nodeId, generator, tenant, checkpoint.runId, undefined, (g) => {
      this.paused.set(checkpoint.runId, { tenant, generator: g });
    });

    if (outcome.status === "paused") {
      this.emitTrace("hitl_interrupt", checkpoint.runId, tenant, { nodeId, reason: outcome.reason });
      const pausedCheckpoint: Checkpoint<TState> = {
        ...checkpoint,
        nodeCursor: nodeId,
        status: "paused",
        pendingYields: [{ type: "awaiting_approval", reason: outcome.reason }],
      };
      await this.deps.checkpointStore.save(pausedCheckpoint);
      return pausedCheckpoint;
    }

    this.emitTrace("node_exit", checkpoint.runId, tenant, { nodeId });
    return this.completeNode(nodeId, outcome.partial, checkpoint);
  }

  private async completeNode(
    nodeId: string,
    partial: Partial<TState>,
    checkpoint: Checkpoint<TState>,
  ): Promise<Checkpoint<TState>> {
    const nextState = this.graph.reducer(checkpoint.state, partial);
    const edge = this.graph.edges.find((e) => e.from === nodeId && (!e.condition || e.condition(nextState)));

    let nextCheckpoint: Checkpoint<TState>;
    if (!edge) {
      nextCheckpoint = { ...checkpoint, state: nextState, nodeCursor: nodeId, status: "done", pendingYields: [] };
    } else if (Array.isArray(edge.to)) {
      const cursor: NodeCursor = { type: "parallel", branches: edge.to, joinTo: edge.joinTo };
      nextCheckpoint = { ...checkpoint, state: nextState, nodeCursor: cursor, status: "running", pendingYields: [] };
    } else {
      nextCheckpoint = { ...checkpoint, state: nextState, nodeCursor: edge.to, status: "running", pendingYields: [] };
    }
    await this.deps.checkpointStore.save(nextCheckpoint);
    return nextCheckpoint;
  }

  private async stepParallel(
    checkpoint: Checkpoint<TState>,
    cursor: Extract<NodeCursor, { type: "parallel" }>,
  ): Promise<Checkpoint<TState>> {
    const tenant: TenantContext = { tenantId: checkpoint.tenantId, sessionId: checkpoint.sessionId };

    const partials = await Promise.all(
      cursor.branches.map(async (branchId) => {
        const nodeFn = this.graph.nodes[branchId];
        if (!nodeFn) {
          throw new Error(`Unknown node: ${branchId}`);
        }
        this.emitTrace("node_enter", checkpoint.runId, tenant, { nodeId: branchId });
        const guardedNodeFn = this.wrapWithGuardrails(branchId, nodeFn);
        const generator = guardedNodeFn(checkpoint.state, { tenant, eventBus: this.deps.eventBus });
        const outcome = await this.runNodeToCompletion(branchId, generator, tenant, checkpoint.runId, undefined, () => {
          throw new Error(
            `Node "${branchId}" attempted to await approval inside a parallel fan-out branch, which is not supported`,
          );
        });
        if (outcome.status === "paused") {
          throw new Error(
            `Node "${branchId}" attempted to await approval inside a parallel fan-out branch, which is not supported`,
          );
        }
        this.emitTrace("node_exit", checkpoint.runId, tenant, { nodeId: branchId });
        return outcome.partial;
      }),
    );

    const mergedState = partials.reduce((state, partial) => this.graph.reducer(state, partial), checkpoint.state);
    const nextCheckpoint: Checkpoint<TState> = cursor.joinTo
      ? { ...checkpoint, state: mergedState, nodeCursor: cursor.joinTo, status: "running", pendingYields: [] }
      : { ...checkpoint, state: mergedState, nodeCursor: cursor.branches[0], status: "done", pendingYields: [] };

    await this.deps.checkpointStore.save(nextCheckpoint);
    return nextCheckpoint;
  }

  private async runNodeToCompletion(
    nodeId: string,
    generator: NodeGenerator<TState>,
    tenant: TenantContext,
    runId: string,
    initialResume: NodeResumeValue,
    onApprovalPause: (generator: NodeGenerator<TState>) => void,
    replayQueue?: NodeResumeValue[],
  ): Promise<NodeOutcome<TState>> {
    // Copy so draining it here never mutates the caller's array — resumeFromCheckpoint still
    // needs its own original replayQueue afterwards, to build the next checkpoint's pendingYields.
    const queue = replayQueue ? [...replayQueue] : undefined;

    const advance = async (value: NodeResumeValue) => {
      try {
        return await generator.next(value);
      } catch (cause) {
        const error = new NodeError(nodeId, cause, false);
        this.emitTrace("error", runId, tenant, { nodeId, message: error.message });
        throw error;
      }
    };

    let result = await advance(initialResume);
    while (!result.done) {
      const yielded = result.value;
      if (yielded.type === "awaiting_tool") {
        this.emitTrace("tool_call_start", runId, tenant, { toolCall: yielded.toolCall });
        const toolResult = await this.deps.toolRegistry.execute(yielded.toolCall, tenant);
        this.emitTrace("tool_call_end", runId, tenant, { toolResult });
        result = await advance({ type: "tool_result", result: toolResult });
        continue;
      }
      // On replay, each awaiting_approval yield consumes the next queued value in order — this
      // is what makes cross-process resume possible: the node is being re-driven from scratch
      // (see resumeFromCheckpoint), and everything already resolved in an earlier replay pass
      // must be faithfully re-answered before the genuinely new value is applied. Once the queue
      // is empty, the next awaiting_approval yield pauses for real, exactly like a first-time pause.
      if (queue && queue.length > 0) {
        const seeded = queue.shift() as NodeResumeValue;
        result = await advance(seeded);
        continue;
      }
      onApprovalPause(generator);
      return { status: "paused", reason: yielded.reason };
    }
    return { status: "done", partial: result.value };
  }

  /**
   * Composes a node's own generator with optional before/after Guardrail checks by delegating
   * via `yield*`. A "require_approval" decision reuses the exact same awaiting_approval yield
   * (and therefore the exact same pause/resume/checkpoint machinery) as a node's own HITL yield,
   * so `resume()` needs no changes to support guardrail-triggered pauses.
   */
  private wrapWithGuardrails(nodeId: string, nodeFn: NodeFn<TState>): NodeFn<TState> {
    const guardrails = this.deps.guardrails ?? [];
    if (guardrails.length === 0) {
      return nodeFn;
    }
    return async function* guarded(state, ctx) {
      for (const guardrail of guardrails) {
        const decision = await guardrail.check({ nodeId, phase: "before", state, ctx: ctx.tenant });
        if (decision === "block") {
          throw new Error(`Guardrail blocked node "${nodeId}" before execution`);
        }
        if (decision === "require_approval") {
          const resume = yield {
            type: "awaiting_approval",
            reason: `Guardrail requires approval before running "${nodeId}"`,
          };
          if (!(resume?.type === "approval" && resume.approved)) {
            throw new Error(`Guardrail approval was denied for node "${nodeId}" before execution`);
          }
        }
      }
      const partial = yield* nodeFn(state, ctx);
      for (const guardrail of guardrails) {
        const decision = await guardrail.check({ nodeId, phase: "after", state, output: partial, ctx: ctx.tenant });
        if (decision === "block") {
          throw new Error(`Guardrail blocked node "${nodeId}" after execution`);
        }
        if (decision === "require_approval") {
          const resume = yield {
            type: "awaiting_approval",
            reason: `Guardrail requires approval after running "${nodeId}"`,
          };
          if (!(resume?.type === "approval" && resume.approved)) {
            throw new Error(`Guardrail approval was denied for node "${nodeId}" after execution`);
          }
        }
      }
      return partial;
    };
  }

  private emitTrace(
    type: Parameters<EventBus["emit"]>[0]["type"],
    runId: string,
    tenant: TenantContext,
    payload?: Record<string, unknown>,
  ): void {
    this.deps.eventBus.emit({
      type,
      runId,
      tenantId: tenant.tenantId,
      sessionId: tenant.sessionId,
      timestamp: new Date().toISOString(),
      payload,
    });
  }
}
