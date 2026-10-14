# Tasks: packages/mcpclient 对齐 pi 的独立 MCP 协议实现

**Input**: Design documents from `/specs/003-pi-mcp-client-alignment/`
**Prerequisites**: plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md（全部已就绪）

**Tests**: 本仓库宪法 Principle I（TDD 不可协商）要求所有业务代码配套测试、先写测试再实现——下面
每个 User Story 阶段都包含测试任务，且必须先于对应实现任务完成并确认失败（RED），再写实现让它们
通过（GREEN）。

**Organization**: 按 User Story 分组，每个 Story 原则上可独立测试；User Story 1 的"消费方迁移"部
分实际依赖 User Story 2 的 stdio 传输才能端到端生效，已在 Phase 5 的任务说明里显式标注这个跨阶段
依赖（不影响其余 Story 的独立性）。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 对应 spec.md 的 User Story 编号
- 每个任务都带精确文件路径

## Path Conventions

单仓库多 Python 包：`packages/mcpclient/`（本次改动核心）、`apps/api/`（按 FR-008 限定的 3 个调
用方文件之二）、`tests/mcpclient/`、`tests/apps/api/`。

---

## Phase 1: Setup

**Purpose**: 搭好新的子包骨架 + 依赖分组调整

- [X] T001 [P] 创建子包骨架：`packages/mcpclient/protocol/__init__.py`、
      `packages/mcpclient/transports/__init__.py`、`packages/mcpclient/oauth/__init__.py`（均为空
      文件，只建立 import 路径）
- [X] T002 调整 `pyproject.toml`：把 `"mcp>=2.3.0"` 从 `[project].dependencies` 移到
      `[dependency-groups].dev`（`demo_server.py` 仍需要它，但它是测试夹具依赖，不是生产运行时依
      赖——对应 SC-001）；把 `"httpx>=0.27"` 从 `[dependency-groups].dev` 提升到
      `[project].dependencies`（Streamable HTTP 传输现在是生产代码，不再只是测试依赖）

**Checkpoint**：依赖分组就绪，可以开始写子包代码。

---

## Phase 2: Foundational（阻塞性前置，必须先于任何 User Story 完成）

**⚠️ CRITICAL**: 本阶段完成前不能开始任何 User Story 的任务。

- [X] T003 [P] 实现 JSON-RPC 消息类型：`JsonRpcRequest`/`JsonRpcNotification`/`JsonRpcResponse`（`result`/`error` 二选一，不可同时非 `None`，构造/解析时拒绝两者都非空或都为空的畸形消息）、`JsonRpcErrorObject`、`JSON_RPC_ERROR_CODES`（`IntEnum`：PARSE_ERROR=-32700、INVALID_REQUEST=-32600、METHOD_NOT_FOUND=-32601、INVALID_PARAMS=-32602、INTERNAL_ERROR=-32603）、`parse_jsonrpc_message()` 及类型判定函数，写入 `packages/mcpclient/protocol/jsonrpc.py`
- [X] T004 [P] 实现内容相关类型定义（暂不含转换逻辑）：`ContentBlock` 联合类型（`TextContentBlock`/`ImageContentBlock`/`AudioContentBlock`/`ResourceLinkContentBlock`/`EmbeddedResourceContentBlock`）、`CallToolResult`（`content`/`structured_content`/`is_error`）、`LlmContent` 联合类型（`TextLlmContent`/`ImageLlmContent`），写入 `packages/mcpclient/protocol/content.py`
- [X] T005 [P] 实现 MCP 协议类型定义：`Implementation`/`Root`/`ClientCapabilities`/`ServerCapabilities`/`InitializeResult`/`ProgressNotification`/`Tool`/`Resource`/`ResourceTemplate`，协议版本常量 `LATEST_PROTOCOL_VERSION="2025-11-25"`/`SUPPORTED_PROTOCOL_VERSIONS=("2025-11-25","2025-06-18","2025-03-26","2024-11-05")`，以及结构校验函数 `is_tool(data)`/`is_resource(data)`/`is_resource_template(data)`（必需字段缺失即返回 `False`，供分页逻辑整页拒绝用），写入 `packages/mcpclient/protocol/types.py`
- [X] T006 [P] 在 `packages/mcpclient/client.py` 新增异常层级 `MCPTimeoutError`/`MCPAbortError`/`MCPProtocolError`/`MCPConfigValidationError`（全部继承既有的 `MCPConnectionError`，不破坏 FR-008 要求的现有 `except MCPConnectionError` 分支）+ `validate_server_config(data: dict) -> MCPServerConfig` 结构校验工厂函数（必需字段缺失/类型不对时抛 `MCPConfigValidationError`，错误信息指出具体字段，对应 FR-002）
- [X] T007 实现最小传输接口：`McpTransport`（`typing.Protocol`：`start()`/`send(message, *, cancel_event=None)`/`close()`/`on_message`/`on_error`/`on_close`/可选 `set_protocol_version(version)`）+ `TransportEventsMixin`（监听器登记、close 只触发一次的共享样板），写入 `packages/mcpclient/transports/base.py`
- [X] T008 [P] 实现 `InMemoryTransport` + `create_in_memory_transport_pair() -> tuple[McpTransport, McpTransport]`（`send()` 内部用 `copy.deepcopy` 把消息投递给对端的 `on_message`，不涉及真实子进程/网络 I/O），写入 `packages/mcpclient/transports/in_memory.py`（依赖 T007）

