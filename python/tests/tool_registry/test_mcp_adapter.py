import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer

from opentalos.core_types import TenantContext
from opentalos.tool_registry.mcp_adapter import create_mcp_tools

CTX = TenantContext(tenant_id="t1", session_id="s1")


def _build_server() -> MCPServer:
    server = MCPServer("test-server")

    @server.tool()
    def add(a: int, b: int) -> str:
        """Add two numbers."""
        return str(a + b)

    @server.tool()
    def always_fails() -> str:
        """A tool that reports an error."""
        raise RuntimeError("nope")

    return server


@pytest.mark.asyncio
async def test_adapts_and_executes_mcp_tool():
    server = _build_server()
    async with Client(server) as client:
        tools = await create_mcp_tools(client.session)
        add_tool = next(t for t in tools if t.definition.name == "add")
        result = await add_tool.execute({"a": 1, "b": 2}, CTX)
        assert result.output == "3"
        assert result.is_error is None or result.is_error is False


@pytest.mark.asyncio
async def test_mcp_tool_error_surfaces_is_error():
    server = _build_server()
    async with Client(server) as client:
        tools = await create_mcp_tools(client.session)
        failing_tool = next(t for t in tools if t.definition.name == "always_fails")
        result = await failing_tool.execute({}, CTX)
        assert result.is_error is True
