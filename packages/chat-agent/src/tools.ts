import type { Tool } from "@opentalos/core-types";

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
