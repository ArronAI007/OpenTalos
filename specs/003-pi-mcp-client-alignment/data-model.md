# Phase 1 Data Model: packages/mcpclient 对齐 pi 的独立 MCP 协议实现

所有类型都定义在 `packages/mcpclient` 内部，按 Project Structure 的子包切分。字段名用 Python 惯
用的 `snake_case`，不照抄 pi 的 `camelCase`（Assumptions 已明确）。类名沿用这个仓库已有的
`MCP` 全大写前缀约定（`MCPServerConfig`/`MCPToolInfo`/`MCPConnectionError`），新增类型统一跟随
（`MCPClient`，不是 `McpClient`）。

## `packages/mcpclient/protocol/jsonrpc.py`

### JsonRpcRequest / JsonRpcNotification（dataclass）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `int` | 仅 `JsonRpcRequest` 有；`JsonRpcNotification` 没有 `id` 字段（协议语义：不期待响应） |
| `method` | `str` | 方法名，如 `"tools/list"`/`"notifications/cancelled"` |
| `params` | `dict[str, Any] \| None` | 可选参数 |

### JsonRpcResponse（dataclass）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `int` | 对应请求的 id |
| `result` | `Any \| None` | 成功时的结果；与 `error` 二选一，不可同时非 `None` |
| `error` | `JsonRpcErrorObject \| None` | 失败时的错误对象 |

**校验规则**：`result`/`error` 必须恰好一个非 `None`（构造时/解析时拒绝两者都非空或两者都为空
的畸形消息）——对应 Edge Cases"同一个请求 id 收到了两次响应"类问题的第一道防线。

### JsonRpcErrorObject（dataclass）

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | `int` | 见 `JSON_RPC_ERROR_CODES`（`IntEnum`：PARSE_ERROR=-32700、INVALID_REQUEST=-32600、METHOD_NOT_FOUND=-32601、INVALID_PARAMS=-32602、INTERNAL_ERROR=-32603） |
| `message` | `str` | 人类可读错误信息 |
| `data` | `Any \| None` | 可选附加数据 |

### 异常类型（继承链，见 research.md Decision 5）

```text
MCPConnectionError（已存在，不变）
├── MCPTimeoutError        # 请求超时（含进度通知续期后仍超时）
├── MCPAbortError           # 客户端主动取消
├── MCPProtocolError         # 协议级错误：重复 cursor、分页结果形状不合法、重复/未知响应 id
└── MCPConfigValidationError  # MCPServerConfig 结构校验失败（FR-002）
```

OAuth 相关异常（`oauth/errors.py`）独立成一棵小继承树，不挂在 `MCPConnectionError` 下（OAuth 失
败不是"连接失败"，是"授权失败"，语义不同）：

```text
OAuthError（新增基类）
├── OAuthIssuerMismatchError
├── OAuthInsecureEndpointError
├── OAuthRegistrationError
└── MCPOAuthAuthorizationRequiredError   # FR-011 Acceptance Scenario 1 要求的"特定异常"
```

### PendingRequest（内部状态，不对外导出）

| 字段 | 类型 | 说明 |
|------|------|------|
| `request_id` | `int` | |
| `future` | `asyncio.Future[Any]` | 最终结果/异常投递点 |
| `timeout_seconds` | `float` | 每次收到 progress 通知后用这个值重新计时 |
| `timer_task` | `asyncio.Task \| None` | 当前的超时计时任务，续期时取消重建 |
| `cancel_event` | `asyncio.Event \| None` | 调用方传入的取消信号（可选） |

## `packages/mcpclient/protocol/types.py`

直接对应 pi `protocol/types.ts`（已全文核实），字段、可选性与 TS 源一一对应：

- `Implementation`：`name: str`、`version: str`、`title: str | None`
- `Root`：`uri: str`、`name: str | None`
- `ClientCapabilities`：`experimental`/`roots`/`sampling`/`elicitation`，均为可选 `dict`
- `ServerCapabilities`：`experimental`/`logging`/`prompts`/`resources`/`tools`/`completions`，均
  为可选 `dict`
- `InitializeResult`：`protocol_version: str`、`capabilities: ServerCapabilities`、
  `server_info: Implementation`、`instructions: str | None`
- `ProgressNotification`：`progress_token: str | int`、`progress: float`、`total: float | None`、
  `message: str | None`
- `ToolAnnotations` / `ToolExecution`：按原字段一一对应
- **`Tool`**（`MCPToolInfo` 的"协议层原始形状"，二者字段部分重叠但不是同一个类型——
  `MCPToolInfo` 是这个仓库对外暴露的稳定公共类型，`Tool` 是协议层内部中间表示，解析完响应后转
  成 `MCPToolInfo`）：`name`/`title`/`description`/`input_schema`/`output_schema`/`annotations`/
  `execution`/`_meta`
- `Resource` / `ResourceTemplate`：按原字段一一对应（本次范围只需要类型定义本身以支撑
  `resources/list`/`resources/templates/list` 分页方法存在，不要求 `MCPClient` 之上有封装过的
  "resource 相关便捷方法"——spec.md 的 Key Entities/FR 都只提到"分页机制"本身需要支持这三类列
  表，没有要求额外的业务封装）

