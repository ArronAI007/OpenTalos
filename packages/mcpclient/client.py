"""MCP 客户端：官方 mcp SDK 的薄封装。每次调用都是全新连接、用完即断——不维护常驻会话
(和 packages/skill 的脚本执行同一个取舍：换来不用处理进程崩溃/重连/应用重启后连接丢失
等更复杂的生命周期问题)。"""
from dataclasses import dataclass, field
from typing import Any, Literal

import mcp


class MCPConnectionError(Exception):
    """连接失败/握手失败/工具调用失败统一包成这个异常，调用方（API 路由的校验分支、
    MCPTool.acall()）只需要认这一种异常类型，不用关心底层是 stdio 子进程起不来、HTTP
    连不上、还是官方 SDK 内部的哪种异常。"""


@dataclass
class MCPServerConfig:
    transport: Literal["stdio", "http"]
    command: str | None = None  # stdio 专用
    args: list[str] = field(default_factory=list)  # stdio 专用
    url: str | None = None  # http 专用


@dataclass
class MCPToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any]


def _connect_target(server_config: MCPServerConfig) -> "mcp.StdioServerParameters | str":
    if server_config.transport == "stdio":
        return mcp.StdioServerParameters(command=server_config.command, args=server_config.args)
    return server_config.url


async def connect_and_list_tools(server_config: MCPServerConfig) -> list[MCPToolInfo]:
    """连接一次、拿到 list_tools() 的结果、断开。用于"添加/刷新服务器"时探测可用工具。"""
    try:
        async with mcp.Client(_connect_target(server_config)) as client:
            result = await client.list_tools()
    except Exception as exc:  # noqa: BLE001
        raise MCPConnectionError(f"{type(exc).__name__}: {exc}") from exc
    return [
        MCPToolInfo(name=tool.name, description=tool.description or "", input_schema=tool.input_schema)
        for tool in result.tools
    ]


async def connect_and_call_tool(server_config: MCPServerConfig, tool_name: str, arguments: dict[str, Any]) -> str:
    """连接一次、调用一次工具、拿到文本结果、断开。"""
    try:
        async with mcp.Client(_connect_target(server_config)) as client:
            result = await client.call_tool(tool_name, arguments)
    except Exception as exc:  # noqa: BLE001
        raise MCPConnectionError(f"{type(exc).__name__}: {exc}") from exc
    text = "\n".join(getattr(block, "text", str(block)) for block in result.content)
    if result.is_error:
        raise MCPConnectionError(f"tool call returned an error: {text}")
    return text