**Checkpoint**：协议类型/异常层级/传输接口/内存测试传输就绪，User Story 1 可以开始。

---

## Phase 3: User Story 1 - 不依赖官方 SDK 的独立 JSON-RPC 协议核心 (Priority: P1) 🎯 MVP

**Goal**：`MCPClient` 作为 transport-neutral 的持久会话对象，自己完成握手、分页、超时续期、双向
取消、服务端主动请求自动应答。

**Independent Test**：用 `InMemoryTransport`（Phase 2 已就绪）驱动一次完整握手+分页 list_tools+
call_tool+客户端发起的取消+服务端发起的 ping，不需要真实子进程/网络。

### Tests for User Story 1 ⚠️ 先写，确认失败，再实现

- [X] T009 [P] [US1] 失败测试：未 `connect()` 前调用 `list_tools()`/`call_tool()`/`ping()` 必须抛出明确错误；`connect()` 必须严格按"发 `initialize`（带 `protocol_version`/`capabilities`/`client_info`）→ 收到合法响应 → 发 `notifications/initialized`"的顺序执行，写入 `tests/mcpclient/test_protocol_core.py`
- [X] T010 [P] [US1] 失败测试：`list_tools()` 自动翻页合并多页结果；收到和上一页相同的 `next_cursor` 时抛 `MCPProtocolError` 而不是死循环；某一页里混入不满足 `is_tool` 最小形状的条目时整页报错，写入 `tests/mcpclient/test_protocol_core.py`
- [X] T011 [P] [US1] 失败测试：一次等待响应中的 `call_tool()`，调用方触发 `cancel_event` 后立刻以 `MCPAbortError` 结束，且服务端侧的假 handler 能观察到对应的 `notifications/cancelled`；`initialize` 请求本身不支持取消，写入 `tests/mcpclient/test_protocol_core.py`
- [X] T012 [P] [US1] 失败测试：服务端发来 `ping` 请求被自动回复空结果，不触发任何调用方代码；构造时提供 `roots` 参数时服务端发来 `roots/list` 请求也被自动应答，未提供 `roots` 时回复 `METHOD_NOT_FOUND`，写入 `tests/mcpclient/test_protocol_core.py`
- [X] T013 [P] [US1] 失败测试：请求超过超时时间以 `MCPTimeoutError` 结束；期间收到针对该请求 `progress_token` 的 `notifications/progress` 后，超时计时器必须重新计时（不能沿用最初截止时间），写入 `tests/mcpclient/test_protocol_core.py`
- [X] T014 [P] [US1] 失败测试：底层传输触发 `on_close`（显式 `close()` 或意外断开）后，全部仍在等待响应的请求立刻以 `MCPConnectionError`（连接已关闭）结束，不能挂起，写入 `tests/mcpclient/test_protocol_core.py`

### Implementation for User Story 1

