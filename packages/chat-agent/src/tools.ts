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
