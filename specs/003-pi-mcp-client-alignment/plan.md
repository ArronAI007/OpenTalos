# Implementation Plan: packages/mcpclient 对齐 pi 的独立 MCP 协议实现

**Branch**: `003-pi-mcp-client-alignment` | **Date**: 2026-10-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-pi-mcp-client-alignment/spec.md`

## Summary

把 `packages/mcpclient` 从"官方 `mcp` PyPI SDK 的薄封装（每次操作一次性连接-执行-断开）"整体替
换成对齐 `earendil-works/pi` `packages/mcp` 的从零实现：一个 transport-neutral 的 JSON-RPC 协议
核心（自己做请求关联/超时续期/双向取消/服务端主动请求自动应答/分页）、三种独立实现的传输
（stdio 子进程生命周期管理、可断线重连续传的 Streamable HTTP、纯内存测试传输）、一个把
`CallToolResult` 转成模型可读内容的转换函数、以及完整的 OAuth 客户端子集。范围经 `/speckit-clarify`
前的 `/speckit-specify` 内联澄清确认为"全部对齐"：持久会话模型（替换现状的
`connect_and_list_tools`/`connect_and_call_tool` 一次性连接函数）、完整的 HTTP 重连续传、完整的
OAuth 子集，三项都不分阶段削减。调用方改造范围按 FR-008 限定在 `apps/api/main.py`、
`apps/api/runtime.py`、`packages/mcpclient/tools.py` 三个已知文件。

## Technical Context

**Language/Version**: Python 3.12+（与 `001`/`002` 一致，`.venv` 实际跑 Python 3.13.5）

**Primary Dependencies**: `httpx>=0.27`（已是 `[dependency-groups].dev` 依赖，Streamable HTTP 传输
复用它的 `AsyncClient.stream()` 做 SSE 读取和重连请求，不新增 HTTP 库；本次计划把它提升为
`packages/mcpclient` 的主依赖，因为它不再只是测试工具）；不引入任何 MCP 协议/SSE 解析/OAuth 专用
第三方库——JSON-RPC 关联、SSE 帧解析、PKCE（`hashlib`+`secrets`）、OAuth 发现/token 请求全部用标
准库 + `httpx` 手写，对齐 pi"不依赖 SDK，只依赖通用 HTTP 客户端"的设计立场。stdio 传输用标准库
`asyncio.create_subprocess_exec`，不引入 `cross-spawn` 的等价第三方包（Python 的
`create_subprocess_exec` 本身跨平台，不需要 shell 猜测可执行文件路径那层封装）。

**Dependency change**: 官方 `mcp` PyPI 包从 `[project].dependencies`（pyproject.toml 第 15 行）移到
`[dependency-groups].dev`——`packages/mcpclient` 自身的协议/传输实现代码不再 import 它，唯一继续
依赖它的是 `packages/mcpclient/demo_server.py`（见 Decision 7），这是一个供真机测试用的 MCP
*server* 测试夹具，不是本次重写的*client*生产代码路径的一部分。这一步直接兑现 SC-001（"不再要求
官方 mcp PyPI 包作为运行时依赖"——SC-001 的措辞本身就是"运行时依赖"，为测试依赖留了空间）。

**Storage**: N/A（不涉及 SQLite schema 变更；`apps/api/db.py` 的 `mcp_servers` 表结构不变，`config`/
`cached_tools` 两个 JSON 字段的内容形状不变）

**Testing**: pytest + pytest-asyncio（`.venv/bin/pytest`）。沿用 `tests/mcpclient/` 现有的"真机测
试、不 mock"风格——`test_mcpclient_client.py`/`test_mcpclient_tools.py` 都是直接对
`packages/mcpclient/demo_server.py` 发起真实 stdio/HTTP 子进程连接；协议核心本身的单元测试改用
User Story 4 的内存传输（`InMemoryTransport`）而不是每个协议细节（取消、超时续期、重复 cursor
检测等）都要起一个真实子进程——这是 FR-005/User Story 1 Independent Test 明确要求的测试基础设
施，不是额外发明。stdio/HTTP 传输层的生命周期/重连测试继续用真实子进程（demo_server.py 或专门的
测试夹具脚本），因为这些行为（SIGTERM 级联、断线重连）本质上需要真实进程/真实网络中断才能验证。

**Target Platform**: 本仓库现有后端进程（`apps/api`，macOS/Linux 为主，stdio 传输的子进程终止逻辑
需要按 FR-004 提供 Windows 等效分支，但不要求本次在 Windows 上实机验证——现有 CI/开发环境是
macOS，这一点与 002 的"不涉及新部署目标"一致）

**Project Type**: 单仓库多 Python 包。本次改动范围：`packages/mcpclient` 内部整体重写（新增协议
核心/传输/OAuth 子模块），`packages/mcpclient/demo_server.py` 不变（继续用官方 SDK 扮演测试用的
服务器角色），`apps/api/main.py`/`apps/api/runtime.py` 按 FR-008 的既定范围改造持久会话的生命周
期绑定点，`pyproject.toml` 调整依赖分组。不涉及 `packages/core`/`packages/agents`/`packages/tool`
的改动（`MCPTool` 仍然是普通的 `Tool` 子类，`ToolOutcome` 契约不变）。

**Performance Goals**: 不是本次关注点；唯一的可观察性能变化是 SC-006 要求的"同一个服务器一次对
话里只建立一次连接"（减少握手次数），这是正确性/资源行为要求，不是吞吐量指标。

**Constraints**: FR-008（调用方改造范围限定在 3 个已知文件）必须成立；FR-009 的持久会话迁移、
FR-010 的完整 HTTP 重连续传、FR-011/FR-012 的完整 OAuth 子集三项都是经确认的"全部交付"范围，不
允许在 `/speckit-tasks` 阶段自行拆成"先做基础版本"；SC-001 要求官方 `mcp` 包不再是运行时依赖（见
上方 Dependency change）；OAuth 相关代码按 Clarifications 的要求，实现/评审阶段需要先过一轮针对
性的安全检查（鉴权/凭据处理）。

**Scale/Scope**: `packages/mcpclient` 当前 3 个源文件（`client.py`/`tools.py`/`demo_server.py`，
`__init__.py` 为空）；本次预计重写/新增约 20 个源文件（协议核心 3-4 个、传输 4 个、OAuth 6 个、
加 `client.py`/`tools.py`/`__init__.py` 的重写），按 Project Structure 一节的目录布局组织，保持
"文件保持短小聚焦"的既有约定，直接对应 pi 参考实现的模块切分（人工翻译成 Python 风格命名，不是推
平成一个大文件）。`apps/api/runtime.py` 新增一小块"任务级 MCP 连接生命周期"记录+清理逻辑（见
Decision 2）；`apps/api/main.py` 的两个探测路由改用新客户端的"一次性连接"用法（无需持久化）；新
增一个 OAuth 回调路由（FR-011/SC-007，具体路径留给 `/speckit-tasks`）。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

依据 `.specify/memory/constitution.md` v1.0.0 的五条原则逐一检查：

- **I. TDD（不可协商）**：`/speckit-tasks` 产出的每个任务都先写测试再实现；协议核心/传输/OAuth
  各自独立可测（User Story 1-5 各自的 Independent Test 已经在 spec.md 里写明），`tests/mcpclient/`
  现有两个真机测试文件会被改写（`connect_and_list_tools`/`connect_and_call_tool` 这两个被替换的
  函数不再存在，断言需要跟着新的 `MCPClient` 持久会话 API 调整）而不是删除后不补。✅ 通过。
- **II. 代码规范一致性**：纯 Python 改动，遵循现有 ruff/black 风格和 snake_case 模块命名（不照搬
  pi 的 TS camelCase 标识符，Assumptions 已明确）；不涉及前端。✅ 通过。
- **III. 输入必须校验**：FR-002（`MCPServerConfig` 从持久化存储加载时的结构校验）、Edge Cases 里
  "服务端返回的分页结果混入不满足最小形状的条目必须整体拒绝"、OAuth 元数据的结构校验（对齐 pi
  `oauth/types.ts` 的 parse 函数），都是系统边界输入校验的具体体现，data-model.md 会为每个从外部
  （持久化存储/网络响应）进入的类型标注校验规则。✅ 通过。
- **IV. 简洁至上，拒绝过度工程**：本次范围内的"复杂度"（三种传输、OAuth 子集）是спec 经用户明
  确确认的范围，不是本计划自行添加的；demo_server.py 保持用官方 SDK 不重写（见 Decision 7）是避
  免"连服务器也要重新实现"这种明显超出范围的工作；OAuth 回调复用 `apps/api/runtime.py` 已有的
  `_pending_approvals` pending-Future 模式（见 Decision 6），不引入一个独立的回调 HTTP 服务器这
  种在 CLI 场景才合理、在已经是常驻 Web 服务的 `apps/api` 里属于多余抽象的机制。✅ 通过。
- **V. 接口文档完整性**：协议核心、三种传输、OAuth 子集各自在 `contracts/` 下有独立契约文档；
  `data-model.md` 列出全部新增类型的字段级说明和校验规则。✅ 通过。

无违反项，不需要在 Complexity Tracking 表格里做"违规申诉"；下方表格仅作说明性记录。

**Post-Design Re-check（Phase 1 完成后复查）**：`data-model.md` 定稿的全部新增类型都能在
`contracts/` 里找到对应契约；`research.md` 的每条决策都标注了对应的 Functional Requirement；
`quickstart.md` 的验证场景覆盖全部 5 个 User Story 的 Acceptance Scenarios + SC-001 到 SC-008。五
条原则依然全部通过，无新增违规。

## Project Structure

### Documentation (this feature)

```text
specs/003-pi-mcp-client-alignment/
├── plan.md               # This file (/speckit-plan command output)
├── research.md           # Phase 0 output (/speckit-plan command)
├── data-model.md         # Phase 1 output (/speckit-plan command)
├── quickstart.md         # Phase 1 output (/speckit-plan command)
├── contracts/            # Phase 1 output (/speckit-plan command)
│   ├── protocol-core.md
│   ├── transports.md
│   ├── content-conversion.md
│   └── oauth.md
└── tasks.md               # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
packages/mcpclient/
├── __init__.py              # 改：导出公共符号（MCPClient、MCPServerConfig、MCPToolInfo、
│                             #     MCPConnectionError 及其子类、to_llm_content 等）
├── client.py                 # 重写：MCPClient 持久会话类（取代 connect_and_list_tools/
│                              #     connect_and_call_tool 两个一次性函数，见 Decision 1）；
│                              #     保留 MCPServerConfig/MCPToolInfo/MCPConnectionError 这三个
│                              #     现有公共符号名（FR-008 兼容性约束）
├── protocol/
│   ├── __init__.py
│   ├── jsonrpc.py              # 新增：JsonRpcRequest/Notification/Response(Success/Error)、
│   │                           #     JSON_RPC_ERROR_CODES、parse_jsonrpc_message、
│   │                           #     类型判定函数（is_request/is_notification/is_response）
│   ├── types.py                 # 新增：Tool/Resource/ResourceTemplate/ClientCapabilities/
│   │                            #     ServerCapabilities/Root/ProgressNotification/
│   │                            #     Implementation/InitializeResult，以及协议版本常量
│   │                            #     （LATEST_PROTOCOL_VERSION/SUPPORTED_PROTOCOL_VERSIONS）
│   └── content.py                # 新增：ContentBlock 联合类型、CallToolResult、LlmContent
│                                  #     联合类型、to_llm_content() 转换函数（对应 FR-006）
├── transports/
│   ├── __init__.py
│   ├── base.py                  # 新增：McpTransport Protocol（最小传输接口）+
│   │                             #     TransportEventsMixin（监听器登记/一次性 close 事件的
│   │                             #     共享样板，对应 pi 的 TransportEvents 基类）
│   ├── stdio.py                   # 新增：StdioTransport（asyncio 子进程、进程组、
│   │                              #     stdin-close→SIGTERM→SIGKILL 级联、进程退出钩子）
│   ├── streamable_http.py          # 新增：StreamableHttpTransport（httpx 流式 POST/GET、
│   │                               #     手写 SSE 帧解析、指数退避重连+Last-Event-ID 续传、
│   │                               #     可注入 AuthProvider）
│   └── in_memory.py                 # 新增：InMemoryTransport + create_in_memory_transport_pair()
├── auth_provider.py                 # 新增：AuthProvider Protocol（token()/on_unauthorized()）
├── oauth/
│   ├── __init__.py
│   ├── types.py                      # 新增：OAuth 相关 dataclass + 结构校验 parse 函数
│   ├── discovery.py                    # 新增：WWW-Authenticate 解析、受保护资源/授权服务器
│   │                                   #     元数据发现（含 issuer 校验）
│   ├── flow.py                          # 新增：PKCE、授权 URL 构造、token 请求/刷新（含并发
│   │                                    #     401 共享单次刷新）、动态客户端注册、step-up 授权
│   ├── provider.py                       # 新增：MCPOAuthProvider（单个 server_url 的具体状态
│   │                                     #     持有者，凭据存储通过注入的 Store Protocol，对应
│   │                                     #     FR-012"调用方可注入凭据存储"）
│   ├── callback.py                        # 新增：回调等待原语（pending-Future keyed by state，
│   │                                      #     不是独立 HTTP 服务器，见 Decision 6）
│   └── errors.py                           # 新增：OAuthError 及子类、
│                                           #     MCPOAuthAuthorizationRequiredError
├── tools.py                   # 改：MCPTool 内部改为持有/复用一个 MCPClient（见 Decision 2），
│                               #     acall() 不再每次新建连接；_json_schema_to_parameters 不变
└── demo_server.py              # 不变（见 Decision 7），继续依赖官方 mcp SDK 扮演测试服务器角色

