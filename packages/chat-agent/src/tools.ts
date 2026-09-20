import type { MemoryStore, TenantContext, Tool } from "@opentalos/core-types";

/**
 * Deterministic mock tool: no network, no real exchange-rate API, no API key required. Always
 * returns a fixed-shape (timestamped) answer so the whole demo is reproducible offline.
 */
export const lookupExchangeRateTool: Tool = {
  definition: {
    name: "lookup_exchange_rate",
    // The "when to use me" guidance lives here (and in the schema below), not in the shared
    // system prompt — this is the whole point of the pattern: a new tool only needs a good
    // description of itself, never an edit to graph.ts's SYSTEM_PROMPT.
    description:
      "Looks up today's exchange rate for a currency pair. Use this whenever the user asks about a currency's " +
      "exchange rate, wants to convert an amount between two currencies, or otherwise needs current FX pricing.",
    inputSchema: {
      type: "object",
      properties: {
        pair: {
          type: "string",
          description: "The currency pair as BASE/QUOTE, e.g. \"USD/CNY\" for how many CNY one USD buys.",
        },
      },
      required: ["pair"],
    },
    // Deliberately marked dangerous: this is this codebase's reference example of a tool gated by
    // chat-agent's human-approval pause (see graph.ts's confirm node) — the test suite and demo UI
    // are built around this tool exercising that path. A real tool should only set this when it
    // has a genuinely risky/irreversible effect, not merely because it returns financial data.
    dangerous: true,
  },
  async execute(input) {
    const { pair } = input as { pair: string };
    return {
      id: `rate-${Date.now()}`,
      output: `1 ${pair} = 7.13（模拟汇率，生成于 ${new Date().toISOString()}）`,
    };
  },
};

/**
 * Kimi/Moonshot's server-hosted web search: the provider adapter declares this as a bare
 * `builtin_function` (see packages/model-providers/openai-compatible.ts), so the model calls it
 * like any other tool, but the actual search runs on Moonshot's servers, not here. Per Moonshot's
 * documented protocol, the client's only job is to echo the model's own arguments straight back —
 * doing anything else (real HTTP calls, transforming the payload) would just be wrong, not
 * merely redundant. Only registered when MODEL_PROVIDER=kimi (see registry.ts) — sending this
 * tool type to a provider that doesn't understand it would be meaningless at best.
 */
export const webSearchTool: Tool = {
  definition: {
    name: "$web_search",
    kind: "builtin",
    // Ignored by the provider adapter for a builtin tool (only `name` is ever sent), but
    // ToolDefinition requires the field — kept accurate for anyone reading this locally.
    description: "Kimi's server-hosted web search. The client never executes this itself.",
    inputSchema: {},
  },
  async execute(input) {
    return { id: "", output: JSON.stringify(input) };
  },
};

/** 按需查询完整记忆内容——模型看到 system prompt 里自动注入的摘要（见 graph.ts）某条标题相关、
 * 但需要更完整内容时主动调用。这是 MemoryStore.search() 至今为止第一个真实调用方。只读查询，
 * 不设 dangerous: true（不触发 HITL 审批）。 */
export function createSearchMemoryTool(memoryStore: MemoryStore): Tool {
  return {
    definition: {
      name: "search_memory",
      description: "查询关于当前用户的历史记忆，返回匹配的完整记忆内容。当 system prompt 里的\"已知用户信息\"摘要提到某条相关但不够详细时使用。",
      inputSchema: {
        type: "object",
        properties: { query: { type: "string", description: "要查询的关键词" } },
        required: ["query"],
      },
    },
    async execute(input, ctx: TenantContext) {
      const { query } = input as { query: string };
      const results = await memoryStore.search(query, ctx);
      // packages/sdk's runModelWithTools does `String(result.output)` before splicing this back
      // into the conversation — an array of objects would stringify to "[object Object],..."
      // garbage, so this must be a string, matching lookupExchangeRateTool/webSearchTool above.
      return { id: "", output: JSON.stringify(results) };
    },
  };
}
