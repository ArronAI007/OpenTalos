"""对应 packages/tool-registry/src/in-memory-registry.ts。"""

from opentalos.core_types import TenantContext, Tool, ToolCall, ToolDefinition, ToolResult


class InMemoryToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.definition.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_definitions(self) -> list[ToolDefinition]:
        return [tool.definition for tool in self._tools.values()]

    async def execute(self, call: ToolCall, ctx: TenantContext) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(id=call.id, output=f"Unknown tool: {call.name}", is_error=True)
        try:
            result = await tool.execute(call.input, ctx)
            return result.model_copy(update={"id": call.id})
        except Exception as error:  # noqa: BLE001 — 故意捕获所有异常，转成错误结果而不是让它传播
            return ToolResult(id=call.id, output=str(error), is_error=True)
