"""Streamable HTTP 传输测试：用一个手写的最小 ASGI handler（httpx.ASGITransport 驱动，不依赖
真实网络）覆盖往返/自定义请求头/405 GET 流；断线重连续传直接针对 `_consume_response_stream_
with_resume` 这个具体方法做白盒测试（真实网络中途断开在测试环境里无法可靠复现，直接验证重连
逻辑本身更确定）。"""
import json
from typing import Any

import httpx

from mcp.client import MCPClient, MCPServerConfig
from mcp.transports.streamable_http import StreamableHttpTransport, consume_sse_stream


class _FakeHttpMcpApp:
    """最小 ASGI 应用：对每个 POST 请求回一个单事件 SSE 流；GET 一律 405。"""

    def __init__(self) -> None:
        self.received_headers: list[dict[str, str]] = []

    async def __call__(self, scope, receive, send) -> None:
        assert scope["type"] == "http"
        headers = {k.decode(): v.decode() for k, v in scope["headers"]}
        self.received_headers.append(headers)
        if scope["method"] == "GET":
            await send({"type": "http.response.start", "status": 405, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        body = b""
        more_body = True
        while more_body:
            message = await receive()
            body += message.get("body", b"")
            more_body = message.get("more_body", False)
        request_message = json.loads(body)
        if "id" not in request_message:
            await send({"type": "http.response.start", "status": 202, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        result = self._build_result(request_message)
        response_obj = {"jsonrpc": "2.0", "id": request_message["id"], "result": result}
        sse_body = f"data: {json.dumps(response_obj)}\n\n".encode()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/event-stream"),
                    (b"mcp-session-id", b"session-abc"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": sse_body})

    def _build_result(self, message: dict[str, Any]) -> dict[str, Any]:
        method = message.get("method")
        if method == "initialize":
            return {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "serverInfo": {"name": "fake-http", "version": "0.0"},
            }
        if method == "tools/list":
            return {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}
        if method == "tools/call":
            return {"content": [{"type": "text", "text": "ok"}]}
        return {}


def _make_client_against(app: _FakeHttpMcpApp) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fakehost")


class TestRoundTrip:
    async def test_initialize_list_tools_call_tool_over_sse(self) -> None:
        app = _FakeHttpMcpApp()
        http_client = _make_client_against(app)
        transport = StreamableHttpTransport("http://fakehost/mcp", client=http_client)
        client = MCPClient(MCPServerConfig(transport="http", url="http://fakehost/mcp"))
        await client.connect(transport=transport)
        try:
            tools = await client.list_tools()
            assert tools[0].name == "echo"
            result = await client.call_tool("echo", {})
            assert not result.is_error
        finally:
            await client.close()


class TestCustomHeaders:
    async def test_custom_headers_appear_on_every_request(self) -> None:
        app = _FakeHttpMcpApp()
        http_client = _make_client_against(app)
        transport = StreamableHttpTransport(
            "http://fakehost/mcp", headers={"X-Api-Key": "secret-123"}, client=http_client
        )
        client = MCPClient(MCPServerConfig(transport="http", url="http://fakehost/mcp"))
        await client.connect(transport=transport)
        try:
            await client.list_tools()
        finally:
            await client.close()
        post_requests = [h for h in app.received_headers if h.get("x-api-key")]
        assert len(post_requests) >= 2  # initialize + list_tools 至少两次
        assert all(h["x-api-key"] == "secret-123" for h in post_requests)


class TestGetStream405Tolerance:
    async def test_405_on_get_stream_does_not_raise(self) -> None:
        app = _FakeHttpMcpApp()
        http_client = _make_client_against(app)
        transport = StreamableHttpTransport("http://fakehost/mcp", client=http_client)
        client = MCPClient(MCPServerConfig(transport="http", url="http://fakehost/mcp"))
        await client.connect(transport=transport)  # connect() 触发 set_protocol_version -> start_push_stream
        import asyncio

        await asyncio.sleep(0.05)
        assert transport._get_stream_task is not None
        assert transport._get_stream_task.done()
        assert transport._get_stream_task.exception() is None
        await client.close()


class TestSseFrameParsing:
    async def test_consume_sse_stream_reassembles_multiline_data_and_id(self) -> None:
        async def lines():
            for line in ["id: 42", "data: hello", "data: world", ""]:
                yield line

        events = [event async for event in consume_sse_stream(lines())]
        assert len(events) == 1
        assert events[0].id == "42"
        assert events[0].data == "hello\nworld"


class TestReconnectWithResume:
    async def test_dropped_stream_resumes_via_last_event_id_without_loss(self) -> None:
        """白盒测试：直接驱动 `_consume_response_stream_with_resume`，第一次响应流在发了一条
        progress 事件后中途抛出模拟的网络错误，第二次（重连后，带 Last-Event-ID）响应流带着真
        正的最终结果——验证客户端能拿到完整、不丢失的内容。"""

        class _FakeResponse:
            def __init__(self, lines: list[str], *, raise_after: int | None = None) -> None:
                self._lines = lines
                self._raise_after = raise_after
                self.closed = False

            async def aiter_lines(self):
                for i, line in enumerate(self._lines):
                    yield line
                    if self._raise_after is not None and i == self._raise_after:
                        raise httpx.ReadError("simulated mid-stream drop")

            async def aclose(self) -> None:
                self.closed = True

        first_response = _FakeResponse(["id: 1", "data: {\"progress\": true}", ""], raise_after=2)
        final_payload = json.dumps({"jsonrpc": "2.0", "id": 7, "result": {"content": []}})
        second_response = _FakeResponse(["id: 2", f"data: {final_payload}", ""])

        app = _FakeHttpMcpApp()
        http_client = _make_client_against(app)
        transport = StreamableHttpTransport(
            "http://fakehost/mcp", client=http_client, initial_delay_seconds=0.01, max_delay_seconds=0.01
        )

        captured_last_event_id = {}

        async def fake_send(request, **kwargs):
            captured_last_event_id["value"] = request.headers.get("last-event-id")
            return second_response

        transport._client.send = fake_send

        received_messages = []
        transport.on_message = lambda message: received_messages.append(message) or _noop()

        await transport._consume_response_stream_with_resume(first_response)  # type: ignore[arg-type]

        assert captured_last_event_id["value"] == "1"
        # 两条消息都该收到（流层不做协议语义判断，只负责转发）：第一次响应流里的 progress
        # 事件，加上重连续传后的真正最终结果，没有丢失任何一条。
        assert received_messages == [
            {"progress": True},
            {"jsonrpc": "2.0", "id": 7, "result": {"content": []}},
        ]
        assert first_response.closed
        assert second_response.closed


async def _noop() -> None:
    return None
