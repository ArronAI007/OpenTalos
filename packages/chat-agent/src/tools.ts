import type { Tool } from "@opentalos/core-types";

/**
 * Deterministic mock tool: no network, no real exchange-rate API, no API key required. Always
 * returns a fixed-shape (timestamped) answer so the whole demo is reproducible offline.
 */
export const lookupExchangeRateTool: Tool = {
  definition: {
    name: "lookup_exchange_rate",
    description: "Looks up today's exchange rate for a currency pair",
    inputSchema: { type: "object", properties: { pair: { type: "string" } }, required: ["pair"] },
  },
  async execute(input) {
    const { pair } = input as { pair: string };
    return {
      id: `rate-${Date.now()}`,
      output: `1 ${pair} = 7.13（模拟汇率，生成于 ${new Date().toISOString()}）`,
    };
  },
};
