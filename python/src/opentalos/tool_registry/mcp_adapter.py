"""对应 packages/tool-registry/src/mcp-adapter.ts —— 把一个 MCP ClientSession 的工具集适配成
本仓库的 Tool 列表。"""

from dataclasses import dataclass
from typing import Any

from mcp import ClientSession
from mcp.types import CallToolResult, TextContent

from opentalos.core_types import TenantContext, ToolDefinition, ToolResult


def _extract_text(result: CallToolResult) -> str:
    return "".join(block.text for block in result.content if isinstance(block, TextContent))


@dataclass
class _McpTool:
    definition: ToolDefinition
    _session: ClientSession

    async def execute(self, input: Any, ctx: TenantContext) -> ToolResult:
        result = await self._session.call_tool(self.definition.name, arguments=input or {})
        return ToolResult(
            id=f"{self.definition.name}-mcp",
            output=_extract_text(result),
            is_error=bool(result.is_error),
        )


async def create_mcp_tools(session: ClientSession) -> list[_McpTool]:
    listed = await session.list_tools()
    return [
        _McpTool(
            definition=ToolDefinition(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.input_schema or {},
            ),
            _session=session,
        )
        for tool in listed.tools
    ]