- [X] T015 [US1] 实现 `MCPClient.__init__()`/`connect()` 握手：构造传输（按 `server_config.transport` 分支，暂时只需支持已就绪的 `InMemoryTransport` 做内部驱动测试，stdio/http 分支留到各自 Story 实现后再接上）→ `start()` → 发 `initialize` 请求 → 校验响应 `protocol_version` 在 `SUPPORTED_PROTOCOL_VERSIONS` 内 → 发 `notifications/initialized` → `_connected=True`；未连接前调用其余方法必须拒绝，写入 `packages/mcpclient/client.py`（依赖 T003、T005、T006、T007）
- [X] T016 [US1] 实现请求关联：`_next_request_id` 计数器、`_pending: dict[int, PendingRequest]`、`PendingRequest`（`future`/`timeout_seconds`/`timer_task`/`cancel_event`）、挂到传输 `on_message` 上的响应/通知分发循环（响应 id 不在 `_pending` 里时安全忽略，不抛未处理异常），写入 `packages/mcpclient/client.py`（依赖 T015）
- [X] T017 [US1] 实现 `list_tools()`/`list_resources()`/`list_resource_templates()`：共享的 `_list_all(method, params, result_key, item_validator)` 分页辅助函数，处理重复 cursor 检测 + 逐条 `is_tool`/`is_resource`/`is_resource_template` 校验，写入 `packages/mcpclient/client.py`（依赖 T016）
- [X] T018 [US1] 实现 `call_tool(name, arguments, *, cancel_event=None)`：`cancel_event` 触发时发 `notifications/cancelled`（带原请求 id）并让本地调用以 `MCPAbortError` 结束，写入 `packages/mcpclient/client.py`（依赖 T016）
- [X] T019 [US1] 实现每请求独立超时 + `notifications/progress` 触发的续期逻辑，写入 `packages/mcpclient/client.py`（依赖 T016）
- [X] T020 [US1] 实现内置的服务端主动请求自动应答（`ping`/`roots/list`），写入 `packages/mcpclient/client.py`（依赖 T016）
- [X] T021 [US1] 实现 `close()`（让 `_pending` 里全部未完成请求以 `MCPConnectionError` 结束）+ `__aenter__`/`__aexit__`，写入 `packages/mcpclient/client.py`（依赖 T016）
- [X] T022 [US1] 运行 `.venv/bin/pytest tests/mcpclient/test_protocol_core.py -v`，确认全部通过（GREEN checkpoint）

**Checkpoint**：User Story 1（协议核心）在内存传输下完整可用、独立可测——这是 MVP。

---

## Phase 4: User Story 2 - stdio 传输的健壮子进程生命周期管理 (Priority: P2)

**Goal**：stdio 传输按"先礼后兵"顺序关闭子进程，不残留孤儿进程。

**Independent Test**：对一个忽略普通终止信号、只认 SIGKILL 的测试脚本调用 `close()`，断言最终
退出；对一个会拉起孙进程的包装脚本，断言两层进程都被清理。

### Tests for User Story 2 ⚠️ 先写，确认失败，再实现

- [X] T023 [P] [US2] 准备一个忽略 SIGTERM、只在 SIGKILL 时退出的测试脚本（放在 `tests/mcpclient/fixtures/` 下）+ 失败测试：对它建立 stdio 连接后调用 `close()`，断言最终确实让它退出（可用耗时量级粗略核实走完了"stdin 关闭宽限期→SIGTERM 等待期→SIGKILL"三个阶段），写入 `tests/mcpclient/test_transports_stdio.py`
- [X] T024 [P] [US2] 准备一个会再拉起一个子进程的包装测试脚本（放在 `tests/mcpclient/fixtures/` 下）+ 失败测试：关闭连接后用 `ps`/`pgrep` 核实外层包装进程和它拉起的子进程都不在了，写入 `tests/mcpclient/test_transports_stdio.py`
- [X] T025 [P] [US2] 失败测试：直接调用模块级的进程退出清理钩子函数（模拟"宿主进程异常退出"），断言仍存活的已注册进程组会被 SIGTERM，写入 `tests/mcpclient/test_transports_stdio.py`

### Implementation for User Story 2

- [X] T026 [US2] 实现 `StdioTransport.start()`：`asyncio.create_subprocess_exec(..., start_new_session=True)`（POSIX 新建进程组）、逐行读取 stdout 解析换行分隔的 JSON-RPC 消息（单行超过 `DEFAULT_MAX_MESSAGE_BYTES=16MB` 报错而不是无限增长内存）、stderr 读入容量上限 64KB 的环形缓冲区，写入 `packages/mcpclient/transports/stdio.py`（依赖 T007）
- [X] T027 [US2] 实现 `StdioTransport.close()` 级联：关闭 stdin → 等待 `STDIN_CLOSE_GRACE_MS`（默认 500ms，受 `close_timeout_ms` 封顶）→ 仍未退出发 SIGTERM（POSIX：`os.killpg(os.getpgid(pid), signal.SIGTERM)`；Windows：`taskkill /T /F` 等效机制）→ 等待 `close_timeout_ms`（默认 2000ms）→ 仍未退出发 SIGKILL，写入 `packages/mcpclient/transports/stdio.py`（依赖 T026）
- [X] T028 [US2] 实现模块级"存活进程组 id"注册表 + `atexit.register` 清理钩子（宿主进程退出时对仍存活的进程组发 SIGTERM），写入 `packages/mcpclient/transports/stdio.py`（依赖 T026）
- [X] T029 [US2] 运行 `.venv/bin/pytest tests/mcpclient/test_transports_stdio.py -v`，确认全部通过（GREEN checkpoint）

