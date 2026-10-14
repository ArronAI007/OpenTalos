# Quickstart: 验证"packages/mcpclient 对齐 pi 的独立 MCP 协议实现"

> 本文档在 `/speckit-plan` 阶段写出，描述实现完成后应该怎么验证；命令里引用的测试文件名/测试函
> 数名以 `/speckit-tasks` 最终产出的 `tasks.md` 为准（规划阶段按 Project Structure 的文件布局预
> 先起名，若实现时调整了命名，请同步更新这里，不要让这份文档和实际测试名脱节）。

## 前置条件

```bash
cd /Users/arron/Desktop/ArronAI/OpenTalos
.venv/bin/pytest --version   # 确认用的是项目虚拟环境，不是系统/anaconda 的 python
```

## 场景 1：协议核心——握手 + 分页 + 取消 + 服务端主动请求（User Story 1）

```bash
.venv/bin/pytest tests/mcpclient/test_protocol_core.py -v
```

预期：用 `InMemoryTransport` 驱动的测试全部通过——未连接时调用 `list_tools()`/`call_tool()` 抛
出明确异常；`list_tools()` 正确合并多页结果，遇到重复 `nextCursor` 报 `MCPProtocolError`；一次
等待中的 `call_tool()` 在 `cancel_event.set()` 后立刻以 `MCPAbortError` 结束，且服务端侧的假
handler 观察到 `notifications/cancelled`；服务端发起的 `ping` 请求被自动应答；超时+进度通知续
期的计时器行为符合预期；传输 `on_close` 触发后所有挂起请求以连接已关闭结束。

## 场景 2：stdio 传输——子进程生命周期级联关闭（User Story 2）

```bash
.venv/bin/pytest tests/mcpclient/test_transports_stdio.py -v
```

预期：对一个忽略 SIGTERM、只在 SIGKILL 时退出的测试脚本调用 `close()`，最终确实让它退出（验证
完整的 stdin 关闭→SIGTERM→SIGKILL 级联，可以用耗时量级粗略判断确实走完了三个阶段）；对一个会
再拉起子进程的包装脚本，关闭后用 `ps`/`pgrep` 核实两层进程都不在了。

## 场景 3：Streamable HTTP 传输——重连续传 + 自定义请求头（User Story 3）

```bash
.venv/bin/pytest tests/mcpclient/test_transports_http.py -v
```

预期：一个测试用最小 ASGI handler 模拟"响应流写到一半断开"，客户端自动重连并用
`Last-Event-ID` 续传，最终拿到完整内容（对应 SC-008）；自定义请求头出现在实际发出的 HTTP 请求
里；405 响应（服务端不提供 GET 流）被正常处理，不报错。

## 场景 4：内存传输 + 工具结果转换（User Story 4）

```bash
.venv/bin/pytest tests/mcpclient/test_content_conversion.py -v
```

预期：纯文本 `CallToolResult` 转换结果和现状行为等价（不回归）；包含图片/嵌入资源的结果被正确
解包成对应的 `LlmContent` 成员；只有 `structuredContent` 的结果转成它的 JSON 文本而不是空字符
串；`MCPTool.acall()` 对图片内容压平出的最终字符串里能看到可读的 `mime_type` 占位符，看不到
Python 对象 repr 的典型特征（`<`/`0x` 地址）。

## 场景 5：OAuth 子集——PKCE 流程 + 并发 401 去重（User Story 5）

```bash
.venv/bin/pytest tests/mcpclient/test_oauth.py -v
```

预期：对假授权服务器端点跑通完整 PKCE 换 token 流程；5 个并发请求同时收到 401 时，底层只发出
一次真正的刷新请求；`issuer` 不匹配/不安全 URL scheme 的发现响应被拒绝。

## 场景 6：持久会话 + 真实消费方（FR-009、SC-002、SC-006，真机）

```bash
.venv/bin/pytest tests/mcpclient/test_mcpclient_client.py tests/mcpclient/test_mcpclient_tools.py -v
```

预期：对 `demo_server.py`（stdio 和 HTTP 两种模式）的真机测试全部通过；`MCPTool` 在同一个任务
内被连续 `acall()` 多次时，只建立一次底层连接（可以通过给 `MCPClient.connect()` 打点计数断
言，或者观察子进程只被 spawn 一次）。

```bash
.venv/bin/pytest tests/apps/api/test_api_routes.py -k mcp -v
```

预期："创建/刷新 MCP 服务器"两条路由继续可用，行为与对齐前一致（SC-002）。

## 场景 7：依赖边界（SC-001）

```bash
grep -n '"mcp' pyproject.toml
grep -rn "^import mcp$\|^from mcp\." packages/mcpclient/client.py packages/mcpclient/tools.py packages/mcpclient/protocol packages/mcpclient/transports packages/mcpclient/oauth
```

预期：第一条命令显示 `mcp>=2.3.0` 出现在 `[dependency-groups].dev` 下，不在 `[project].dependencies`
下；第二条命令只有 `demo_server.py`（不在搜索范围内）依赖官方 `mcp` 包，`packages/mcpclient` 自
身的协议/传输/工具代码零匹配。

## 场景 8：全量回归

```bash
.venv/bin/pytest
.venv/bin/python scripts/check_core_boundary.py
```

预期：全量测试通过，测试数相比对齐前只增不减（新增 User Story 1-5 的测试，2 个现有真机测试文件
的断言调整但不减少覆盖面）；`packages/core` 边界检查器保持零违规（这次改动不涉及 `packages/
core`，理应天然通过，列在这里是确认没有意外波及）。
