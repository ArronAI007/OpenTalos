export interface ChatState {
  message: string;
  searchResult?: string;
  /** True when this turn called at least one tool marked `dangerous` in its ToolDefinition — see
   * graph.ts's respond node. Only these turns route through the confirm/approval pause; an
   * ordinary read-only tool call does not. */
  requiresApproval?: boolean;
  approved?: boolean;
  reply?: string;
}