**校验规则**（对应 Edge Cases 第 2 条、FR-002）：`is_tool(data: dict) -> bool`（`name`/
`input_schema` 必需字段存在且类型正确）、`is_resource(data: dict) -> bool`（`uri`/`name` 必需）、
`is_resource_template(data: dict) -> bool`（`uri_template`/`name` 必需）——每页结果里只要有一条
不满足，整页拒绝并抛 `MCPProtocolError`，不做"挑出合法条目"的静默降级。

## `packages/mcpclient/protocol/content.py`

### ContentBlock（联合类型，tagged by `type` 字段）

| 成员 | 字段 |
|------|------|
| `TextContentBlock` | `type="text"`、`text: str` |
| `ImageContentBlock` | `type="image"`、`data: str`（base64）、`mime_type: str` |
| `AudioContentBlock` | `type="audio"`、`data: str`、`mime_type: str` |
| `ResourceLinkContentBlock` | `type="resource_link"`、`uri: str`、`name: str` |
| `EmbeddedResourceContentBlock` | `type="resource"`、`resource: TextResourceContents \| BlobResourceContents` |

### CallToolResult（dataclass）

| 字段 | 类型 | 说明 |
|------|------|------|
| `content` | `list[ContentBlock]` | 可能为空列表 |
| `structured_content` | `dict[str, Any] \| None` | |
| `is_error` | `bool` | |

### LlmContent（联合类型，`to_llm_content()` 的输出元素类型）

| 成员 | 字段 |
|------|------|
| `TextLlmContent` | `type="text"`、`text: str` |
| `ImageLlmContent` | `type="image"`、`data: str`、`mime_type: str` |

**转换规则**（`to_llm_content(result: CallToolResult) -> list[LlmContent]`，对应 FR-006，见
research.md Decision 8）：

1. `content` 非空：逐个 block 转换——`text`/`image` 直接变成同类型的 `LlmContent`；
   `resource`（嵌入资源）如果是文本资源解包成 `TextLlmContent`，是图片资源解包成
   `ImageLlmContent`，其余二进制资源变成 `TextLlmContent`（占位符文案，如
   `[嵌入资源：{mime_type}，{size} 字节]`）；`audio`/`resource_link` 都变成 `TextLlmContent` 占位
   符。
2. `content` 为空但 `structured_content` 非空：返回单个 `TextLlmContent`，内容是
   `json.dumps(structured_content, ensure_ascii=False)`。
3. 两者都为空：返回空列表（不是报错，不是占位符——这是现状行为，对应 Acceptance Scenario 2 的
   "不回归"要求的边界延伸）。

## `packages/mcpclient/transports/base.py`

### McpTransport（`typing.Protocol`）

| 方法 | 签名 | 说明 |
|------|------|------|
| `start` | `async def start(self) -> None` | 建立底层连接（spawn 子进程/发起 HTTP 连接） |
| `send` | `async def send(self, message: dict, *, cancel_event: asyncio.Event \| None = None) -> None` | 发送一条已序列化的 JSON-RPC 消息 |
| `close` | `async def close(self) -> None` | 优雅关闭 |
| `on_message` | `Callable[[dict], Awaitable[None]] \| None` | 协议核心注入的消息回调 |
| `on_error` | `Callable[[Exception], Awaitable[None]] \| None` | |
| `on_close` | `Callable[[], Awaitable[None]] \| None` | |
| `set_protocol_version` | `Callable[[str], None] \| None`（可选） | 协商完成后告知传输层（HTTP 传输用它设请求头） |

**校验规则**：三种传输实现（`StdioTransport`/`StreamableHttpTransport`/`InMemoryTransport`）必须
结构性满足这个 Protocol（`tests/mcpclient/test_protocol_core.py` 里有一个"最小假传输满足
Protocol 形状"的结构性测试，延续 `001`/`002` 已经用过的做法）。

## `packages/mcpclient/client.py`

### MCPClient（持久会话，取代 `connect_and_list_tools`/`connect_and_call_tool`）

| 状态字段 | 类型 | 说明 |
|---------|------|------|
| `_server_config` | `MCPServerConfig` | 构造时传入 |
| `_transport` | `McpTransport \| None` | `connect()` 后才非空 |
| `_pending` | `dict[int, PendingRequest]` | 请求关联表 |
| `_next_request_id` | `int` | 单调递增计数器 |
| `_server_capabilities` | `ServerCapabilities \| None` | `initialize` 响应后填充 |
| `_protocol_version` | `str \| None` | 协商后的版本（FR-007） |
| `_connected` | `bool` | `list_tools`/`call_tool` 在未连接时必须拒绝（Acceptance Scenario 1） |