pyproject.toml                 # 改：`mcp>=2.3.0` 从 [project].dependencies 移到
                                # [dependency-groups].dev；httpx 提升为 [project].dependencies
                                # （不再只是 dev 依赖）

apps/api/
├── main.py                   # 改：两个探测路由（创建/刷新 MCP 服务器）改用 MCPClient 的"一次性
│                             #     连接"用法（构造→connect→list_tools→close）；新增一个 OAuth
│                             #     回调路由（FR-011，具体路径/方法留给 /speckit-tasks）
└── runtime.py                 # 改：_ensure_mcp_tools() 构造的 MCPTool 现在持有持久连接；新增
                                #     按 task_id 记录本次任务用到的 MCPTool 实例列表，evict()
                                #     清理时对每个实例调用关闭连接（复用已有的按 task_id 缓存+
                                #     evict() 清理模式，见 Decision 2，不引入新的生命周期概念）

tests/mcpclient/
├── test_protocol_core.py        # 新增：User Story 1 的协议核心测试（用内存传输驱动）
├── test_transports_stdio.py       # 新增：User Story 2 的 stdio 生命周期测试
├── test_transports_http.py         # 新增：User Story 3 的 Streamable HTTP 测试
├── test_content_conversion.py       # 新增：User Story 4 的 to_llm_content 测试
├── test_oauth.py                     # 新增：User Story 5 的 OAuth 子集测试
├── test_mcpclient_client.py            # 改：断言跟着 MCPClient 持久会话 API 调整（原有的
│                                      #     connect_and_list_tools/connect_and_call_tool
│                                      #     断言替换为 MCPClient(...).connect()/list_tools()/
│                                      #     call_tool()/close() 的等价场景）
└── test_mcpclient_tools.py              # 改：MCPTool.acall() 相关断言跟着内部实现调整（公开行
                                        #     为——返回值/outcome 状态——保持不变）

