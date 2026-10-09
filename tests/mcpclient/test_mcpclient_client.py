"""mcpclient.client 的真机测试——直接对 demo_server.py 发起真实 stdio 子进程连接，不 mock。"""
import asyncio
import socket
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


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestConnectAndListToolsHttp:
    async def test_returns_real_tool_info_over_http(self) -> None:
        port = _free_port()
        proc = await asyncio.create_subprocess_exec(
            sys.executable, _DEMO_SERVER, "--http", "--port", str(port),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            http_config = MCPServerConfig(transport="http", url=f"http://127.0.0.1:{port}/mcp")
            # demo server 启动（uvicorn 绑端口）需要一点时间，轮询代替固定 sleep。
            tools = None
            for _ in range(30):
                try:
                    tools = await connect_and_list_tools(http_config)
                    break
                except MCPConnectionError:
                    await asyncio.sleep(0.2)
            assert tools is not None, "demo server 在 6 秒内没有就绪"
            assert tools[0].name == "get_weather"

            result = await connect_and_call_tool(http_config, "get_weather", {"city": "Shanghai"})
            assert "Shanghai" in result
        finally:
            proc.terminate()
            await proc.wait()
