"""MCP 客户端：不依赖官方 mcp SDK 的从零实现（对齐 earendil-works/pi 的 packages/mcp）。

`MCPClient` 是一个持久会话对象——构造一次、`connect()` 一次，之后反复调用 `list_tools()`/
`call_tool()`/`ping()`，直到显式 `close()` 或底层传输掉线。"""
import asyncio
import itertools
from dataclasses import dataclass, field
from typing import Any, Literal

from .protocol.content import CallToolResult
from .protocol.jsonrpc import (
    JSON_RPC_ERROR_CODES,
    JsonRpcErrorObject,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    parse_jsonrpc_message,
)
from .protocol.types import (
    SUPPORTED_PROTOCOL_VERSIONS,
    ClientCapabilities,
    Implementation,
    Root,
    ServerCapabilities,
    is_resource,
    is_resource_template,
    is_tool,
)
from .transports.base import McpTransport


class MCPConnectionError(Exception):
    """连接失败/握手失败/工具调用失败统一包成这个异常，调用方（API 路由的校验分支、
    MCPTool.acall()）只需要认这一种异常类型，不用关心底层是 stdio 子进程起不来、HTTP
    连不上、还是协议核心内部的哪种具体错误。下面的细粒度子类都继承自它，不破坏现有
    `except MCPConnectionError` 分支（FR-008）。"""


class MCPTimeoutError(MCPConnectionError):
    """一次请求超过超时时间仍未收到响应（含收到过 progress 通知后续期的情形）。"""


class MCPAbortError(MCPConnectionError):
    """调用方主动取消了一次尚未返回的请求。"""


class MCPProtocolError(MCPConnectionError):
    """协议层面的错误：重复 cursor、分页结果形状不合法、响应 id 不匹配等。"""


class MCPConfigValidationError(MCPConnectionError):
    """MCPServerConfig 从持久化存储加载时结构校验失败。"""


@dataclass
class MCPServerConfig:
    transport: Literal["stdio", "http"]
    command: str | None = None  # stdio 专用
    args: list[str] = field(default_factory=list)  # stdio 专用
    url: str | None = None  # http 专用
    env: dict[str, str] | None = None  # stdio 专用，透传给子进程（例如 API key）
    headers: dict[str, str] | None = None  # http 专用，鉴权/代理场景的自定义请求头


def validate_server_config(data: dict[str, Any]) -> MCPServerConfig:
    """`MCPServerConfig` 从持久化存储（`apps/api/db.py` 的 `mcp_servers` 表）加载出来时的结构
    校验（FR-002）：必需字段缺失/类型不对必须在构造客户端之前报出清晰、指向具体字段的错误。"""
    transport = data.get("transport")
    if transport not in ("stdio", "http"):
        raise MCPConfigValidationError(
            f"MCPServerConfig.transport 必须是 'stdio' 或 'http'，收到: {transport!r}"
        )
    if transport == "stdio":
        command = data.get("command")
        if not isinstance(command, str) or not command:
            raise MCPConfigValidationError(
                f"transport='stdio' 时 command 必须是非空字符串，收到: {command!r}"
            )
        args = data.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise MCPConfigValidationError(f"args 必须是字符串列表，收到: {args!r}")
        env = data.get("env")
        if env is not None and (
            not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())
        ):
            raise MCPConfigValidationError(f"env 必须是 str->str 的字典，收到: {env!r}")
        return MCPServerConfig(transport="stdio", command=command, args=list(args), env=env)
    url = data.get("url")
    if not isinstance(url, str) or not url:
        raise MCPConfigValidationError(f"transport='http' 时 url 必须是非空字符串，收到: {url!r}")
    headers = data.get("headers")
    if headers is not None and (
        not isinstance(headers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items())
    ):
        raise MCPConfigValidationError(f"headers 必须是 str->str 的字典，收到: {headers!r}")
    return MCPServerConfig(transport="http", url=url, headers=headers)


@dataclass
class MCPToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class _PendingRequest:
    future: "asyncio.Future[Any]"
    timeout_seconds: float
    timer_task: "asyncio.Task[None] | None" = None
    cancel_event: asyncio.Event | None = None
    progress_token: str | None = None


_DEFAULT_TIMEOUT_SECONDS = 30.0


