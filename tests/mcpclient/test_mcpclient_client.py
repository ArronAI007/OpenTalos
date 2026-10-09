"""mcpclient.client 的真机测试——直接对 demo_server.py 发起真实 stdio 子进程连接，不 mock。"""
import sys
from pathlib import Path

import pytest

from mcpclient.client import MCPConnectionError, MCPServerConfig, connect_and_call_tool, connect_and_list_tools

_DEMO_SERVER = str(Path(__file__).resolve().parent.parent.parent / "packages" / "mcpclient" / "demo_server.py")


def _stdio_config() -> MCPServerConfig:
    return MCPServerConfig(transport="stdio", command=sys.executable, args=[_DEMO_SERVER])


class TestConnectAndListToolsStdio:
    async def test_returns_real_tool_info(self) -> None:
        tools = await connect_and_list_tools(_stdio_config())
        assert len(tools) == 1
        assert tools[0].name == "get_weather"
        assert "properties" in tools[0].input_schema

    async def test_bad_command_raises_connection_error(self) -> None:
        bad = MCPServerConfig(transport="stdio", command="no-such-executable-xyz", args=[])
        with pytest.raises(MCPConnectionError):
            await connect_and_list_tools(bad)


class TestConnectAndCallToolStdio:
    async def test_returns_real_weather_text(self) -> None:
        result = await connect_and_call_tool(_stdio_config(), "get_weather", {"city": "Beijing"})
        assert "Beijing" in result
