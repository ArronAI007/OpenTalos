// Threaded through every operation for multi-tenant isolation and log/trace correlation.
export interface TenantContext {
  tenantId: string;
  sessionId: string;
}

export type MessageRole = "system" | "user" | "assistant" | "tool";

export interface Message {
  role: MessageRole;
  content: string;
  /** Set on an assistant message that requested one or more tool calls in this turn. */
  toolCalls?: ToolCall[];
  /** Set on a role: "tool" message — correlates this result back to the ToolCall.id it answers. */
  toolCallId?: string;
}

export type JSONSchema = Record<string, unknown>;

export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: JSONSchema;
}

export interface ToolCall {
  id: string;
  name: string;
  input: unknown;
}

export interface ToolResult {
  id: string;
  output: unknown;
  isError?: boolean;
}

export interface Tool {
  definition: ToolDefinition;
  execute(input: unknown, ctx: TenantContext): Promise<ToolResult>;
}

export interface ToolRegistry {
  register(tool: Tool): void;
  get(name: string): Tool | undefined;
  list(): ToolDefinition[];
  execute(call: ToolCall, ctx: TenantContext): Promise<ToolResult>;
}

export interface ModelRequest {
  messages: Message[];
  tools?: ToolDefinition[];
  responseSchema?: JSONSchema;
}

export type ModelResponseChunk =
  | { type: "text_delta"; textDelta: string }
  | { type: "tool_call"; toolCall: ToolCall }
  | { type: "message_stop" };

export interface ModelProvider {
  complete(request: ModelRequest): AsyncIterable<ModelResponseChunk>;
}

export interface MemoryRecord {
  key: string;
  value: unknown;
  score?: number;
}

export interface MemoryStore {
  read(key: string, ctx: TenantContext): Promise<unknown | undefined>;
  write(key: string, value: unknown, ctx: TenantContext): Promise<void>;
  search(query: string, ctx: TenantContext): Promise<MemoryRecord[]>;
}

// `nodeCursor` and `pendingYields` are deliberately `unknown`: CheckpointStore must stay
// usable by any future execution engine, not just the generator-based graph engine built
// in this plan. The graph engine casts these fields to its own cursor type internally.
export interface Checkpoint<TState = unknown> {
  graphId: string;
  runId: string;
  tenantId: string;
  sessionId: string;
  nodeCursor: unknown;
  state: TState;
  pendingYields: unknown[];
  status: "running" | "paused" | "done";
  createdAt: string;
}

export interface CheckpointQuery {
  tenantId?: string;
  sessionId?: string;
}

export interface CheckpointStore {
  save(checkpoint: Checkpoint): Promise<void>;
  load(runId: string): Promise<Checkpoint | undefined>;
  list(query: CheckpointQuery): Promise<Checkpoint[]>;
}

export type TraceEventType =
  | "node_enter"
  | "node_exit"
  | "llm_call_start"
  | "llm_call_end"
  | "llm_text_delta"
  | "tool_call_start"
  | "tool_call_end"
  | "hitl_interrupt"
  | "error";

export interface TraceEvent {
  type: TraceEventType;
  runId: string;
  tenantId: string;
  sessionId: string;
  timestamp: string;
  payload?: Record<string, unknown>;
}

export type EventHandler = (event: TraceEvent) => void;

export interface EventBus {
  emit(event: TraceEvent): void;
  subscribe(handler: EventHandler): () => void;
}

export type GuardrailDecision = "allow" | "block" | "require_approval";

export interface GuardrailInput {
  nodeId: string;
  phase: "before" | "after";
  state: unknown;
  /** The node's own return value, populated only on the "after" phase (undefined on "before") — lets an after-phase guardrail actually inspect what the node produced, not just its input state. */
  output?: unknown;
  ctx: TenantContext;
}

export interface Guardrail {
  check(input: GuardrailInput): Promise<GuardrailDecision>;
}