tests/apps/api/
└── test_api_routes.py 等                 # 改：跟着 MCP 服务器探测路由的实现细节调整（如果测试
                                          #     直接 mock 了 connect_and_list_tools，需要改成
                                          #     mock MCPClient 的等价入口）
```

**Structure Decision**: 单仓库多包结构不变。`packages/mcpclient` 内部从 3 个文件扩展为一个有子目
录的小包（`protocol/`/`transports/`/`oauth/` 三个子包），直接镜像 pi 参考实现的模块切分
（`src/protocol/`、`src/transports/`、`src/oauth/`），每个子模块对应一个 User Story 的交付范围，
不推平成一个大文件（宪法原则 IV + 既有的"文件保持短小聚焦"约定）。

## Complexity Tracking

> 无 Constitution 违规需要申诉；以下表格仅作说明性记录。

| 决策 | 为什么需要 | 更简单的替代方案被否决的原因 |
|------|-----------|-----------------------------|
| `packages/mcpclient` 内部拆成 `protocol/`/`transports/`/`oauth/` 三个子包（约 20 个文件）而非少数几个大文件 | 每个 User Story（协议核心/stdio/HTTP/内存传输+内容转换/OAuth）独立可测、独立交付，子包边界直接对应验收边界；OAuth 子集本身约占参考实现代码量的 43%，塞进一个文件会远超"文件保持短小聚焦"的既有约定 | 推平成 2-3 个大文件表面上"更简单"，但会让 OAuth（经确认为高风险、需要额外安全评审的代码）和协议核心混在一起，审查/定位问题更难，违反宪法原则 IV 的"可读性优先" |
| OAuth 回调用 `apps/api/runtime.py` 已有的 pending-Future 模式而非独立回调 HTTP 服务器 | `apps/api` 本身已经是常驻 Web 服务，`_pending_approvals` 已经验证过"状态机式等待一个外部 HTTP 请求到来并解析挂起的 Future"这个模式；复用现成的、已经过验证的机制 | pi 的 `OAuthCallbackServer`（独立 `node:http` 回调服务器）是为 pi 自己的 CLI 工具场景设计的——CLI 工具没有常驻 Web 服务，必须自己起一个临时服务器接收浏览器重定向；照搬到 `apps/api` 会多开一个端口/服务器实例，是不必要的架构错配，详见项目 memory `[[feedback_reference_project_renaming]]`（移植架构语义，不逐行照搬不适配目标运行环境的机制） |
