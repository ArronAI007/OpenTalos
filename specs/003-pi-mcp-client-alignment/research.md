# Phase 0 Research: packages/mcpclient 对齐 pi 的独立 MCP 协议实现

本次调研基于对真实代码的阅读：`/tmp/pi-reference/packages/mcp/src/{client.ts,transports/*.ts,
protocol/*.ts,auth-provider.ts,oauth/*.ts}`（全部 14 个源文件，约 3200 行，全读）；本仓库现状
`packages/mcpclient/{client.py,tools.py,demo_server.py,__init__.py}`、
`tests/mcpclient/{test_mcpclient_client.py,test_mcpclient_tools.py}`、`apps/api/{main.py,db.py,
runtime.py}` 里全部调用点；`packages/tool/outcome.py`（`ToolOutcome` 的真实契约）；
`pyproject.toml`。不是对 spec.md 的转述。

## 决策 1：持久会话的具体类/函数形状，以及现有一次性函数的去留

**决策**：新增 `MCPClient`（`packages/mcpclient/client.py`）作为持久会话类，构造一次
（`MCPClient(server_config)`）、`await client.connect()` 一次，之后反复 `await
client.list_tools()`/`await client.call_tool(name, arguments)`/`await client.ping()`，直到显式
`await client.close()` 或底层传输掉线（`MCPConnectionError` 在下次调用时抛出）。

`connect_and_list_tools()`/`connect_and_call_tool()` 这两个现状的一次性函数**整体删除**（FR-009
已确认是刻意替换，不是兼容层）。但删除不等于"所有调用方都要变成持久会话"——按场景区分：

- `apps/api/main.py` 的"创建/刷新服务器"两个路由，语义上就是一次性探测（用户点一次按钮，探测
  一次就收工），**不需要**持有连接到下次探测。这两个路由改写为"构造 `MCPClient` → `connect()` →
  `list_tools()` → `close()`"的内联序列（用 `async with` 风格的上下文管理器，`MCPClient` 实现
  `__aenter__`/`__aexit__` 包裹 `connect()`/`close()`，和官方 SDK 现状用法的"外壳"一致，内部实
  现完全不同）——这是 FR-009 里"不再对探测各自建立一次性连接"这句话字面意义上的例外吗？不是：
  FR-009 说的是"不再用连接即用即弃的方式反复探测/执行工具"，针对的是 `MCPTool.acall()` 这条真正
  会被高频重复调用的路径；探测路由本来就是低频、一次性的操作，继续用"开-用-关"模式不违反
  FR-009 的意图，只是不再委托给官方 SDK 实现这个模式，而是用自己的 `MCPClient` 实现。
- `packages/mcpclient/tools.py` 的 `MCPTool.acall()` 才是 FR-009 真正要改的地方：`MCPTool` 内部
  持有一个 `self._client: MCPClient | None = None`，首次 `acall()` 时 `await self._client.connect()`
  （懒连接，不在 `__init__` 时就建连接——构造 `MCPTool` 本身不该有副作用，和现状的"构造只存配
  置"行为保持一致），之后反复调用复用同一个连接；新增 `async def aclose(self) -> None`，供调用
  方（`apps/api/runtime.py`）在合适的时机显式关闭。

对应 FR-009。`apps/api/runtime.py` 的连接生命周期绑定方式见 Decision 2。

**备选方案**：保留 `connect_and_list_tools`/`connect_and_call_tool` 作为 `MCPClient` 之上的薄兼
容包装函数，不删除。被否决——这是经用户确认的刻意行为替换（Clarifications Q1=A），保留两套并
存的 API 入口会让"到底该用哪个"变成一个新的、本不该存在的选择，违反宪法原则 IV。

## 决策 2：持久连接的生命周期绑定到哪个粒度

