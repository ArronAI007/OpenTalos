"""把一个 MCP 工具包装成这个项目的 Tool 接口——agent 侧完全无感知这是 MCP 来源。"""
from typing import Any

from tool.outcome import ToolOutcome
from tool.tool import Tool, ToolParameter

from .client import MCPConnectionError, MCPServerConfig, MCPToolInfo, connect_and_call_tool


def _json_schema_to_parameters(schema: dict) -> list[ToolParameter]:
    """把 MCP 工具的标准 JSON Schema input_schema 转成 ToolParameter 列表——只处理
    object/properties/required 这个最常见的顶层结构，字段级别的 type 直接透传
    （string/number/boolean/array 等 JSON Schema 基础类型和 ToolParameter.type 同名）。"""
    required = set(schema.get("required", []))
    return [
        ToolParameter(
            name=name,
            type=prop.get("type", "string"),
            description=prop.get("description", ""),
            required=name in required,
            enum=prop.get("enum"),
            items=prop.get("items", {}).get("type") if prop.get("type") == "array" else None,
        )
        for name, prop in schema.get("properties", {}).items()
    ]


class MCPTool(Tool):
    """一个 (server, tool_name) 组合对应一个 MCPTool 实例。描述/参数 schema 来自探测时缓存的
    MCPToolInfo，acall() 时才真正建立连接执行。"""

    def __init__(self, server_config: MCPServerConfig, tool_info: MCPToolInfo) -> None:
        # MCP 工具来源不可信且行为未知，统一要求人工审批；输出也按不可信外部内容隔离。
        super().__init__(
            name=tool_info.name,
            description=tool_info.description,
            requires_approval=True,
            untrusted_output=True,
        )
        self._server_config = server_config
        self._tool_info = tool_info

    def parameters(self) -> list[ToolParameter]:
        return _json_schema_to_parameters(self._tool_info.input_schema)

    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
        try:
            result = await connect_and_call_tool(self._server_config, self._tool_info.name, arguments)
        except MCPConnectionError as error:
            return ToolOutcome.error(str(error))
        return ToolOutcome.ok(result)
