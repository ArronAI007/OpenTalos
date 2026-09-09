import type { Client } from "@modelcontextprotocol/sdk/client/index.js";
import type { JSONSchema, Tool, ToolResult } from "@opentalos/core-types";

interface McpTextContent {
  type: "text";
  text: string;
}

function extractText(content: unknown): string {
  if (!Array.isArray(content)) return "";
  return content
    .filter((block): block is McpTextContent => (block as McpTextContent).type === "text")
    .map((block) => block.text)
    .join("");
}

export async function createMcpTools(client: Client): Promise<Tool[]> {
  const { tools } = await client.listTools();
  return tools.map((mcpTool) => ({
    definition: {
      name: mcpTool.name,
      description: mcpTool.description ?? "",
      inputSchema: (mcpTool.inputSchema ?? {}) as JSONSchema,
    },
    async execute(input: unknown): Promise<ToolResult> {
      const result = await client.callTool({
        name: mcpTool.name,
        arguments: input as Record<string, unknown>,
      });
      return {
        id: `${mcpTool.name}-${Date.now()}`,
        output: extractText("content" in result ? result.content : undefined),
        isError: Boolean("isError" in result && result.isError),
      };
    },
  }));
}