**决策**：绑定到 `apps/api/runtime.py` 里已经存在的**按 `task_id` 缓存 Agent + `evict(task_id)`
清理**这个既有模式，不引入新的生命周期概念。核实 `_get_agent()`（`apps/api/runtime.py:362-415`）
发现：`self._agents` 按 `task_id` 缓存 `Agent` 实例，命中缓存直接返回（**不会**重新调
`_ensure_mcp_tools()`/`_build_registry()`）；只有某个 `task_id` 第一次被请求时才会走一遍"建
`MCPTool` 实例 → 注册进该任务专属的 `ToolRegistry`"这条路径。也就是说，`_ensure_mcp_tools()`
构造出来的一批 `MCPTool` 实例，实际上天然就是"每个任务各自一套、只在该任务第一次创建 Agent 时
构造一次"——这正好是持久连接需要的那个生命周期粒度，不需要额外设计一个新的绑定维度（比如"按服
务器全局共享一个连接池"这种需要处理跨任务并发访问同一条连接的复杂度）。

具体改动：`AgentRuntime` 新增 `self._task_mcp_tools: dict[str, list[MCPTool]] = {}`；
`_ensure_mcp_tools()` 构造出的 `MCPTool` 列表在 `_get_agent()` 里（紧跟 `_build_registry(task["id"])`
调用之后）存一份到 `self._task_mcp_tools[task["id"]]`；`evict(task_id)`（现有方法，
`runtime.py:424-429`）新增一步：对 `self._task_mcp_tools.pop(task_id, [])` 里的每个 `MCPTool`
调用 `await tool.aclose()`（连接未建立过时 `aclose()` 是no-op，不需要先查是否连接过）。

对应 FR-009、SC-006。`evict()` 现状是同步方法（`def evict`，非 `async def`）——这次需要改成
`async def evict`，调用方（`request_stop`/任务结束路径，需要在 `/speckit-tasks` 阶段核实全部调
用点）相应改成 `await self.evict(task_id)`，这是 FR-008 允许范围内（`apps/api/runtime.py` 本身）
的必要连带改动，不算"意外新增的调用点"。

**备选方案 A**：连接生命周期绑定到单个 `MCPServerConfig`（全局共享，跨任务复用同一条连接）。被
否决——pi 自己的 `McpClient` 也不是"全局单例"语义，是"调用方按自己的需要构造多少个就有多少
个"；全局共享会引入"多个任务并发调用同一条连接的 `call_tool`"这个新的并发正确性问题（虽然
JSON-RPC 请求关联本身能正确区分响应，但 stdio 子进程异常退出会同时影响所有正在使用它的任务，
波及面不必要地扩大），且现状"每个任务各自探测一遍 `list_mcp_servers()`"的既有设计（见
`_ensure_mcp_tools()` 的注释"这样 /mcp 页面上启用/禁用某个 server 才能在下一个新建的 task 里立
刻生效，不用重启进程"）本来就是按任务粒度设计的，全局共享会和这条既有设计意图冲突。

**备选方案 B**：每次 `acall()` 调用结束后立刻关闭连接（"伪持久"，实际还是连接即用即弃）。被否
决——这完全不满足 FR-009/SC-006 的字面要求（"同一个服务器一次对话里只建立一次连接"）。

## 决策 3：JSON-RPC 协议核心的 Python 落地形状

**决策**：`packages/mcpclient/protocol/jsonrpc.py` 用 `dataclass` 表达三种消息（`JsonRpcRequest`/
`JsonRpcNotification`/`JsonRpcResponse`，后者内部用 `result: Any | None`/`error: JsonRpcErrorObject
| None` 两个可选字段表达"成功或错误二选一"，而不是 pi 的 TS 判别联合——Python 没有原生判别联合
语法，`dataclass` + 运行时检查哪个字段非空是最直接的惯用写法）、`JSON_RPC_ERROR_CODES` 用
`IntEnum`、异常类用标准的 `class XxxError(MCPConnectionError)` 继承链（见 Decision 5 的异常设
计）。请求关联用 `dict[int, PendingRequest]`（`nextRequestId` 用一个简单的实例计数器）；每个
`PendingRequest` 持有一个 `asyncio.Future`（用于投递最终结果/异常）+ 超时任务句柄（`asyncio.
TimerHandle` 或 `asyncio.wait_for` 包装，续期时取消重建）。取消用 `asyncio.Event`（Python 没有
`AbortSignal`，`asyncio.Event` 是标准等价物，Assumptions 已确认）。分页（`list_tools`等）用一个
内部 `_list_all(method, params, result_key)` 辅助函数，统一处理"带着上一页 `nextCursor` 请求下一
页，直到 `nextCursor` 消失；遇到和上一页相同的 `nextCursor` 时报 `MCPProtocolError`"的逻辑，三个
分页方法（`list_tools`/`list_resources`/`list_resource_templates`）共享它，不各写一份。

