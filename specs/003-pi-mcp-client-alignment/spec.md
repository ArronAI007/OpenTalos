# Feature Specification: packages/mcpclient 对齐 pi 的独立 MCP 协议实现

**Feature Branch**: `003-pi-mcp-client-alignment`

**Created**: 2026-10-14

**Status**: Draft

**Input**: User description: "仓库中的packages/mcpclient目录完全要按照 https://github.com/earendil-works/pi/tree/main/packages/mcp 的内核实现，只是pi的开发语言是TypeScript，我们是python"

## 参考实现核实记录（写 spec 前直接读的源码，不是转述）

已克隆 `earendil-works/pi` 仓库，直接读了 `packages/mcp` 的 README 全文、`src/client.ts`（621
行，全读）、`src/transports/transport.ts`（64 行，全读）、`src/transports/stdio.ts`/
`src/transports/streamable-http.ts`（各读了关键结构段）；同时逐行核实了本仓库现状
`packages/mcpclient/{client.py,tools.py}` 和 `apps/api/{main.py,db.py,runtime.py}` 里全部的调
用点。确认的关键事实：

- **pi 的 `@earendil-works/pi-mcp` 明确不依赖官方 MCP SDK**，是一套从零实现的、transport-neutral
  的 JSON-RPC 客户端核心：自己做请求关联（`nextRequestId`/`pending` Map）、自己做超时
  （每个请求独立计时，收到 `notifications/progress` 会重新计时）、自己做取消（客户端侧
  `AbortSignal` 触发后发 `notifications/cancelled` 通知服务端；服务端发来的
  `notifications/cancelled` 会 abort 本地正在处理的、服务端发起的请求）、自己处理服务端主动发
  起的请求（内置 `ping`/`roots/list` 两个 handler）、自己做分页（`tools/list`/
  `resources/list`/`resources/templates/list` 统一走 `listAll`，带重复 cursor 检测）。
- **`McpClient` 是一个持久对象**：`new McpClient(options)` 构造一次，`connect(transport)` 一次，
  之后反复调用 `listTools()`/`callTool()`/`ping()` 等方法，直到显式 `close()` 或底层传输掉线。
  这和本仓库 `packages/mcpclient/client.py` 现状**完全相反**——现状的
  `connect_and_list_tools()`/`connect_and_call_tool()` 是"每次调用都是一次全新的
  连接-操作-断开"，源码注释明确写着这是为了"换来不用处理进程崩溃/重连/应用重启后连接丢失等更
  复杂的生命周期问题"这个刻意的取舍（这次经确认要整体替换成持久会话模型，见下方 Clarifications）。
- **三种传输各自独立实现**：`StdioTransport`（`node:child_process.spawn` + `cross-spawn`
  跨平台兼容、Windows 用 `taskkill /T /F` 兜底、非 Windows 用负 pid 杀整个进程组、"先关
  stdin 给服务器优雅退出的机会、超时再发 SIGTERM、仍不退再 SIGKILL"的关闭顺序、进程退出钩子
  防止宿主进程异常退出时遗留孤儿进程）；`StreamableHttpTransport`（521 行，自己解析 SSE 帧、
  带指数退避的自动重连、用 `Last-Event-ID` 续传断线前未读完的响应流、可注入 `AuthProvider`）；
  `InMemoryTransport`（51 行，纯内存配对，供测试用，不涉及任何真实 I/O）。
- **OAuth 是可选的、独立的子路径导出**（`@earendil-works/pi-mcp/oauth`，不在默认导入路径
  里），约 1369 行，占整个包源码的 43%：PKCE 授权码流程、动态客户端注册、token 刷新（并发收到
  多个 401 时只刷新一次、共享结果）、`insufficient_scope` 时的 step-up 授权、本地回调 HTTP
  服务器、受保护资源/授权服务器的发现协议。**本仓库当前没有任何配置场景需要 OAuth**——
  `apps/api/main.py`/`apps/api/db.py` 里的 `mcp_servers` 表只有 `stdio`/`http` 两种
  `transport`，现有 7 个预置服务器卡片（memory 记录）全部是 npm/pypi 的本地 stdio 服务器，没
  有一个是需要 OAuth 的远程服务。