**Checkpoint**：User Story 1 + 2 都独立可用——stdio 传输现在是生产可用的真实传输。

---

## Phase 5: User Story 1（续）— 消费方迁移到持久会话模型 (FR-008/FR-009)

> 本阶段是 User Story 1 "Clarifications 确认的持久会话模型替换" 在真实调用方（`apps/api/main.py`/
> `apps/api/runtime.py`/`packages/mcpclient/tools.py`）上落地的部分。**显式依赖 Phase 4**（stdio
> 传输）：现有全部真实配置的 MCP 服务器都是 stdio，必须有可用的真实传输才能端到端迁移/验证，不能
> 只在内存传输层面完成这一步。

- [X] T030 [US1] 删除 `packages/mcpclient/client.py` 里的 `connect_and_list_tools()`/`connect_and_call_tool()` 两个一次性连接函数（FR-009 确认的刻意替换，不保留兼容包装）（依赖 T021、T026-T028）
- [X] T031 [US1] 改造 `packages/mcpclient/tools.py` 的 `MCPTool`：新增 `self._client: MCPClient | None = None`，`acall()` 首次调用时 `await self._client.connect()`（懒连接），之后复用同一个连接；新增 `async def aclose(self) -> None`（`self._client` 非空时调用其 `close()`）；捕获异常的分支继续认 `MCPConnectionError`（含新子类）不变（依赖 T030）
- [X] T032 [US1] 改造 `apps/api/main.py`：`POST /api/mcp/servers`（创建）和 `POST /api/mcp/servers/{server_id}/refresh` 两条路由，把 `connect_and_list_tools(server_config)` 替换成 `async with MCPClient(server_config) as client: tools = await client.list_tools()`（依赖 T030）
- [X] T033 [US1] 改造 `apps/api/runtime.py`：`AgentRuntime` 新增 `self._task_mcp_tools: dict[str, list[MCPTool]] = {}`；`_get_agent()` 在 `_build_registry(task["id"])` 调用之后，把 `_ensure_mcp_tools()` 构造出的 `MCPTool` 列表存入 `self._task_mcp_tools[task["id"]]`；`evict(task_id)` 改成 `async def evict`，新增 `for tool in self._task_mcp_tools.pop(task_id, []): await tool.aclose()`；核实并更新全部调用 `evict()` 的现有调用点加上 `await`（依赖 T031）
- [X] T034 [US1] 改写 `tests/mcpclient/test_mcpclient_client.py`：原有依赖 `connect_and_list_tools`/`connect_and_call_tool` 的断言改成 `MCPClient(...).connect()`/`list_tools()`/`call_tool()`/`close()` 的等价场景（含原有的 bad-command 连接失败、stdio env 透传、HTTP 真机三类场景），覆盖面不低于现状（依赖 T030-T033）
- [X] T035 [US1] 改写 `tests/mcpclient/test_mcpclient_tools.py`：`MCPTool.acall()` 相关断言跟着新内部实现调整（公开行为——`ToolOutcome` 状态/文本内容——保持不变）；新增一条"同一个 `MCPTool` 连续 `acall()` 两次，底层只建立一次连接"的断言（对应 SC-006，可以通过给 `MCPClient.connect` 打点计数验证）（依赖 T031）
- [X] T036 [US1] 核实并更新 `tests/apps/api/test_api_routes.py` 等现有测试：如果直接 mock 了 `connect_and_list_tools`，改成 mock `MCPClient` 的等价入口；补一条 `evict()` 变成 `async def` 后现有调用点仍然正确工作的回归测试（依赖 T032-T033）
- [X] T037 [US1] 运行 `.venv/bin/pytest tests/mcpclient/ tests/apps/api/ -v`，确认全部通过（GREEN checkpoint，SC-002/SC-006 成立）

**Checkpoint**：真实调用方已完整迁移到持久会话模型，现状的"添加/刷新服务器"和"模型调用 MCP 工
具"两条用户可见路径继续可用。

---

## Phase 6: User Story 3 - Streamable HTTP 传输 (Priority: P3)

**Goal**：能连接远程 MCP 服务器，HTTP 发请求、SSE 收响应，断线自动重连续传。

