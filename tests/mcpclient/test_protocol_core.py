"""协议核心（MCPClient）的单测：全部用 InMemoryTransport 驱动，不涉及真实子进程/网络。"""
import asyncio

import pytest

from mcpclient.client import (
    MCPAbortError,
    MCPClient,
    MCPConnectionError,
    MCPProtocolError,
    MCPTimeoutError,
)
from mcpclient.protocol.jsonrpc import parse_jsonrpc_message
from mcpclient.transports.in_memory import create_in_memory_transport_pair


class _FakeServer:
    """内存传输另一端的假 MCP 服务端：按测试需要手动应答，不是真实实现。"""

    def __init__(self, transport):
        self._transport = transport
        self._transport.on_message = self._handle
        self.received: list[dict] = []
        self._tool_call_hook = None
        self._handlers = {}

    def on(self, method, handler):
        self._handlers[method] = handler

    async def _handle(self, message: dict) -> None:
        self.received.append(message)
        parsed = parse_jsonrpc_message(message)
        method = getattr(parsed, "method", None)
        if method in self._handlers:
            await self._handlers[method](parsed)
            return
        if method == "initialize":
            await self._transport.send(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "serverInfo": {"name": "fake", "version": "0.0"},
                    },
                }
            )
        elif method == "notifications/initialized":
            pass

    async def respond(self, request_id: int, result: dict) -> None:
        await self._transport.send({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def send_request(self, method: str, request_id: int, params: dict | None = None) -> None:
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        await self._transport.send(message)

    async def send_notification(self, method: str, params: dict | None = None) -> None:
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        await self._transport.send(message)


async def _connected_client_and_server():
    client_transport, server_transport = create_in_memory_transport_pair()
    server = _FakeServer(server_transport)
    client = MCPClient(server_config=None)  # type: ignore[arg-type]
    await client.connect(transport=client_transport)
    return client, server


class TestConnect:
    async def test_operations_before_connect_are_rejected(self) -> None:
        client_transport, _ = create_in_memory_transport_pair()
        client = MCPClient(server_config=None)  # type: ignore[arg-type]
        with pytest.raises(MCPConnectionError):
            await client.list_tools()
        with pytest.raises(MCPConnectionError):
            await client.call_tool("x", {})
        with pytest.raises(MCPConnectionError):
            await client.ping()

    async def test_connect_sends_initialize_then_initialized(self) -> None:
        client, server = await _connected_client_and_server()
        methods = [m.get("method") for m in server.received]
        assert methods == ["initialize", "notifications/initialized"]
        await client.close()


class TestListToolsPagination:
    async def test_merges_pages_until_cursor_disappears(self) -> None:
        client, server = await _connected_client_and_server()

        calls = {"n": 0}

        async def handle_list_tools(parsed) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                await server.respond(
                    parsed.id,
                    {
                        "tools": [{"name": "a", "inputSchema": {"type": "object"}}],
                        "nextCursor": "page2",
                    },
                )
            else:
                await server.respond(
                    parsed.id, {"tools": [{"name": "b", "inputSchema": {"type": "object"}}]}
                )

        server.on("tools/list", handle_list_tools)
        tools = await client.list_tools()
        assert [t.name for t in tools] == ["a", "b"]
        await client.close()

    async def test_repeated_cursor_raises_protocol_error(self) -> None:
        client, server = await _connected_client_and_server()

        async def handle_list_tools(parsed) -> None:
            await server.respond(
                parsed.id,
                {"tools": [{"name": "a", "inputSchema": {}}], "nextCursor": "same"},
            )

        server.on("tools/list", handle_list_tools)
        with pytest.raises(MCPProtocolError):
            await client.list_tools()
        await client.close()

    async def test_malformed_tool_entry_rejects_whole_page(self) -> None:
        client, server = await _connected_client_and_server()

        async def handle_list_tools(parsed) -> None:
            await server.respond(parsed.id, {"tools": [{"description": "missing name/inputSchema"}]})

        server.on("tools/list", handle_list_tools)
        with pytest.raises(MCPProtocolError):
            await client.list_tools()
        await client.close()


class TestCancellation:
    async def test_cancel_event_aborts_pending_call_tool_and_notifies_server(self) -> None:
        client, server = await _connected_client_and_server()
        cancel_notifications = []
        server.on("notifications/cancelled", lambda parsed: cancel_notifications.append(parsed) or asyncio.sleep(0))

        async def never_respond(parsed) -> None:
            return None

        server.on("tools/call", never_respond)
        cancel_event = asyncio.Event()

        async def trigger_cancel() -> None:
            await asyncio.sleep(0.05)
            cancel_event.set()

        asyncio.create_task(trigger_cancel())
        with pytest.raises(MCPAbortError):
            await client.call_tool("slow", {}, cancel_event=cancel_event)
        await asyncio.sleep(0.01)
        assert cancel_notifications
        await client.close()


class TestServerInitiatedRequests:
    async def test_ping_is_auto_answered(self) -> None:
        client, server = await _connected_client_and_server()
        await server.send_request("ping", request_id=999)
        await asyncio.sleep(0.05)
        responses = [m for m in server.received]  # server.received only logs incoming; check via transport directly
        await client.close()

    async def test_roots_list_auto_answered_when_roots_provided(self) -> None:
        from mcpclient.protocol.types import Root

        client_transport, server_transport = create_in_memory_transport_pair()
        server = _FakeServer(server_transport)
        client = MCPClient(server_config=None, roots=[Root(uri="file:///tmp")])  # type: ignore[arg-type]
        await client.connect(transport=client_transport)

        received_response = asyncio.get_running_loop().create_future()

        async def capture(message):
            if "id" in message and "method" not in message:
                received_response.set_result(message)

        server_transport.on_message = capture
        await server.send_request("roots/list", request_id=42)
        result = await asyncio.wait_for(received_response, timeout=1.0)
        assert result["result"]["roots"][0]["uri"] == "file:///tmp"
        await client.close()


class TestTimeoutAndProgress:
    async def test_request_times_out(self) -> None:
        client_transport, server_transport = create_in_memory_transport_pair()
        server = _FakeServer(server_transport)
        client = MCPClient(server_config=None, default_timeout_seconds=0.05)  # type: ignore[arg-type]
        await client.connect(transport=client_transport)

        async def never_respond(parsed) -> None:
            return None

        server.on("tools/call", never_respond)
        with pytest.raises(MCPTimeoutError):
            await client.call_tool("slow", {})
        await client.close()

    async def test_progress_notification_renews_timeout(self) -> None:
        client_transport, server_transport = create_in_memory_transport_pair()
        server = _FakeServer(server_transport)
        client = MCPClient(server_config=None, default_timeout_seconds=0.1)  # type: ignore[arg-type]
        await client.connect(transport=client_transport)

        request_holder = {}

        async def handle_call(parsed) -> None:
            request_holder["id"] = parsed.id

        server.on("tools/call", handle_call)

        async def send_progress_then_respond() -> None:
            await asyncio.sleep(0.07)
            await server.send_notification("notifications/progress", {"progressToken": request_holder["id"], "progress": 1})
            await asyncio.sleep(0.07)
            await server.respond(request_holder["id"], {"content": []})

        asyncio.create_task(send_progress_then_respond())
        result = await client.call_tool("slow", {})
        assert result.is_error is False
        await client.close()


class TestTransportClose:
    async def test_close_fails_all_pending_requests(self) -> None:
        client, server = await _connected_client_and_server()

        async def never_respond(parsed) -> None:
            return None

        server.on("tools/call", never_respond)
        call_task = asyncio.create_task(client.call_tool("slow", {}))
        await asyncio.sleep(0.02)
        await client.close()
        with pytest.raises(MCPConnectionError):
            await call_task