- **`toLlmContent(result)`**：把 `CallToolResult` 转成文本+图片内容给模型用，文本/图片直接透
  传，嵌入的文本/图片资源解包，音频/资源链接/二进制资源转成简短的文本占位符，没有
  `content` 但有 `structuredContent` 时用它的 JSON。这是现状 `packages/mcpclient/tools.py` 里
  `"\n".join(getattr(block, "text", str(block)) for block in result.content)` 这行的更完整版
  本（现状只处理纯文本 block，对图片/嵌入资源/结构化内容没有任何处理）。
- **本仓库当前的真实消费方**（逐一读过，不是猜测）：`apps/api/main.py` 的
  `POST /api/mcp-servers`（新增时调 `connect_and_list_tools` 探测一次工具列表并落库
  `cached_tools`）和"刷新"路由（同样调一次 `connect_and_list_tools`）；`apps/api/runtime.py`
  按 `mcp_servers` 表里 `enabled=1` 的记录，为每个启用的服务器构造一个 `MCPTool` 实例（用落
  库的 `cached_tools`，不是实时查询）注册进 agent 的 `ToolRegistry`；`MCPTool.acall()`
  （`packages/mcpclient/tools.py`）在真正被模型调用时才调 `connect_and_call_tool`——也就是说
  "探测工具列表"和"执行工具"是两条完全独立的连接路径，现状都是连接即用即弃。

## Clarifications

### Session 2026-10-14

- Q: pi 的 `McpClient` 是持久会话对象，本仓库现状是"每次操作都一次性连接-执行-断开"；这次对
  齐要不要把现状换成 pi 式的持久会话模型？ → A: 换成持久会话模型——`connect_and_list_tools()`/
  `connect_and_call_tool()` 这两个"一次性连接"函数被替换，`apps/api/runtime.py`/`MCPTool` 需
  要相应改造成持有/复用一个长期存活的客户端连接，而不是每次操作临时建连接断开。
- Q: Streamable HTTP 传输要不要包含完整的"断线自动重连 + Last-Event-ID 续传"可靠性机制，还是
  先做不支持续传的基础版本？ → A: 完整实现（指数退避自动重连 + 用 Last-Event-ID 续传断线前未
  读完的响应流），与 pi 的参考实现对齐，不分阶段。
- Q: OAuth 客户端子集（PKCE、动态客户端注册、token 刷新、step-up 授权、本地回调服务器）要不
  要纳入本次范围？ → A: 包含——完整对齐 pi 的参考实现，即便当前没有配置场景实际使用它。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 不依赖官方 SDK 的独立 JSON-RPC 协议核心 (Priority: P1)

维护者需要 `packages/mcpclient` 不再是官方 `mcp` PyPI 包的薄封装，而是一套自己实现的、
transport-neutral 的 MCP 客户端协议核心——自己做请求关联、超时（含进度通知续期）、双向取消、
服务端主动请求（`ping`/`roots/list`）、分页列表——这样整个仓库对 MCP 协议本身的行为（协议版本
协商、错误码、取消语义）不再受制于第三方 SDK 的实现细节或版本更新节奏。

**本次经确认，`McpClient` 换成 pi 式的持久会话对象**（构造一次、`connect()` 一次，之后反复调
用 `list_tools()`/`call_tool()` 直到显式 `close()` 或连接掉线）——这是一次经确认的、对现有调
用方行为的替换：`connect_and_list_tools()`/`connect_and_call_tool()` 这两个"一次性连接"函数
被替换，`apps/api/runtime.py`（构造/持有 `MCPTool` 实例的地方）和 `MCPTool.acall()` 需要相应
改造成持有/复用一个长期存活的客户端连接，而不是每次操作临时建连接断开（具体连接生命周期跟谁
绑定——单个服务器配置、还是单次对话——留给 `/speckit-plan` 设计）。

**Why this priority**: 这是"完全按照 pi 的内核实现"这句话里最核心的那部分——pi 的 `README` 开
篇第一句就是"不依赖官方 MCP SDK"，这是这个参考实现存在的理由本身，其余 User Story（传输层、
OAuth）都是这个协议核心之上的具体传输/能力。

