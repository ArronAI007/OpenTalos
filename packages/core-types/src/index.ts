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
  /** Base64 data URIs (e.g. "data:image/png;base64,...") attached to this message — only ever set
   * on a user message. Providers whose API supports vision input translate these into image
   * content parts alongside `content`'s text (currently only the openai-compatible path, which
   * Kimi K3 routes through); providers that don't support it simply ignore this field. */
  images?: string[];
}

export type JSONSchema = Record<string, unknown>;

export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: JSONSchema;
  /** Absent (or "function") is a normal client-executed tool. "builtin" is a provider-hosted tool
   * (e.g. Kimi's `$web_search`) — the provider adapter sends a minimal declaration (just the
   * name, no description/inputSchema) and executes it server-side; the client-side Tool for one
   * of these just echoes the model's arguments back rather than doing real work. */
  kind?: "function" | "builtin";
  /** True marks this tool as requiring human approval before its result is delivered to the user
   * (see chat-agent's `confirm` node in graph.ts). Set this only on tools with a genuinely risky
   * or hard-to-reverse effect — an ordinary read-only lookup or computation should leave this
   * absent/false so it doesn't force a human-approval pause on every turn that uses it. */
  dangerous?: boolean;
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
  /** A fragment of the model's reasoning/thinking trace, distinct from its final answer (e.g.
   * Moonshot's Kimi thinking models stream this as `delta.reasoning_content`, separate from
   * `delta.content`). Only emitted by providers/models that actually support it. */
  | { type: "reasoning_delta"; reasoningDelta: string }
  | { type: "tool_call"; toolCall: ToolCall }
  | { type: "message_stop" };

export interface ModelProvider {
  complete(request: ModelRequest, options?: { signal?: AbortSignal }): AsyncIterable<ModelResponseChunk>;
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
  status: "running" | "paused" | "done" | "failed";
  createdAt: string;
  /** Set via CheckpointStore.requestCancel(). Only honored by chat-agent's respond node while a
   * model call is actively streaming (see NodeContext.signal) — a request that arrives during
   * tool execution or while paused for approval has no effect until (if ever) another streaming
   * phase happens for this run. */
  cancelRequested: boolean;
  /** A pending steering instruction the user wants spliced into the currently-generating reply —
   * see CheckpointStore.requestSteer/clearSteerMessage and packages/scheduler's Worker (delivers
   * it into the run's SteerChannel) and packages/sdk's runModelWithTools (consumes it). Distinct
   * from cancelRequested: this doesn't end the run, it interrupts the current model call, appends
   * the instruction as a new turn, and starts a fresh model call. Single-slot, not a queue: a
   * second steer overwrites a first one that hasn't been delivered yet. */
  steerMessage?: string;
  /** Set when the worker gives up retrying after a node throws (see Worker.execute() in
   * packages/scheduler) — the human-readable error message from the underlying failure (e.g. a
   * real model-provider API error). Only meaningful when status === "failed". */
  error?: string;
}

export interface CheckpointQuery {
  tenantId?: string;
  sessionId?: string;
}

export interface CheckpointStore {
  save(checkpoint: Checkpoint): Promise<void>;
  load(runId: string): Promise<Checkpoint | undefined>;
  list(query: CheckpointQuery): Promise<Checkpoint[]>;
  /** Sets cancelRequested without disturbing any other field — deliberately NOT implemented via
   * save(), which would race a concurrently-executing worker's own save() of state/status for
   * the same run (last-write-wins on a full-row upsert risks silently clobbering whichever side
   * writes last). A no-op if runId doesn't exist. */
  requestCancel(runId: string): Promise<void>;
  /** Sets steerMessage without disturbing any other field — same race-avoidance rationale as
   * requestCancel. A no-op if runId doesn't exist. */
  requestSteer(runId: string, message: string): Promise<void>;
  /** Clears steerMessage back to undefined — called by the Worker immediately after delivering a
   * pending message into the run's SteerChannel, so it isn't redelivered on the next poll tick.
   * A no-op if runId doesn't exist. */
  clearSteerMessage(runId: string): Promise<void>;

  /** Tenant-scoped variants of the four methods above, used by every call site that's driven by
   * an authenticated request/task rather than trusted internal system code (see
   * docs/superpowers/specs/2026-09-17-checkpoint-tracing-rls-design.md). These exist ALONGSIDE
   * the unscoped methods above rather than replacing their signatures, specifically so the 65+
   * existing call sites against InMemoryCheckpointStore (used pervasively in fast unit tests
   * across packages/core-graph, packages/chat-agent, packages/multi-agent, and this package's own
   * scheduler tests) never need to change. Each implementation filters by tenantId in the query
   * itself (works under any DB role) AND — for the Postgres implementation — sets an RLS session
   * variable as a database-level backstop; see PostgresCheckpointStore. Return/no-op the same way
   * as the unscoped method when runId doesn't exist OR belongs to a different tenant — the two
   * cases are indistinguishable by design, matching how RLS itself would behave. */
  loadForTenant(runId: string, tenantId: string): Promise<Checkpoint | undefined>;
  requestCancelForTenant(runId: string, tenantId: string): Promise<void>;
  requestSteerForTenant(runId: string, message: string, tenantId: string): Promise<void>;
  clearSteerMessageForTenant(runId: string, tenantId: string): Promise<void>;
}

export type TraceEventType =
  | "node_enter"
  | "node_exit"
  | "llm_call_start"
  | "llm_call_end"
  | "llm_text_delta"
  | "llm_reasoning_delta"
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
  /** Waits for every emit() issued so far to be durably persisted. Optional because an in-memory
   * bus has nothing to wait for; a durable bus (e.g. Postgres-backed) should implement it so
   * callers that need every trace event visible before observing a state transition — the graph
   * engine, before persisting a checkpoint — can await it instead of racing a fire-and-forget
   * write. */
  flush?(): Promise<void>;
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