对应 FR-001、FR-007。

**备选方案**：用 `pydantic.BaseModel` 代替 `dataclass` 表达 JSON-RPC 消息，借助 pydantic 的校验
能力。被否决——这个协议层需要高频构造/解析（每个请求/响应都要经过），`pydantic` 的校验开销和
`dataclass` 相比不必要；且 `pydantic` 的强类型校验对"错误消息里允许任意形状的 `data` 字段"这种
故意宽松的协议细节反而不友好。`MCPServerConfig`（从持久化存储加载，真正需要边界校验的地方，见
决策 4）继续用现状已经验证过的 `dataclass` + 显式校验函数风格，不引入 pydantic 作为这次改动的
新增依赖。

## 决策 4：`MCPServerConfig`/分页结果/OAuth 元数据的结构校验怎么落地（宪法原则 III）

**决策**：`MCPServerConfig` 保持现状的 `dataclass` 形状不变（`transport`/`command`/`args`/`url`/
`env`），新增一个独立的 `validate_server_config(data: dict) -> MCPServerConfig` 工厂函数（供
`apps/api/db.py` 读出 `mcp_servers` 表的 `config` JSON 字段后构造实例前调用），必需字段缺失/类
型不对时抛 `MCPConfigValidationError`（新增，继承 `MCPConnectionError`），错误信息里带具体字段
名和期望类型（对应 FR-002/Edge Cases 第 4 条）。分页结果的"整体拒绝不满足最小形状的条目"
（Edge Cases 第 2 条）落在 `protocol/types.py` 的 `is_tool(data) -> bool`/`is_resource(data) ->
bool` 等类型判定函数里——直接对齐 pi `isTool`/`isResource` 的角色，`_list_all` 辅助函数对每一页
结果逐条校验，任何一条不满足就整页报 `MCPProtocolError`，不做"挑出合法的那几条、丢弃不合法的"
这种静默降级（会把"服务端返回了半成品数据"这个真实问题悄悄隐藏掉）。OAuth 元数据（发现响应）
同理在 `oauth/types.py` 用 `parse_protected_resource_metadata`/`parse_authorization_server_metadata`
等函数做结构校验，直接对齐 pi `oauth/types.ts` 的 `parse*` 函数集合（包括拒绝 `javascript:`/
`data:`/`vbscript:` 这类不安全 URL scheme 的检查，这是 OAuth 子集本身安全评审的一部分）。

对应 FR-002、Edge Cases 第 2/4 条、OAuth 安全评审要求。

## 决策 5：异常类型层级——新增类型怎么和现有的 `MCPConnectionError` 共存

**决策**：新增 `MCPTimeoutError`/`MCPAbortError`/`MCPProtocolError`/`MCPConfigValidationError`/
`MCPOAuthAuthorizationRequiredError`，全部继承自现有的 `MCPConnectionError`（不是平级新建一套异
常体系）。这样 `apps/api/main.py` 现状的 `except MCPConnectionError as error: raise
HTTPException(502, str(error))`、`packages/mcpclient/tools.py` 现状的 `except MCPConnectionError
as error: return ToolOutcome.error(str(error))`，这两处已有的 catch 分支**不需要修改**就能继续
正确工作（细粒度异常类型是额外可选的能力，不是破坏性要求）——直接满足 FR-008 的"调用方改造范
围限定在三个已知文件"约束，因为这两处恰好就在那三个文件之内，而且改动量是"不改"。