**Independent Test**: 用一个内存传输（User Story 4）直接驱动协议核心完成一次握手
（`initialize`→`notifications/initialized`）+ 一次 `list_tools`（分页）+ 一次
`call_tool`+一次客户端发起的取消（请求还没返回前 abort，断言服务端收到
`notifications/cancelled`）+ 一次服务端发起的 `ping` 请求（断言客户端自动应答），不需要真正的
子进程或网络连接就能完整验证协议核心的行为。

**Acceptance Scenarios**:

1. **Given** 一个满足 `McpTransport` 最小接口的假传输，**When** 客户端发起连接，**Then** 客户
   端按顺序发送 `initialize` 请求（带协议版本/能力/客户端信息）、收到合法响应后发送
   `notifications/initialized` 通知，之后才认为"已连接"（此前的 `list_tools`/`call_tool`
   调用必须被拒绝）。
2. **Given** 已连接的客户端，**When** 发起一次 `list_tools()`，**Then** 客户端自动翻页直到
   `nextCursor` 消失，把所有页的结果合并成一份列表返回；遇到重复的 `nextCursor` 时报错而不是
   死循环。
3. **Given** 一次正在等待响应的 `call_tool` 请求，**When** 调用方取消它（比如传入的取消信号被
   触发），**Then** 客户端本地的这次调用立刻以"已取消"结束，且向服务端发送一条
   `notifications/cancelled` 通知（`initialize` 请求本身不可取消）。
4. **Given** 已连接的客户端，**When** 服务端发来一个 `ping` 请求，**Then** 客户端自动返回空结
   果，不需要调用方代码介入；如果客户端构造时提供了 `roots` 列表，服务端发来 `roots/list` 请
   求时客户端也要自动应答。
5. **Given** 一次等待响应中的请求，**When** 服务端迟迟不回应超过超时时间，**Then** 这次调用以
   超时错误结束；如果期间收到过 `notifications/progress` 通知，超时计时器要重新开始计时，不能
   仍然用最初的截止时间判定超时。
6. **Given** 底层传输掉线（无论是主动 `close()` 还是意外断开），**Then** 所有还在等待响应的请
   求都要立刻以"连接已关闭"结束，不能挂起不返回。

---

### User Story 2 - stdio 传输的健壮子进程生命周期管理 (Priority: P2)

维护者需要 stdio 传输在关闭一个 MCP 服务器子进程时，遵循"先礼后兵"的顺序（关 stdin 给机会优雅
退出 → 超时未退出发终止信号 → 仍不退出强制杀死），并且确保子进程自己又拉起的孙进程（比如
`npx`/`uvx` 这类包装器启动的真正服务器进程）不会变成孤儿残留在系统里；宿主应用本身异常退出时
已经启动的子进程也不应该变成孤儿。

**Why this priority**: 这是现状代码完全没有覆盖的真实生产问题——现状 `connect_and_call_tool`
每次调用都新起一个连接（底层官方 SDK 管理子进程生命周期，细节不透明），一旦改成持久连接/自己
管理子进程，关闭顺序错了就会在生产环境里堆积僵尸/孤儿进程。

**Independent Test**: 启动一个会故意忽略普通终止信号、只在收到 SIGKILL 时才退出的测试脚本作
为"服务器"，断言 close() 最终确实让它退出（验证完整的 stdin 关闭→SIGTERM→SIGKILL 级联）；再
启动一个会再拉起一个子进程的包装脚本，断言关闭后两层进程都不在了（不是只杀了外层）。

**Acceptance Scenarios**:

1. **Given** 一个正常响应终止请求的 stdio 服务器子进程，**When** 调用 `close()`，**Then** 客户
   端先关闭子进程的 stdin，给它一个短暂的宽限期自行退出；没有在宽限期内退出的，发送 SIGTERM；
   仍未退出的，最终发送 SIGKILL（Windows 平台用等效的强制终止机制）。
2. **Given** 一个会自己再拉起子进程的 stdio 服务器（比如用 `npx`/`uvx` 包装的真正服务进程），
   **When** 关闭连接，**Then** 外层包装进程和它拉起的真正服务进程都要被终止，不只是外层。