**Independent Test**：用一个测试里手写的最小 ASGI/HTTP handler 驱动一次完整往返，验证请求体格
式、SSE 解析、断线重连续传。

### Tests for User Story 3 ⚠️ 先写，确认失败，再实现

- [X] T038 [P] [US3] 失败测试：一个测试用最小 ASGI/HTTP handler 驱动一次完整的 `initialize`→`list_tools`→`call_tool` 往返，验证请求以 HTTP POST 发出、响应按 SSE 逐事件解析（不要求一次性完整 JSON），写入 `tests/mcpclient/test_transports_http.py`
- [X] T039 [P] [US3] 失败测试：响应流在对应响应到达前中断，客户端自动重连并用 `Last-Event-ID` 续传断线前未读完的内容，最终结果完整不重复，写入 `tests/mcpclient/test_transports_http.py`
- [X] T040 [P] [US3] 失败测试：配置了自定义请求头的服务器，实际发出的每一次 HTTP 请求都带着这些头，写入 `tests/mcpclient/test_transports_http.py`
- [X] T041 [P] [US3] 失败测试：GET 流请求收到 405 响应时视为"服务端不提供 GET 流"，正常关闭不报错，写入 `tests/mcpclient/test_transports_http.py`

### Implementation for User Story 3

- [X] T042 [US3] 实现手写 SSE 帧解析器 `consume_sse_stream()`（追踪 `data:`/`event:`/`id:`/`retry:` 字段，单事件按上限截断报错），写入 `packages/mcpclient/transports/streamable_http.py`
- [X] T043 [US3] 实现 `StreamableHttpTransport.send()`：`httpx.AsyncClient` 发 POST（`Accept: application/json, text/event-stream`），按响应 `Content-Type` 分支处理一次性 JSON 或 SSE 流，写入 `packages/mcpclient/transports/streamable_http.py`（依赖 T042、T007）
- [X] T044 [US3] 实现指数退避自动重连 + `Last-Event-ID` 续传（初始延迟/最大延迟/最大重试次数对齐 pi 默认值，服务端 `retry:` 字段覆盖退避时机），写入 `packages/mcpclient/transports/streamable_http.py`（依赖 T043）
- [X] T045 [US3] 实现 `initialize`/`notifications/initialized` 完成后开启的独立自重连 GET 流（用于服务端主动推送，405 视为正常），写入 `packages/mcpclient/transports/streamable_http.py`（依赖 T043）
- [X] T046 [US3] 实现 `Mcp-Session-Id` 响应头跟踪（后续请求带上）、协商后的 `MCP-Protocol-Version` 请求头、自定义请求头透传，写入 `packages/mcpclient/transports/streamable_http.py`（依赖 T043）
- [X] T047 [US3] 实现 `AuthProvider`（`typing.Protocol`：`token()`/`on_unauthorized()`）写入 `packages/mcpclient/auth_provider.py`；在 `streamable_http.py` 的请求包装器里接入"收到 401 或 403+insufficient_scope 时调一次 `on_unauthorized` 再重试一次"的逻辑（依赖 T043）
- [X] T048 [US3] 运行 `.venv/bin/pytest tests/mcpclient/test_transports_http.py -v`，确认全部通过（GREEN checkpoint）

**Checkpoint**：三种传输（内存/stdio/HTTP）全部独立可用。

---

## Phase 7: User Story 4 - 工具结果到模型内容的转换 (Priority: P4)

**Goal**：`to_llm_content()` 比现状"只处理纯文本 block"更完整地处理图片/嵌入资源/结构化内容。

**Independent Test**：对纯文本/图片/嵌入资源/仅 `structuredContent` 四种 `CallToolResult` 形状分
别验证转换结果。

### Tests for User Story 4 ⚠️ 先写，确认失败，再实现

- [ ] T049 [P] [US4] 失败测试：`to_llm_content()` 对只含文本 block 的 `CallToolResult`，结果和现状 `"\n".join(block.text for block in result.content)` 行为等价（不回归），写入 `tests/mcpclient/test_content_conversion.py`
- [ ] T050 [P] [US4] 失败测试：`to_llm_content()` 对含图片 block / 嵌入文本资源 block / 嵌入图片资源 block 的结果，正确解包成对应的 `LlmContent` 成员，写入 `tests/mcpclient/test_content_conversion.py`
- [ ] T051 [P] [US4] 失败测试：`to_llm_content()` 对没有 `content`、只有 `structured_content` 的结果，返回它的 JSON 文本而不是空字符串，写入 `tests/mcpclient/test_content_conversion.py`
- [ ] T052 [P] [US4] 失败测试：`MCPTool.acall()` 对含图片内容的结果压平出的 `ToolOutcome.output` 字符串里包含可读的 `mime_type` 占位符，不包含 Python 对象 repr 的典型特征（`<`/`0x` 地址），写入 `tests/mcpclient/test_mcpclient_tools.py`

