"""mcpclient.client 的真机测试——直接对 demo_server.py 发起真实 stdio/HTTP 子进程连接，不 mock。"""
import asyncio
import socket
import sys
from pathlib import Path

import pytest

from mcpclient.client import MCPClient, MCPConnectionError, MCPServerConfig

_DEMO_SERVER = str(Path(__file__).resolve().parent.parent.parent / "packages" / "mcpclient" / "demo_server.py")


def _stdio_config() -> MCPServerConfig:
    return MCPServerConfig(transport="stdio", command=sys.executable, args=[_DEMO_SERVER])


class TestConnectAndListToolsStdio:
    async def test_returns_real_tool_info(self) -> None:
        async with MCPClient(_stdio_config()) as client:
            tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "get_weather"
        assert "properties" in tools[0].input_schema

    async def test_bad_command_raises_connection_error(self) -> None:
        bad = MCPServerConfig(transport="stdio", command="no-such-executable-xyz", args=[])
        with pytest.raises(MCPConnectionError):
            async with MCPClient(bad):
                pass


class TestConnectAndCallToolStdio:
    async def test_returns_real_weather_text(self) -> None:
        async with MCPClient(_stdio_config()) as client:
            result = await client.call_tool("get_weather", {"city": "Beijing"})
        assert not result.is_error
        assert any("Beijing" in getattr(block, "text", "") for block in result.content)

    async def test_persistent_session_reuses_one_connection_across_calls(self) -> None:
        """SC-006：同一个 MCPClient 连续调用两次工具，只建立一次连接（不像旧的
        connect_and_call_tool 那样每次都重新握手）。"""
        client = MCPClient(_stdio_config())
        await client.connect()
        try:
            pid_before = client._transport._process.pid
            await client.call_tool("get_weather", {"city": "Beijing"})
            await client.call_tool("get_weather", {"city": "Shanghai"})
            pid_after = client._transport._process.pid
            assert pid_before == pid_after
        finally:
            await client.close()


class TestServerConfigEnvPassthrough:
    def test_stdio_config_carries_env(self) -> None:
        config = MCPServerConfig(transport="stdio", command="x", args=["y"], env={"FOO": "bar"})
        assert config.env == {"FOO": "bar"}

    def test_stdio_config_without_env_defaults_to_none(self) -> None:
        config = MCPServerConfig(transport="stdio", command="x", args=["y"])
        assert config.env is None


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
            client = None
            for _ in range(30):
                try:
                    client = MCPClient(http_config)
                    await client.connect()
                    break
                except MCPConnectionError:
                    client = None
                    await asyncio.sleep(0.2)
            assert client is not None, "demo server 在 6 秒内没有就绪"
            try:
                tools = await client.list_tools()
                assert tools[0].name == "get_weather"

                result = await client.call_tool("get_weather", {"city": "Shanghai"})
                assert any("Shanghai" in getattr(block, "text", "") for block in result.content)
            finally:
                await client.close()
        finally:
            proc.terminate()
            await proc.wait()