3. **Given** 多个 stdio 连接已经建立且宿主进程本身被终止（而不是通过正常的 `close()` 路径），
   **Then** 所有已启动的子进程（及其子孙进程）最终都要被清理，不残留孤儿进程。

---

### User Story 3 - Streamable HTTP 传输 (Priority: P3)

维护者需要能连接远程（非本地子进程）的 MCP 服务器，通过 HTTP 发请求、通过 SSE（Server-Sent
Events）接收响应和服务端主动发起的消息。

**Why this priority**: 现状 `MCPServerConfig` 已经有 `http` 这个 transport 分支（字段存在），
说明"连远程服务器"这件事本身已经是既定需求的一部分，不是本次新增范围；但现状的 http 分支把
URL 直接丢给官方 SDK 处理，自己完全没有实现任何 HTTP/SSE 逻辑。

**本次经确认，完整实现 pi 的可靠性机制**：断线自动重连（指数退避）+ 用 `Last-Event-ID` 续传
断线前未读完的响应流，与参考实现对齐，不做成阉割的基础版本。

**Independent Test**: 用一个假的 HTTP 服务端（测试里手写的最小 ASGI/HTTP handler，不依赖真实
网络）驱动一次完整的 `initialize`→`list_tools`→`call_tool` 往返，验证请求体格式、SSE 响应解
析、以及（如果范围确认包含）断线后能否正确重连/续传。

**Acceptance Scenarios**:

1. **Given** 配置了 `http` 传输的服务器，**When** 客户端发起请求，**Then** 请求以 HTTP POST
   发出，响应按 SSE 格式逐事件解析，而不是要求响应体必须是一次性完整的 JSON。
2. **Given** 服务端通过 SSE 推送了一个到达客户端的 JSON-RPC 消息，**Then** 客户端正确把它分发
   成 `handleMessage`（响应/请求/通知三选一）处理，和 stdio 传输收到消息后的处理路径完全一致
   （协议核心对"消息从哪个传输来的"无感知）。
3. **Given** 配置了自定义请求头（供鉴权/代理场景使用）的服务器，**When** 客户端发起任意请求，
   **Then** 这些请求头要出现在实际发出的 HTTP 请求里。

---

### User Story 4 - 内存测试传输 + 工具结果到模型内容的转换 (Priority: P4)

维护者需要（a）一个不涉及真实进程/网络的内存传输，用于给协议核心本身写快速、确定性的单元测
试（User Story 1 的 Independent Test 就依赖它）；（b）一个把 MCP `CallToolResult` 转换成这个
仓库 `Tool`/`ToolOutcome` 约定所需的文本表示的函数，比现状"只处理纯文本 block"更完整地处理图
片/嵌入资源/结构化内容。

**Why this priority**: （a）是其余 User Story 测试能够不依赖真实 I/O 的基础设施，（b）是直接
影响 `MCPTool.acall()` 返回给模型的内容质量、现状明确不完整的一个小缺口，两者都比较独立、风
险低，放在后面交付。

**Independent Test**: 用内存传输配对（客户端侧+服务端侧各拿一半）跑一次完整握手+工具调用，验
证两端收发对称；单独测 `to_llm_content` 对纯文本/图片/嵌入资源/仅有 structuredContent 四种
`CallToolResult` 形状的转换结果。

**Acceptance Scenarios**:

1. **Given** 一对内存传输（一端给客户端、一端给某个测试用的假服务端实现），**When** 跑一次完
   整的 `connect`→`list_tools`→`call_tool`→`close`，**Then** 全程不触发任何真实子进程/网络 I/O，
   且行为和真实传输完全一致。
2. **Given** 一个只包含纯文本 block 的 `CallToolResult`，**When** 转换成模型可读内容，**Then**
   结果和现状行为等价（不回归）。
3. **Given** 一个包含图片 block/嵌入资源 block 的 `CallToolResult`，**When** 转换，**Then** 图
   片被保留为图片内容，嵌入的文本/图片资源被解包成对应的内容块（现状这些会被
   `getattr(block, "text", str(block))` 错误地转成一个 Python 对象的字符串表示）。
