import type { EventBus, TenantContext, ToolCall, ToolResult } from "@opentalos/core-types";

export interface NodeContext {
  tenant: TenantContext;
  eventBus: EventBus;
}

export type NodeYield = { type: "awaiting_tool"; toolCall: ToolCall } | { type: "awaiting_approval"; reason: string };

export type NodeResumeValue =
  | { type: "tool_result"; result: ToolResult }
  | { type: "approval"; approved: boolean }
  | undefined;

export type NodeGenerator<TState> = AsyncGenerator<NodeYield, Partial<TState>, NodeResumeValue>;

export type NodeFn<TState> = (state: TState, ctx: NodeContext) => NodeGenerator<TState>;

export interface EdgeDefinition<TState> {
  from: string;
  to: string | string[];
  condition?: (state: TState) => boolean;
  /** Optional when `to` is an array: the node the fan-out branches converge back into. If
   * omitted, the fan-out is treated as the terminal step of the graph (status becomes "done"
   * once all branches complete). */
  joinTo?: string;
}

export interface GraphDefinition<TState> {
  id: string;
  entryNode: string;
  nodes: Record<string, NodeFn<TState>>;
  edges: EdgeDefinition<TState>[];
  reducer: (state: TState, partial: Partial<TState>) => TState;
}

/**
 * Internal representation of "where execution currently is". A plain node id for
 * sequential execution, or a parallel-wave descriptor for an in-flight fan-out.
 * `Checkpoint.nodeCursor` (from @opentalos/core-types) is typed `unknown` precisely so
 * it can hold either shape without core-types knowing about this engine's internals.
 */
export type NodeCursor = string | { type: "parallel"; branches: string[]; joinTo?: string };