### Implementation for User Story 4

- [ ] T053 [US4] 实现 `to_llm_content(result: CallToolResult) -> list[LlmContent]`（转换规则见 `contracts/content-conversion.md`），写入 `packages/mcpclient/protocol/content.py`（依赖 T004）
- [ ] T054 [US4] 改造 `MCPTool.acall()`：调用 `to_llm_content()` 后把结果压平成 `ToolOutcome.output` 字符串（文本成员 `"\n"` 连接；图片成员转成 `f"[图片内容：{mime_type}，约 {len(data)} 字符的 base64 数据]"` 占位符），写入 `packages/mcpclient/tools.py`（依赖 T053、T031）
- [ ] T055 [US4] 运行 `.venv/bin/pytest tests/mcpclient/test_content_conversion.py tests/mcpclient/test_mcpclient_tools.py -v`，确认全部通过（GREEN checkpoint）

**Checkpoint**：图片等多模态内容不再被错误地转成 Python 对象字符串（SC-005）。

---

## Phase 8: User Story 5 - OAuth 客户端子集 (Priority: P5)

**Goal**：发现授权元数据、PKCE 授权码流程、动态客户端注册、token 刷新（并发去重）、step-up 授
权。**安全敏感**——实现/评审时按宪法要求先过一轮专门的安全检查（见 Phase 9 T074）。

**Independent Test**：用假的授权服务器端点跑通完整 PKCE 换 token 流程；验证并发 401 去重。

### Tests for User Story 5 ⚠️ 先写，确认失败，再实现

- [ ] T056 [P] [US5] 失败测试：第一次连接一个要求 OAuth 的服务器且本地无凭据时，抛出 `MCPOAuthAuthorizationRequiredError`（携带授权 URL），而不是普通连接失败，写入 `tests/mcpclient/test_oauth.py`
- [ ] T057 [P] [US5] 失败测试：对假的发现元数据/token 端点跑通完整 PKCE 授权码换 token 流程，写入 `tests/mcpclient/test_oauth.py`
- [ ] T058 [P] [US5] 失败测试：5 个并发请求同时收到 401，底层只发出一次真正的刷新请求，其余请求共享同一次结果（用计数器 mock token 端点验证），写入 `tests/mcpclient/test_oauth.py`
- [ ] T059 [P] [US5] 失败测试：服务端返回 `insufficient_scope` 时触发一次 step-up 授权流程，而不是把错误原样抛给调用方，写入 `tests/mcpclient/test_oauth.py`
- [ ] T060 [P] [US5] 失败测试：`issuer` 不匹配的发现响应抛 `OAuthIssuerMismatchError`；`authorization_endpoint` 等 URL 字段是 `javascript:`/`data:`/`vbscript:` scheme 时被拒绝，写入 `tests/mcpclient/test_oauth.py`

### Implementation for User Story 5

