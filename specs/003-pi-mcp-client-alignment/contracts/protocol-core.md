# Contract: JSON-RPC 协议核心（`MCPClient` + `protocol/jsonrpc.py` + `protocol/types.py`）

对应 User Story 1、FR-001/FR-002/FR-007、SC-001/SC-002。

## 公共入口

```python
class MCPClient:
    def __init__(self, server_config: MCPServerConfig, *, roots: list[Root] | None = None) -> None: ...
    async def connect(self) -> None: ...
    async def list_tools(self) -> list[MCPToolInfo]: ...
    async def list_resources(self) -> list[Resource]: ...
    async def list_resource_templates(self) -> list[ResourceTemplate]: ...
    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, cancel_event: asyncio.Event | None = None
    ) -> CallToolResult: ...
    async def ping(self) -> None: ...
    async def close(self) -> None: ...
    async def __aenter__(self) -> "MCPClient": ...
    async def __aexit__(self, *exc_info: object) -> None: ...
```

## 行为契约

1. **连接前拒绝操作**：`connect()` 完成（`initialize` 握手 + 发出 `notifications/initialized`）
   之前调用 `list_tools()`/`call_tool()`/`ping()` 必须抛出明确错误（`MCPConnectionError` 或子
   类），不能挂起、不能返回看似成功的空结果。
2. **握手顺序**：`connect()` 必须严格按"发送 `initialize` 请求（带
   `protocol_version=LATEST_PROTOCOL_VERSION`、`capabilities`、`client_info`）→ 等待响应 → 校验
   响应里的 `protocol_version` 在 `SUPPORTED_PROTOCOL_VERSIONS` 内 → 发送
   `notifications/initialized` 通知"这个顺序执行；响应里的版本不在支持列表内时 `connect()` 失
   败并给出清晰错误（FR-007）。
3. **分页**：`list_tools`/`list_resources`/`list_resource_templates` 自动翻页直到响应不带
   `next_cursor`；收到和上一页相同的 `next_cursor` 时抛 `MCPProtocolError`，不能死循环。每一页
   的每个条目都必须通过对应的 `is_tool`/`is_resource`/`is_resource_template` 结构校验，任何一条
   不满足就整页失败。
4. **取消**：`call_tool()` 传入的 `cancel_event` 在请求仍未返回时被 `set()`，必须让这次调用立刻
   以 `MCPAbortError` 结束，且向服务端发送一条 `notifications/cancelled`（带原请求 id）。
   `initialize` 请求本身不接受取消参数。
5. **服务端主动请求自动应答**：收到 `method="ping"` 的请求，必须在不触发任何调用方代码的前提下
   自动回复空结果；构造时提供了 `roots` 参数时，收到 `method="roots/list"` 必须自动回复
   `{"roots": [...]}`。
6. **超时与续期**：每个请求有独立的超时计时器；收到针对该请求 `progress_token` 的
   `notifications/progress` 通知后，计时器必须重新从头计时，不能沿用最初的截止时间。超时触发
   时以 `MCPTimeoutError` 结束该请求。
7. **传输掉线**：底层传输触发 `on_close`（无论是 `close()` 还是意外断开）时，所有仍在
   `_pending` 里等待响应的请求必须立刻以 `MCPConnectionError`（"连接已关闭"）结束，不能保持挂
   起状态。
8. **响应 id 不匹配**：收到一个 `_pending` 里不存在的请求 id 对应的响应，必须安全忽略或记录错
   误日志，不能抛出未处理异常搞垮整条连接。

## 独立测试方式

用 `InMemoryTransport`（见 `transports.md`）驱动：构造一对配对传输 → 客户端侧传给
`MCPClient`，服务端侧用测试写的最小 handler 回应 `initialize`/`tools/list`（分页 2 页）/
`tools/call`（故意延迟不回应，用于测取消）/ `ping`（服务端主动发起）—— 全程不依赖真实子进程/网
络。