对应 FR-008（约束）、FR-001（取消/超时需要可区分的异常类型供内部协议核心逻辑使用，即便外部调
用方选择不区分）。

**备选方案**：新增异常类型平级独立（不继承 `MCPConnectionError`）。被否决——会让
`apps/api/main.py`/`tools.py` 现状的 `except MCPConnectionError` 分支漏接新异常类型，连接失败
会变成未捕获异常直接 500，这是一次隐藏的破坏性变更，违反 FR-008。

## 決策 6：OAuth 回调怎么从 pi 的独立 CLI 回调服务器适配成 `apps/api` 的 Web 服务

**决策**：不照搬 pi 的 `OAuthCallbackServer`（独立 `node:http.createServer`，CLI 工具专属模式）。
`packages/mcpclient/oauth/callback.py` 只提供一个运行时无关的 `PendingCallbackRegistry`——
`register(state: str) -> asyncio.Future[dict]`（登记一个等待中的回调，返回一个会被外部解析的
Future）+ `resolve(state: str, params: dict) -> bool`（外部收到真实 HTTP 回调请求时调用，解析对
应 Future；`state` 不存在时返回 `False`，调用方据此给出 404）。真正接收浏览器重定向的 HTTP 路由
是 `apps/api/main.py` 新增的一个 FastAPI 路由（具体路径留给 `/speckit-tasks`，例如 `GET
/api/mcp/oauth/callback`），内部直接调 `registry.resolve(state, dict(request.query_params))`。
这个模式直接复用 `apps/api/runtime.py` 第 175/318-330/694 行一直在用的
`self._pending_approvals: dict[str, tuple[str, asyncio.Future[bool]]]`（审批网关的"挂起 Future、
等外部 HTTP 请求到来解析它"模式），只是把"工具调用审批"换成"OAuth 回调"这个新场景，模式本身是
已经在生产代码里验证过的，不是凭空发明。

对应 FR-011、SC-007。

**备选方案**：照搬 pi 的做法，在 `packages/mcpclient` 内部起一个独立的 `http.server`/`asyncio`
临时 HTTP 服务器监听一个随机端口。被否决——`apps/api` 本身已经是一个常驻、可公网访问的 Web 服
务；再起一个临时服务器意味着两个问题：(1) 需要额外处理端口分配/防火墙/反向代理这个服务器不在
已有路由表里这件事，(2) 浏览器完成 OAuth 授权后重定向到的 `redirect_uri` 应该指向用户已经在访
问的同一个 `apps/api` 域名/端口下的某个路径，而不是另一个临时端口——这和"apps/api 是一个常驻
Web 后端，不是 CLI 工具"这个根本性的部署形态差异直接相关，项目 memory
`[[feedback_reference_project_renaming]]`（移植参考实现的架构语义，不照搬不适配目标运行环境的
具体机制）明确适用于这种情况。

## 决策 7：`demo_server.py` 和官方 `mcp` 依赖的去留

**决策**：`packages/mcpclient/demo_server.py` **不变**，继续 `from mcp.server import MCPServer`。
理由：这次重写的范围是 MCP **客户端**（pi 自己的 README 和这个仓库的 spec 标题都明确是
"client"），`demo_server.py` 扮演的是被连接的**服务器**角色，是两个真机测试文件
（`test_mcpclient_client.py`/`test_mcpclient_tools.py`）已经在用的测试夹具，不是生产客户端代码
路径的一部分。重新用从零实现的方式写一个 MCP *server*，完全超出这次"对齐 pi 的*client*内核实
现"这句话的字面范围，属于范围蔓延。唯一需要的改动是 `pyproject.toml`：`mcp>=2.3.0` 从
`[project].dependencies` 移到 `[dependency-groups].dev`——`demo_server.py` 只在测试时需要被启
动，不是生产运行时路径会 import 到的模块（`packages/mcpclient/__init__.py` 不会 import
`demo_server`），这样 `packages/mcpclient` 自己的生产代码（`client.py`/`tools.py`/`protocol/`/
`transports/`/`oauth/`）对官方 `mcp` 包零依赖，字面满足 SC-001。