- [ ] T061 [US5] 实现 `oauth/types.py`：`OAuthTokens`/`OAuthClientInformation`/`OAuthProtectedResourceMetadata`/`AuthorizationServerMetadata` 等 dataclass + `parse_oauth_tokens`/`parse_client_information`/`parse_protected_resource_metadata`/`parse_authorization_server_metadata` 结构校验函数（含 URL scheme 安全检查），写入 `packages/mcpclient/oauth/types.py`
- [ ] T062 [US5] 实现 `oauth/errors.py`：`OAuthError`/`OAuthIssuerMismatchError`/`OAuthInsecureEndpointError`/`OAuthRegistrationError`/`MCPOAuthAuthorizationRequiredError`，写入 `packages/mcpclient/oauth/errors.py`
- [ ] T063 [US5] 实现 `oauth/discovery.py`：`parse_www_authenticate`、`discover_protected_resource_metadata`（路径特定→根路径两级尝试）、`discover_authorization_server_metadata`（含 `issuer` 校验，默认不跳过）、`discover_oauth_server_info`，写入 `packages/mcpclient/oauth/discovery.py`（依赖 T061、T062）
- [ ] T064 [US5] 实现 `oauth/flow.py`：PKCE（`hashlib.sha256`+`secrets.token_urlsafe`）、`start_authorization()`（构造授权 URL）、`token_request()`/`exchange_authorization_code()`/`refresh_authorization()`（表单编码 POST）、客户端鉴权方式选择、`register_client()`（动态客户端注册）、`step_up_scope()`（已授予∪服务端要求的 scope 并集），写入 `packages/mcpclient/oauth/flow.py`（依赖 T061-T063）
- [ ] T065 [US5] 实现并发 401 去重的刷新适配器（把一个 `OAuthClientProvider`-等价对象包装成 `AuthProvider`，`on_unauthorized()` 用一个作用域内的"进行中刷新" `asyncio.Future` 共享结果），写入 `packages/mcpclient/oauth/flow.py`（依赖 T064）
- [ ] T066 [US5] 实现 `oauth/provider.py`：`MCPOAuthProvider`（绑定单个 `server_url`）、`OAuthStateStore`（`typing.Protocol`：`load()`/`save()`）、`MemoryOAuthStateStore`（供测试/默认行为），写入 `packages/mcpclient/oauth/provider.py`（依赖 T064）
- [ ] T067 [US5] 实现 `oauth/callback.py`：`PendingCallbackRegistry.register(state) -> asyncio.Future[dict]` / `resolve(state, params) -> bool`，写入 `packages/mcpclient/oauth/callback.py`
- [ ] T068 [US5] 在 `apps/api/main.py` 新增一个 OAuth 回调 HTTP 路由（例如 `GET /api/mcp/oauth/callback`），内部调用 `PendingCallbackRegistry.resolve(state, dict(request.query_params))`，复用现有 `_pending_approvals` 的 pending-Future 模式（依赖 T067）
- [ ] T069 [US5] 运行 `.venv/bin/pytest tests/mcpclient/test_oauth.py -v`，确认全部通过（GREEN checkpoint）

**Checkpoint**：全部 5 个 User Story 独立可用。

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T070 [P] 执行 `quickstart.md` 场景 7（依赖边界核查）：`grep` 确认 `mcp>=2.3.0` 只出现在 `[dependency-groups].dev` 下，`packages/mcpclient` 的 `client.py`/`tools.py`/`protocol/`/`transports/`/`oauth/` 零处 `import mcp`（`demo_server.py` 除外）
- [ ] T071 运行 `.venv/bin/pytest`（全量），确认 0 回归、测试数只增不减
- [ ] T072 运行 `.venv/bin/python scripts/check_core_boundary.py`，确认依然零违规（本次改动不涉及 `packages/core`，确认没有意外波及）
- [ ] T073 [P] 更新项目 memory（`project_opentalos_python_rebuild.md` 追加本次 shipped 记录 + `MEMORY.md` 索引行同步）
- [ ] T074 对 `packages/mcpclient/oauth/` 全部文件做一次专门的安全检查（凭据存储方式、PKCE 校验正确性、回调 `state` 参数处理、URL scheme 校验覆盖面），对应宪法"安全敏感代码需要额外谨慎"的要求

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup（Phase 1）**：无依赖，立即开始
- **Foundational（Phase 2）**：依赖 Setup 完成——阻塞全部 User Story
- **User Story 1（Phase 3）**：依赖 Foundational 完成；**MVP**，内存传输下即可独立交付
- **User Story 2（Phase 4）**：依赖 Foundational 完成；和 User Story 1 的协议核心逻辑无交叉依
  赖，可以在 Phase 3 完成后并行安排
- **User Story 1 消费方迁移（Phase 5）**：依赖 Phase 3（协议核心）**和** Phase 4（stdio 传输）
  都完成——这是本次任务图里唯一一处"后一个 User Story 的交付是前一个 Story 收尾的前置条件"的
  例外，已在 Phase 5 标题处说明原因
- **User Story 3（Phase 6）**：依赖 Foundational 完成；独立于 Phase 4/5，可以和它们并行安排
- **User Story 4（Phase 7）**：协议类型部分（T004）在 Foundational 阶段已就绪；`to_llm_content`
  本身的实现独立于其余 Story，可以在 Foundational 完成后随时安排；但 T054（`MCPTool.acall()` 改
  造）依赖 Phase 5 的 T031（`MCPTool` 已经持有 `self._client`）
- **User Story 5（Phase 8）**：依赖 Foundational 完成；依赖 Phase 6 的 `AuthProvider`
  （`packages/mcpclient/auth_provider.py`，T047）存在，但不依赖 OAuth 的具体传输细节
- **Polish（Phase 9）**：依赖全部 User Story 完成

### Within Each User Story

- 测试任务必须先写、先确认失败（RED），再写实现任务（GREEN）
- 同一 Story 内，类型/接口定义先于使用它们的方法实现

