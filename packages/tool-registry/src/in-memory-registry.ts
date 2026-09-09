import type { TenantContext, Tool, ToolCall, ToolDefinition, ToolRegistry, ToolResult } from "@opentalos/core-types";

export class InMemoryToolRegistry implements ToolRegistry {
  private readonly tools = new Map<string, Tool>();

  register(tool: Tool): void {
    this.tools.set(tool.definition.name, tool);
  }

  get(name: string): Tool | undefined {
    return this.tools.get(name);
  }

  list(): ToolDefinition[] {
    return [...this.tools.values()].map((tool) => tool.definition);
  }

  async execute(call: ToolCall, ctx: TenantContext): Promise<ToolResult> {
    const tool = this.tools.get(call.name);
    if (!tool) {
      return { id: call.id, output: `Unknown tool: ${call.name}`, isError: true };
    }
    try {
      return { ...(await tool.execute(call.input, ctx)), id: call.id };
    } catch (error) {
      return { id: call.id, output: error instanceof Error ? error.message : String(error), isError: true };
    }
  }
}