class MCPClient:
    """持久会话：构造一次、`connect()` 一次，之后反复调用直到 `close()`。"""

    def __init__(
        self,
        server_config: MCPServerConfig,
        *,
        roots: list[Root] | None = None,
        client_info: Implementation | None = None,
        default_timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._server_config = server_config
        self._roots = roots
        self._client_info = client_info or Implementation(name="opentalos-mcpclient", version="0.1.0")
        self._default_timeout_seconds = default_timeout_seconds
        self._transport: McpTransport | None = None
        self._pending: dict[int, _PendingRequest] = {}
        self._request_id_counter = itertools.count(1)
        self._server_capabilities: ServerCapabilities | None = None
        self._protocol_version: str | None = None
        self._connected = False

    def _build_transport(self) -> McpTransport:
        if self._server_config.transport == "stdio":
            from .transports.stdio import StdioTransport

            return StdioTransport(
                self._server_config.command, self._server_config.args, env=self._server_config.env
            )
        if self._server_config.transport == "http":
            from .transports.streamable_http import StreamableHttpTransport

            return StreamableHttpTransport(self._server_config.url, headers=self._server_config.headers)
        raise MCPConnectionError(f"unsupported transport: {self._server_config.transport!r}")

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise MCPConnectionError("not connected: call connect() first")

    async def connect(self, *, transport: McpTransport | None = None) -> None:
        self._transport = transport if transport is not None else self._build_transport()
        self._transport.on_message = self._handle_message
        self._transport.on_close = self._handle_close
        try:
            await self._transport.start()
            capabilities = ClientCapabilities(roots={"listChanged": False} if self._roots is not None else None)
            params = {
                "protocolVersion": SUPPORTED_PROTOCOL_VERSIONS[0],
                "capabilities": {k: v for k, v in vars(capabilities).items() if v is not None},
                "clientInfo": {"name": self._client_info.name, "version": self._client_info.version},
            }
            result = await self._request("initialize", params, timeout_seconds=self._default_timeout_seconds)
        except MCPConnectionError:
            raise
        except Exception as exc:  # noqa: BLE001 — 握手窗口期的任何失败都统一包成 MCPConnectionError
            raise MCPConnectionError(f"{type(exc).__name__}: {exc}") from exc
        negotiated_version = result.get("protocolVersion")
        if negotiated_version not in SUPPORTED_PROTOCOL_VERSIONS:
            await self._transport.close()
            raise MCPProtocolError(
                f"server negotiated unsupported protocol version: {negotiated_version!r}"
            )
        self._protocol_version = negotiated_version
        self._server_capabilities = result.get("capabilities")
        if hasattr(self._transport, "set_protocol_version"):
            self._transport.set_protocol_version(negotiated_version)
        await self._notify("notifications/initialized", None)
        self._connected = True

    async def _request(
        self,
        method: str,
        params: dict[str, Any] | None,
        *,
        timeout_seconds: float,
        cancel_event: asyncio.Event | None = None,
    ) -> Any:
        request_id = next(self._request_id_counter)
        progress_token = str(request_id)
        sent_params = dict(params) if params is not None else {}
        sent_params["_meta"] = {"progressToken": progress_token}
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        pending = _PendingRequest(
            future=future, timeout_seconds=timeout_seconds, cancel_event=cancel_event, progress_token=progress_token
        )
        self._pending[request_id] = pending
        pending.timer_task = asyncio.create_task(self._watch_timeout(request_id))
        cancel_watch_task = None
        if cancel_event is not None:
            cancel_watch_task = asyncio.create_task(self._watch_cancel(request_id, cancel_event))
        try:
            await self._transport.send(
                JsonRpcRequest(id=request_id, method=method, params=sent_params).to_dict()
            )
            return await future
        finally:
            self._pending.pop(request_id, None)
            if pending.timer_task is not None:
                pending.timer_task.cancel()
            if cancel_watch_task is not None:
                cancel_watch_task.cancel()

    async def _notify(self, method: str, params: dict[str, Any] | None) -> None:
        await self._transport.send(JsonRpcNotification(method=method, params=params).to_dict())

    async def _watch_timeout(self, request_id: int) -> None:
        pending = self._pending.get(request_id)
        if pending is None:
            return
        try:
            await asyncio.sleep(pending.timeout_seconds)
        except asyncio.CancelledError:
            return
        pending = self._pending.get(request_id)
        if pending is None or pending.future.done():
            return
        pending.future.set_exception(MCPTimeoutError(f"request {request_id} timed out"))

    def _restart_timeout(self, request_id: int, pending: "_PendingRequest") -> None:
        if pending.timer_task is not None:
            pending.timer_task.cancel()
        pending.timer_task = asyncio.create_task(self._watch_timeout(request_id))

    async def _watch_cancel(self, request_id: int, cancel_event: asyncio.Event) -> None:
        await cancel_event.wait()
        pending = self._pending.get(request_id)
        if pending is None or pending.future.done():
            return
        pending.future.set_exception(MCPAbortError("request was cancelled by the caller"))
        await self._notify("notifications/cancelled", {"requestId": request_id, "reason": "client cancelled"})

    async def _handle_message(self, message: dict[str, Any]) -> None:
        parsed = parse_jsonrpc_message(message)
        if isinstance(parsed, JsonRpcResponse):
            await self._handle_response(parsed)
        elif isinstance(parsed, JsonRpcRequest):
            await self._handle_server_request(parsed)
        elif isinstance(parsed, JsonRpcNotification):
            await self._handle_notification(parsed)

    async def _handle_response(self, response: JsonRpcResponse) -> None:
        pending = self._pending.get(response.id)
        if pending is None or pending.future.done():
            return  # 未知/重复响应 id：安全忽略（Edge Case）
        if response.error is not None:
            pending.future.set_exception(MCPConnectionError(f"{response.error.code}: {response.error.message}"))
        else:
            pending.future.set_result(response.result)

    async def _handle_notification(self, notification: JsonRpcNotification) -> None:
        if notification.method == "notifications/progress" and notification.params:
            token = str(notification.params.get("progressToken"))
            for request_id, pending in self._pending.items():
                if pending.progress_token == token:
                    self._restart_timeout(request_id, pending)

    async def _handle_server_request(self, request: JsonRpcRequest) -> None:
        if request.method == "ping":
            await self._transport.send(JsonRpcResponse(id=request.id, result={}).to_dict())
            return
        if request.method == "roots/list":
            if self._roots is not None:
                result = {"roots": [{"uri": r.uri, **({"name": r.name} if r.name else {})} for r in self._roots]}
                await self._transport.send(JsonRpcResponse(id=request.id, result=result).to_dict())
            else:
                error = JsonRpcErrorObject(
                    code=JSON_RPC_ERROR_CODES.METHOD_NOT_FOUND, message="roots not provided by this client"
                )
                await self._transport.send(JsonRpcResponse(id=request.id, error=error).to_dict())
            return
        error = JsonRpcErrorObject(code=JSON_RPC_ERROR_CODES.METHOD_NOT_FOUND, message=f"unknown method: {request.method}")
        await self._transport.send(JsonRpcResponse(id=request.id, error=error).to_dict())

    async def _handle_close(self) -> None:
        self._connected = False
        error = MCPConnectionError("connection closed")
        for pending in list(self._pending.values()):
            if not pending.future.done():
                pending.future.set_exception(error)

    async def _list_all(self, method: str, result_key: str, validator) -> list[dict[str, Any]]:
        self._ensure_connected()
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            params = {"cursor": cursor} if cursor else None
            result = await self._request(method, params, timeout_seconds=self._default_timeout_seconds)
            page = result.get(result_key, [])
            for entry in page:
                if not validator(entry):
                    raise MCPProtocolError(f"{method} returned a malformed entry: {entry!r}")
            items.extend(page)
            next_cursor = result.get("nextCursor")
            if not next_cursor:
                return items
            if next_cursor in seen_cursors:
                raise MCPProtocolError(f"{method} returned a repeated cursor, aborting to avoid an infinite loop")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    async def list_tools(self) -> list[MCPToolInfo]:
        entries = await self._list_all("tools/list", "tools", is_tool)
        return [
            MCPToolInfo(name=e["name"], description=e.get("description") or "", input_schema=e["inputSchema"])
            for e in entries
        ]

    async def list_resources(self) -> list[dict[str, Any]]:
        return await self._list_all("resources/list", "resources", is_resource)

    async def list_resource_templates(self) -> list[dict[str, Any]]:
        return await self._list_all("resources/templates/list", "resourceTemplates", is_resource_template)

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, cancel_event: asyncio.Event | None = None
    ) -> CallToolResult:
        self._ensure_connected()
        result = await self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
            timeout_seconds=self._default_timeout_seconds,
            cancel_event=cancel_event,
        )
        from .protocol.content import _content_blocks_from_wire  # local import：避免循环引用

        return CallToolResult(
            content=_content_blocks_from_wire(result.get("content", [])),
            structured_content=result.get("structuredContent"),
            is_error=bool(result.get("isError", False)),
        )

    async def ping(self) -> None:
        self._ensure_connected()
        await self._request("ping", None, timeout_seconds=self._default_timeout_seconds)

    async def close(self) -> None:
        if self._transport is not None:
            await self._transport.close()
        await self._handle_close()

    async def __aenter__(self) -> "MCPClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()
