"""Streamable HTTP 传输：httpx 流式 POST/GET + 手写 SSE 帧解析 + 断线重连续传。

对齐 pi `transports/streamable-http.ts`：POST 发请求，响应可能是一次性 JSON，也可能是 SSE
流；流中途断开时用 `Last-Event-ID` 续传，指数退避重连。"""
import asyncio
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from .base import TransportEventsMixin

MAX_EVENT_BYTES = 1 * 1024 * 1024
DEFAULT_MAX_RETRIES = 5
DEFAULT_INITIAL_DELAY_SECONDS = 1.0
DEFAULT_MAX_DELAY_SECONDS = 30.0


class McpHttpError(Exception):
    pass


@dataclass
class SseEvent:
    event: str | None
    data: str
    id: str | None
    retry: float | None


async def consume_sse_stream(lines: AsyncIterator[str]) -> AsyncIterator[SseEvent]:
    """把一个已按行拆分好的文本流（httpx 的 `aiter_lines()` 已经处理了字节层面的分片重组）
    重新组装成 SSE 事件——这一层才是 SSE 协议本身的语义（`data:`/`event:`/`id:`/`retry:`
    字段、空行分隔事件），不是任何 HTTP 库提供的能力。"""
    event_type: str | None = None
    data_lines: list[str] = []
    event_id: str | None = None
    retry: float | None = None
    byte_count = 0

    async for line in lines:
        if line == "":
            if data_lines:
                yield SseEvent(event=event_type, data="\n".join(data_lines), id=event_id, retry=retry)
            event_type, data_lines, retry = None, [], None
            byte_count = 0
            continue
        byte_count += len(line.encode("utf-8"))
        if byte_count > MAX_EVENT_BYTES:
            raise McpHttpError("a single SSE event exceeded the configured size limit")
        if line.startswith("data:"):
            data_lines.append(line[len("data:"):].lstrip(" "))
        elif line.startswith("event:"):
            event_type = line[len("event:"):].lstrip(" ")
        elif line.startswith("id:"):
            event_id = line[len("id:"):].lstrip(" ")
        elif line.startswith("retry:"):
            try:
                retry = float(line[len("retry:"):].strip()) / 1000.0
            except ValueError:
                pass
    if data_lines:
        yield SseEvent(event=event_type, data="\n".join(data_lines), id=event_id, retry=retry)