| 方法 | 说明 |
|------|------|
| `async def connect(self) -> None` | 构造传输（按 `server_config.transport` 分支）→ `start()` → 发 `initialize` 请求 → 收到合法响应后发 `notifications/initialized` → `_connected = True` |
| `async def list_tools(self) -> list[MCPToolInfo]` | 走 `_list_all("tools/list", ...)`，转换成 `MCPToolInfo` |
| `async def call_tool(self, name: str, arguments: dict, *, cancel_event: asyncio.Event \| None = None) -> CallToolResult` | |
| `async def ping(self) -> None` | |
| `async def close(self) -> None` | 关闭传输，所有 `_pending` 里未完成的 Future 以 `MCPConnectionError`（"连接已关闭"）结束 |
| `async def __aenter__/__aexit__` | 包裹 `connect()`/`close()`，供一次性探测场景使用（Decision 1） |

**服务端主动请求自动应答**（内置 handler，不对外暴露为可覆盖的回调——spec.md 没有任何 Acceptance
Scenario 要求"调用方能自定义 ping/roots 的响应"，这是协议核心内置行为）：收到 `method="ping"`
的请求自动回空结果；收到 `method="roots/list"` 且构造时提供了 `roots` 参数时自动回
`{"roots": [...]}`，未提供时回一个标准 JSON-RPC 错误（`METHOD_NOT_FOUND`）。

## `packages/mcpclient/tools.py`

### MCPTool（`Tool` 子类，字段不变，内部实现改变）

| 字段 | 类型 | 说明 |
|------|------|------|
| `_server_config` | `MCPServerConfig` | 不变 |
| `_tool_info` | `MCPToolInfo` | 不变 |
| `_client` | `MCPClient \| None` | 新增，懒连接（首次 `acall()` 时才 `connect()`） |

`acall()` 的行为变化：第一次调用时构造 `MCPClient(self._server_config)` 并 `connect()`，之后的
调用复用同一个 `self._client`；`MCPConnectionError`（或其任意子类）仍然被捕获转成
`ToolOutcome.error(...)`，公开行为不变（outcome 状态/类型契约不变）。新增 `async def aclose(self)
-> None`：`self._client` 非空时调用其 `close()`。

## `packages/mcpclient/oauth/` 相关类型

### OAuthTokens（dataclass）

| 字段 | 类型 |
|------|------|
| `access_token` | `str` |
| `token_type` | `str` |
| `expires_in` | `int \| None` |
| `refresh_token` | `str \| None` |
| `scope` | `str \| None` |

### OAuthClientInformation（dataclass）

| 字段 | 类型 |
|------|------|
| `client_id` | `str` |
| `client_secret` | `str \| None` |
| `client_id_issued_at` | `int \| None` |
| `client_secret_expires_at` | `int \| None` |

### OAuthProtectedResourceMetadata / AuthorizationServerMetadata（dataclass）

按 pi `oauth/types.ts` 对应字段一一翻译（`resource`/`authorization_servers`/`scopes_supported`
等；`issuer`/`authorization_endpoint`/`token_endpoint`/`registration_endpoint` 等）。

**校验规则**（对应宪法原则 III + OAuth 安全评审要求）：`parse_oauth_tokens(data: dict) ->
OAuthTokens`、`parse_client_information(data: dict) -> OAuthClientInformation`、
`parse_protected_resource_metadata(data: dict) -> OAuthProtectedResourceMetadata`、
`parse_authorization_server_metadata(data: dict) -> AuthorizationServerMetadata` 四个工厂函数，
均：(a) 必需字段缺失时抛 `OAuthError` 并指出具体字段；(b) 任何 URL 类型字段的 scheme 必须是
`http`/`https`，拒绝 `javascript:`/`data:`/`vbscript:`（直接对齐 pi 的安全检查）。

### MCPOAuthProvider（具体状态持有者，对应单个 `server_url`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `server_url` | `str` | 这个 provider 实例绑定的唯一服务器 |
| `_store` | `OAuthStateStore`（`typing.Protocol`：`load()`/`save()`） | 调用方注入的持久化实现（FR-012——这个包本身只定义 Protocol 形状和一个内存实现 `MemoryOAuthStateStore` 供测试用，不替调用方选择真正落盘到哪） |

### PendingCallbackRegistry（`oauth/callback.py`，见 research.md Decision 6）

| 方法 | 说明 |
|------|------|
| `register(self, state: str) -> asyncio.Future[dict]` | |
| `resolve(self, state: str, params: dict) -> bool` | `state` 未登记时返回 `False` |

## 持久化存储边界（不变）

`apps/api/db.py` 的 `mcp_servers` 表 schema **不变**（`config`/`cached_tools` 两个 JSON 字段的内
容形状不变——`cached_tools` 继续是 `[{name, description, input_schema}]`，和 `MCPToolInfo` 转
`dict` 的现状序列化方式一致）。OAuth 凭据的持久化（如果用户真的配置了需要 OAuth 的服务器）不在
这次范围内新增表结构——FR-012 要求的是"可注入"，`MemoryOAuthStateStore` 是唯一自带的实现，真
正要接入 SQLite 持久化属于"有实际使用场景时再做"的后续工作，不在这次 5 个 User Story 的 FR/SC
范围内。