4. **Given** 一个没有 `content` 字段、只有 `structuredContent` 的结果，**When** 转换，**Then**
   结果是 `structuredContent` 的 JSON 文本表示，而不是空字符串。

---

### User Story 5 - OAuth 客户端子集 (Priority: P5)

维护者需要让这个客户端能连接要求 OAuth 鉴权的远程 MCP 服务器：发现授权元数据、走 PKCE 授权码
流程、必要时做动态客户端注册、在 token 过期/服务端要求更高授权范围（`insufficient_scope`）时
自动处理。

**Why this priority**: 本次范围里优先级最低、风险最高、代码量最大的一块（参考实现里占
43%），且目前没有任何实际配置场景用到它。

**本次经确认，包含 OAuth 客户端子集**（PKCE 授权码流程、动态客户端注册、token 刷新、
`insufficient_scope` 时的 step-up 授权、本地回调 HTTP 服务器、discovery 协议），与参考实现完
整对齐，即便当前没有配置场景实际使用它——这是本次范围里代码量最大、风险最高（鉴权/凭据处
理）的一块，实现/评审时需要对照宪法"安全敏感代码需要额外谨慎"的要求优先过一轮安全检查。

**Independent Test**: 用假的授权服务器端点（返回固定的发现元数据/token 响应）跑一次完整的
PKCE 授权码换 token 流程；单独测"并发多个请求同时收到 401 时只触发一次刷新、大家共享同一次刷
新结果"这条并发安全保证。

**Acceptance Scenarios**:

1. **Given** 一个要求 OAuth 的服务器，**When** 客户端第一次连接且本地没有可用凭据，**Then**
   客户端抛出一个"需要先完成授权"的特定异常，而不是普通的连接失败，调用方可以据此触发授权流
   程（展示授权 URL 给用户）。
2. **Given** 用户已经在浏览器完成授权、拿到授权码，**When** 调用方把授权码交给客户端，**Then**
   客户端完成 PKCE 换 token，之后的连接能够正常建立。
3. **Given** 一个已经持有 access token 但已过期的客户端，**When** 发起请求收到 401，**Then**
   客户端自动用 refresh token 换一个新的 access token 并重试这次请求，调用方无感知；如果同一
   时刻有多个请求都收到 401，只会触发一次刷新，其余请求等待同一次刷新的结果。
4. **Given** 服务端对某个具体操作返回 `insufficient_scope` 错误，**Then** 客户端能触发一次
   "step-up"授权（申请更高权限范围），而不是把这个错误原样抛给调用方了事。

### Edge Cases

- 子进程/HTTP 连接在"正在发送初始化请求、还没收到响应"这个窗口期意外断开——必须让 `connect()`
  本身以明确的错误失败，不能挂起，也不能让客户端进入一种"看起来连上了但协议核心状态不一致"的
  中间态。
- 服务端返回的 `tools/list`/`resources/list` 结果里混入了不满足最小形状（缺 `name`/
  `inputSchema` 等必需字段）的条目——必须整体拒绝这一页结果并报出清晰错误，而不是把半成品数
  据悄悄喂给上层调用方（上层可能把它当成合法的 `Tool` 直接注册进 `ToolRegistry`）。
- 同一个请求 id 收到了两次响应，或收到了一个客户端完全没有记录过的请求 id 对应的响应——必须
  安全地忽略/报错，不能让状态机混乱或抛出未处理异常搞垮整个连接。
- `MCPServerConfig` 从持久化存储（`apps/api/db.py` 的 `mcp_servers` 表）加载出来时缺字段/字段
  类型不对——这是系统边界（外部可变数据），必须在构造客户端之前校验，给出清晰错误，不能让非
  法配置一路传导到协议层才报错。
- Streamable HTTP 传输收到的单个 SSE 事件/消息体超过约定的大小上限——必须有明确的上限保护，
  不能无限增长占用内存（现状完全没有这层防护，因为协议细节都在官方 SDK 内部）。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须提供一个不依赖任何第三方 MCP SDK 的 JSON-RPC 协议客户端核心，自己实现
  请求关联、每请求独立超时（收到 `notifications/progress` 后重新计时）、客户端/服务端双向发
  起的取消（`notifications/cancelled`）、内置对服务端 `ping`/`roots/list` 请求的自动应答、
  以及 `tools/list`/`resources/list`/`resources/templates/list` 的自动翻页（含重复 cursor 检
  测防止死循环）。