class StreamableHttpTransport(TransportEventsMixin):
    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        auth_provider: Any | None = None,
        client: httpx.AsyncClient | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        initial_delay_seconds: float = DEFAULT_INITIAL_DELAY_SECONDS,
        max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
    ) -> None:
        super().__init__()
        self._url = url
        self._headers = dict(headers) if headers else {}
        self._auth_provider = auth_provider
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self._max_retries = max_retries
        self._initial_delay_seconds = initial_delay_seconds
        self._max_delay_seconds = max_delay_seconds
        self._session_id: str | None = None
        self._protocol_version: str | None = None
        self._last_event_id: str | None = None
        self._get_stream_task: asyncio.Task[None] | None = None
        self._closed = False

    def set_protocol_version(self, version: str) -> None:
        self._protocol_version = version
        self.start_push_stream()

    def _request_headers(self, *, accept: str, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Accept": accept, "Content-Type": "application/json", **self._headers}
        if self._session_id is not None:
            headers["Mcp-Session-Id"] = self._session_id
        if self._protocol_version is not None:
            headers["MCP-Protocol-Version"] = self._protocol_version
        if extra:
            headers.update(extra)
        return headers

    async def _apply_auth_header(self, headers: dict[str, str]) -> None:
        if self._auth_provider is not None:
            token = await self._auth_provider.token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

    async def start(self) -> None:
        return None

    async def send(self, message: dict[str, Any]) -> None:
        headers = self._request_headers(accept="application/json, text/event-stream")
        await self._apply_auth_header(headers)
        request = self._client.build_request("POST", self._url, json=message, headers=headers)
        response = await self._client.send(request, stream=True)
        await self._handle_authorized_response(response, method="POST", json=message, headers=headers)

    async def _handle_authorized_response(
        self, response: httpx.Response, *, method: str, json: dict[str, Any] | None, headers: dict[str, str]
    ) -> None:
        if response.status_code == 401 or response.status_code == 403:
            body = await response.aread()
            await response.aclose()
            needs_reauth = response.status_code == 401 or b"insufficient_scope" in body
            if not needs_reauth or self._auth_provider is None:
                # 不把响应体拼进异常信息：鉴权失败的响应体来自服务端，可能回显请求里的敏感
                # 内容（比如格式错误时把收到的 Authorization 头原样吐回来），不值得为了调试
                # 方便冒这个泄露风险。
                raise McpHttpError(f"HTTP {response.status_code}: authorization failed")
            await self._auth_provider.on_unauthorized()
            await self._apply_auth_header(headers)
            retry_request = self._client.build_request(method, self._url, json=json, headers=headers)
            response = await self._client.send(retry_request, stream=True)
        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id
        if response.status_code >= 400:
            body = await response.aread()
            await response.aclose()
            raise McpHttpError(f"HTTP {response.status_code}: {body!r}")
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            body = await response.aread()
            await response.aclose()
            if body:
                payload = json_module_loads(body)
                for item in payload if isinstance(payload, list) else [payload]:
                    await self._emit_message(item)
            return
        if content_type.startswith("text/event-stream"):
            await self._consume_response_stream_with_resume(response)
            return
        await response.aread()
        await response.aclose()

    async def _consume_response_stream_with_resume(self, response: httpx.Response) -> None:
        attempt = 0
        current_response = response
        try:
            while True:
                try:
                    async for event in consume_sse_stream(current_response.aiter_lines()):
                        if event.id:
                            self._last_event_id = event.id
                        if event.data:
                            await self._emit_message(json_module_loads(event.data))
                    return  # 流正常结束（服务端关闭），不是意外断开
                except (httpx.StreamError, httpx.HTTPError):
                    pass
                finally:
                    await current_response.aclose()
                attempt += 1
                if attempt > self._max_retries:
                    raise McpHttpError("SSE stream dropped and exceeded max reconnect attempts")
                delay = min(self._initial_delay_seconds * (2 ** (attempt - 1)), self._max_delay_seconds)
                await asyncio.sleep(delay)
                headers = self._request_headers(accept="text/event-stream")
                if self._last_event_id:
                    headers["Last-Event-ID"] = self._last_event_id
                current_response = await self._client.send(
                    self._client.build_request("GET", self._url, headers=headers), stream=True
                )
        finally:
            pass

    def start_push_stream(self) -> None:
        if self._get_stream_task is not None:
            return
        self._get_stream_task = asyncio.create_task(self._run_get_stream())

    async def _run_get_stream(self) -> None:
        attempt = 0
        while not self._closed:
            try:
                headers = self._request_headers(accept="text/event-stream")
                if self._last_event_id:
                    headers["Last-Event-ID"] = self._last_event_id
                response = await self._client.send(
                    self._client.build_request("GET", self._url, headers=headers), stream=True
                )
                if response.status_code == 405:
                    await response.aclose()
                    return  # 服务端不提供 GET 流：正常情况，不是错误
                if response.status_code >= 400:
                    await response.aclose()
                    return
                async for event in consume_sse_stream(response.aiter_lines()):
                    if event.id:
                        self._last_event_id = event.id
                    if event.data:
                        await self._emit_message(json_module_loads(event.data))
                await response.aclose()
                return
            except (httpx.StreamError, httpx.HTTPError):
                attempt += 1
                if attempt > self._max_retries:
                    return
                delay = min(self._initial_delay_seconds * (2 ** (attempt - 1)), self._max_delay_seconds)
                await asyncio.sleep(delay)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._get_stream_task is not None:
            self._get_stream_task.cancel()
        if self._owns_client:
            await self._client.aclose()
        await self._emit_close()


def json_module_loads(data: Any) -> Any:
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    return json.loads(data)