对应 SC-001、Assumptions（"OAuth/传输/协议核心架构对齐，不要求逐行照搬"同样适用于"demo_server
该不该重写"这个问题——不属于 User Story 1-5 任何一条范围）。

**备选方案**：把 `demo_server.py` 也用这次新写的协议核心反向实现成一个 MCP server（复用
`protocol/jsonrpc.py`/`protocol/types.py` 的类型定义）。被否决——spec.md 的全部 5 个 User Story
和全部 FR/SC 条目没有一条提到"服务器端实现"，这是一次会让任务列表膨胀却不对应任何验收标准的
额外工作，违反宪法原则 IV（拒绝过度工程）。

## 决策 8：`to_llm_content` 的转换结果如何在 `ToolOutcome.output: str` 这个纯文本契约下落地
（FR-006/SC-005 与 `packages/tool` 边界的张力）

**决策**：`packages/mcpclient/protocol/content.py` 的 `to_llm_content(result: CallToolResult) ->
list[LlmContent]` **忠实对齐 pi 的完整转换语义**——`LlmContent` 是一个 `text`/`image` 两种成员的
联合类型（用 `dataclass` + 字面量 `type` 字段区分，Python 惯用写法），文本/图片 block 直接透
传，嵌入的文本/图片资源解包成对应的 `LlmContent` 成员，音频/资源链接/二进制资源转成简短文本占
位符，只有 `structuredContent` 没有 `content` 时用它的 JSON 文本。这个函数本身**完整**满足
FR-006 的字面要求，不打折扣。

`packages/mcpclient/tools.py` 的 `MCPTool.acall()` 调用 `to_llm_content()` 之后，在**这一层**
（不是在 `to_llm_content` 内部）把 `list[LlmContent]` 压平成 `ToolOutcome.output` 要求的单个
`str`：文本成员按顺序拼接（和现状行为等价，满足 Acceptance Scenario 2 的不回归要求）；图片成员
转成一行可读占位符（例如 `[图片内容：image/png，2048 字节]`，不是 `str(ImageContent(...))` 这种
Python 对象 repr）——这满足 SC-005 的字面验收标准（"图片以可用的格式呈现，而不是一段不可读的
Python 对象字符串"），同时不需要改动 `packages/tool/outcome.py` 的 `ToolOutcome.output: str`
契约或 `packages/core`/`packages/agents` 的消息构建管线去支持真正的多模态结构化内容传给模型
——那是一次跨越 `packages/mcpclient` 包边界的、影响面大得多的改动，不在这次"对齐 pi 的 mcp
client 内核"范围内，也没有任何一条 User Story/FR 要求"模型最终收到的是结构化多模态内容"，只要
求"图片以可用格式呈现"（SC-005 的措辞本身是技术无关的，"可用格式"不等于"结构化多模态")。

对应 FR-006、SC-005、Acceptance Scenario（User Story 4，第 2/3/4 条）。

**备选方案**：改造 `packages/tool/outcome.py`，让 `ToolOutcome.output` 支持 `str | list[LlmContent]`
联合类型，一路打通到 `packages/core` 的消息构建，实现真正的多模态模型输入。被否决——这是一次跨
包边界的架构改动，`packages/tool`/`packages/core`/`packages/agents` 都不在这次 spec 的 Key
Entities/FR/Project Structure 范围内；真要做，应该是一个独立的、专门讨论"工具结果多模态化"的
feature，不应该夹带在"mcp client 内核对齐"这个本应聚焦在 `packages/mcpclient` 内部的改动里。