- **FR-002**: `McpServerConfig`（本仓库的 `MCPServerConfig`）从持久化存储加载时必须先完成结构
  校验（必需字段存在、类型正确）才能用于构造客户端，校验失败必须给出清晰的、指向具体字段的
  错误信息。
- **FR-003**: 系统必须提供至少 stdio 和 Streamable HTTP 两种传输实现，二者都满足同一个最小传
  输接口（能发送一条 JSON-RPC 消息、能把收到的消息/错误/关闭事件回调给协议核心），协议核心本
  身不感知消息来自哪种传输。
- **FR-004**: stdio 传输关闭一个子进程时必须按"关闭 stdin 给宽限期 → SIGTERM → SIGKILL（或
  Windows 等效机制）"的顺序执行，并确保子进程自己拉起的子孙进程一并被终止，不残留孤儿进程；
  宿主应用异常退出时已启动的子进程最终也要被清理。
- **FR-005**: 系统必须提供一个不涉及真实进程/网络 I/O 的内存传输实现，供协议核心自身的单元测
  试使用。
- **FR-006**: 系统必须提供一个把 MCP `CallToolResult`（文本/图片/嵌入资源/资源链接/二进制资
  源/`structuredContent` 等形状）转换成这个仓库 `ToolOutcome` 约定所需文本表示的函数，覆盖面
  不低于现状（纯文本透传）且至少额外正确处理图片内容与"仅有 `structuredContent`"的情况。
- **FR-007**: 系统必须支持 MCP 协议版本 `2025-11-25`，并接受服务端协商降级到
  `2025-06-18`/`2025-03-26`/`2024-11-05` 中的任意一个；协商结果使用服务端在
  `initialize` 响应里实际返回的版本。
- **FR-008**: `packages/mcpclient` 对外暴露的公共符号（类/函数/异常类型）变化（如果有）不得
  要求 `apps/api/main.py`/`apps/api/runtime.py`/`packages/mcpclient/tools.py` 之外再新增别的
  调用点改动——即调用方改造范围限定在这三个已知文件，不应该出现需要触达更多未预料到的文件才
  能完成迁移的情况（如果规划阶段发现确实需要，必须在实现前明确说明原因）。
- **FR-009**: 客户端必须支持作为持久会话对象使用——构造一次、连接一次，之后支持反复发起请求
  直到显式关闭或连接掉线；`apps/api/runtime.py`/`packages/mcpclient/tools.py` 的
  `MCPTool`/调用方必须相应迁移为持有并复用该连接，不再对"探测工具列表"和"执行工具调用"各自建
  立一次性、用完即断的连接（这是对现有行为的刻意替换，见 Clarifications）。
- **FR-010**: Streamable HTTP 传输断线时必须按指数退避策略自动重连，并使用服务端提供的
  `Last-Event-ID`（或协议规定的等价续传标识）续传断线前未完整接收的响应流；调用方不需要自己
  实现任何重连/续传逻辑。
- **FR-011**: 系统必须提供 OAuth 客户端子集：发现受保护资源/授权服务器的元数据、PKCE 授权码
  流程、必要时的动态客户端注册、收到 401 时自动用 refresh token 换新 access token 并重试（并
  发场景下多个请求同时收到 401 只触发一次刷新、共享同一次结果）、`insufficient_scope` 时触发
  一次 step-up 授权流程；未配置 OAuth 的服务器完全不受这部分代码路径影响（不强制所有连接都走
  OAuth 发现流程）。
- **FR-012**: OAuth 相关的凭据（access token、refresh token、client 注册信息）的存储方式必须
  是可由调用方注入的（而不是写死在 `packages/mcpclient` 内部），这个包本身不负责选择凭据持久
  化在哪里。

### Key Entities

- **JSON-RPC 消息**：请求（带 id，期待响应）、响应（成功结果或错误）、通知（不带 id，不期待
  响应）三选一的协议消息。
