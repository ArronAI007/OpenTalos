import type { Tool } from "@opentalos/core-types";

export const searchTool: Tool = {
  definition: {
    name: "search",
    description: "Looks up findings for a research topic",
    inputSchema: { type: "object", properties: { query: { type: "string" } }, required: ["query"] },
  },
  async execute(input) {
    const { query } = input as { query: string };
    return {
      id: `search-result-${Date.now()}`,
      output: [`${query} is a widely studied subject`, `${query} has active open-source implementations`],
    };
  },
};
