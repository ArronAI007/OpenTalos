export interface ChatState {
  message: string;
  /** Base64 data URIs the user attached to this turn's message — see Message.images. */
  images?: string[];
  searchResult?: string;
  /** The model's reasoning/thinking trace for this turn (see AgentTurnResult.reasoningText) —
   * empty/absent for providers or models that don't emit it. Never gated by `approved`: it's the
   * model's own deliberation, not a tool's result, so it's always shown once available. */
  reasoningText?: string;
  /** True when this turn called at least one tool marked `dangerous` in its ToolDefinition — see
   * graph.ts's respond node. Only these turns route through the confirm/approval pause; an
   * ordinary read-only tool call does not. */
  requiresApproval?: boolean;
  approved?: boolean;
  reply?: string;
}