- **传输（Transport）**：负责消息的实际收发/编解码（stdio 子进程的 stdin/stdout 行协议、HTTP
  的请求体+SSE 响应流、内存测试用的直接配对），不关心消息内容的协议语义。
- **客户端会话**：一次 `initialize`握手之后、`close()`之前的连接期——持有服务端信息/能力/协
  议版本、所有尚未返回的请求、正在处理的服务端发起请求。
- **待处理请求**：一次已发出、尚未收到响应的请求，带超时计时器、可选的取消信号、可选的进度
  回调。
- **工具调用结果**：MCP 服务端对一次 `tools/call` 的响应，可能包含文本/图片/嵌入资源/资源链
  接/二进制资源等多种内容块，以及可选的 `structuredContent`。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `packages/mcpclient` 的 `pyproject.toml`（或等价依赖声明）不再要求官方 `mcp`
  PyPI 包作为运行时依赖。
- **SC-002**: 现有的"添加/刷新 MCP 服务器"和"模型调用 MCP 工具"两条用户可见路径，在完成这次
  对齐后行为保持可用（不出现之前能用、现在报错的服务器配置）。
- **SC-003**: 一次客户端发起的工具调用取消，能在服务端侧观察到对应的取消通知被发送（不是客
  户端本地假装取消、服务端完全不知情继续白跑）。
- **SC-004**: 一个会拉起子孙进程、且对普通终止信号没有反应的 stdio 测试服务器，在客户端
  `close()` 调用完成后，操作系统里找不到任何与它相关的残留进程。
- **SC-005**: 一个包含图片内容的工具调用结果，模型看到的最终内容里图片以可用的格式呈现，而
  不是一段不可读的 Python 对象字符串。
- **SC-006**: 同一个已启用的 MCP 服务器在一次对话里被连续调用多次工具，底层只建立一次连接
  （而不是每次工具调用都重新握手），直到连接被显式关闭或掉线。
- **SC-007**: 一个要求 OAuth 的远程服务器，用户能够走完"打开授权链接 → 授权 → 自动换 token →
  连接成功"的完整流程并开始使用它的工具，不需要手动管理 token 的刷新。
- **SC-008**: 一个远程 HTTP 服务器连接在响应流接收到一半时断开，客户端自动重连并续传剩余内
  容，调用方感知到的是一次完整、未丢失数据的响应，而不是一次失败需要重试的请求。

## Assumptions

- "完全按照 pi 的内核实现"理解为对齐其**架构设计**（transport-neutral 协议核心、请求关联/超
  时/取消/分页机制、stdio 子进程生命周期管理、可续传的 Streamable HTTP 传输、内存测试传输、
  `CallToolResult` 到模型内容的转换、OAuth 客户端子集、持久会话模型——经 Clarifications 确认
  全部包含，不分阶段）而不是逐行照搬 TypeScript 代码或标识符命名——Python 一侧用
  `asyncio`/`dataclass`/标准库 `subprocess` 等惯用写法表达同样的语义，不强行复刻 `camelCase`/
  TS 专属命名或 `AbortSignal` 这类 TS 运行时概念（Python 用 `asyncio.Event`/取消令牌等价表
  达）。
- 本次范围明确包含一处对**已上线、已有调用方依赖**行为的替换，且已经过用户确认，不是误判的
  回归：`connect_and_list_tools()`/`connect_and_call_tool()` 这两个"一次性连接"便捷函数被持久
  会话模型取代，`apps/api/runtime.py`/`packages/mcpclient/tools.py` 的 `MCPTool` 需要相应改造
  成持有并复用连接（FR-009）。
- 底层 HTTP/SSE 的具体实现是否使用某个第三方 HTTP 客户端库（如本仓库 `websearch` 包已经在用
  的那一类）还是纯标准库，属于技术选型细节，留给 `/speckit-plan` 决定，不在这里约束。
- 本次范围不包含 MCP 协议里的 `sampling`、`tasks`、批量 JSON-RPC 消息、legacy HTTP+SSE（旧版
  传输）——这些 pi 自己的 README 也明确写了"不在初始核心范围内"，不是本次遗漏。