### Parallel Opportunities

- Phase 2 的 T003/T004/T005/T006 四个类型定义任务可以并行（各自独立文件）
- Phase 3 的 T009-T014 六个测试任务可以并行编写（同一个测试文件内的不同测试函数，互不依赖）
- Phase 4 的 T023-T025 三个测试任务可以并行编写
- Phase 6 的 T038-T041、Phase 7 的 T049-T052、Phase 8 的 T056-T060 同理，组内测试任务可并行
- Phase 4（User Story 2）和 Phase 6（User Story 3）两条传输实现线，在 Phase 3 完成后可以由不同
  开发者并行推进（互不依赖对方的具体传输实现）

---

## Parallel Example: Phase 2（Foundational）

```bash
# 四个类型定义任务可以并行：
Task: "实现 JSON-RPC 消息类型 in packages/mcpclient/protocol/jsonrpc.py"
Task: "实现内容相关类型定义 in packages/mcpclient/protocol/content.py"
Task: "实现 MCP 协议类型定义 in packages/mcpclient/protocol/types.py"
Task: "实现异常层级 + MCPServerConfig 校验 in packages/mcpclient/client.py"
```

## Parallel Example: User Story 1 的测试

```bash
# 六个测试任务可以并行编写（同一文件的不同测试类/函数）：
Task: "connect() 握手顺序 + 连接前拒绝操作的失败测试"
Task: "list_tools() 分页 + 重复 cursor 的失败测试"
Task: "call_tool() 取消的失败测试"
Task: "服务端主动请求自动应答的失败测试"
Task: "超时 + progress 续期的失败测试"
Task: "传输掉线的失败测试"
```

---

## Implementation Strategy

### MVP First（仅 User Story 1）

1. 完成 Phase 1：Setup
2. 完成 Phase 2：Foundational（阻塞项，必须完成）
3. 完成 Phase 3：User Story 1
4. **STOP and VALIDATE**：独立验证 User Story 1（`quickstart.md` 场景 1）
5. 此时协议核心已经是可审查、可独立合并的增量（虽然还不能在真实 stdio/HTTP 场景下使用）

### Incremental Delivery

1. Setup + Foundational → 基础就绪
2. User Story 1（协议核心，内存传输验证）→ 独立测试通过
3. User Story 2（stdio 传输）→ 独立测试通过
4. User Story 1 消费方迁移（Phase 5，依赖 Story 1+2）→ 真实"添加/刷新服务器"和"模型调用 MCP 工
   具"两条路径切到持久会话模型，SC-002/SC-006 成立——**到这一步为止就是一个完整、可独立上线的增
   量**（stdio 是现状唯一实际使用的传输）
5. User Story 3（HTTP 传输）→ 独立测试通过，远程服务器场景解锁
6. User Story 4（内容转换）→ 独立测试通过，图片等多模态内容不再被错误转换
7. User Story 5（OAuth 子集）→ 独立测试通过，远程 OAuth 服务器场景解锁
8. Polish → 全量回归 + 依赖边界核查 + OAuth 专项安全检查 + memory 更新

### Parallel Team Strategy

1. 团队一起完成 Setup + Foundational
2. Foundational 完成后：
   - 开发者 A：User Story 1（协议核心）
   - 开发者 B：User Story 2（stdio 传输，不依赖协议核心的具体实现细节，只依赖 Phase 2 的
     `McpTransport` 接口定义）
   - 开发者 C：User Story 3（HTTP 传输，同样只依赖传输接口定义）
3. User Story 1 和 2 都完成后，由其中一人推进 Phase 5（消费方迁移）
4. User Story 4、5 在 Foundational 完成后即可由任意开发者独立推进（User Story 4 的
   `MCPTool.acall()` 改造部分需要等 Phase 5 的 T031 完成）

---

## Notes

- `[P]` 任务 = 不同文件、无依赖
- `[Story]` 标签把任务对应回 spec.md 的 User Story 编号，便于追溯
- 每个 Story 原则上独立可完成可测试；Phase 5 是本次任务图里唯一的例外（已在该阶段标题处说明依
  赖原因），不代表其余 Story 之间存在隐藏耦合
- 实现前先验证测试确实失败（RED）
- 建议每个任务或逻辑分组完成后提交一次（参照 002 feature 的"每个 User Story 一次提交"节奏）
- 可以在任意 Checkpoint 处停下独立验证对应 Story
- 避免：模糊任务描述、同文件冲突的并行标记、破坏 Story 独立性的跨 Story 依赖（Phase 5 除外，原
  因已显式说明）
