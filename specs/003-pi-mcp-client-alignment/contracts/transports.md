# Contract: 传输层（`McpTransport` + stdio/HTTP/内存三种实现）

对应 User Story 2/3/4（前半：内存传输部分）、FR-003/FR-004/FR-005/FR-010、SC-004/SC-006/SC-008。

## 最小传输接口（`transports/base.py`）

```python
class McpTransport(Protocol):
    async def start(self) -> None: ...
    async def send(self, message: dict[str, Any], *, cancel_event: asyncio.Event | None = None) -> None: ...
    async def close(self) -> None: ...
    on_message: Callable[[dict[str, Any]], Awaitable[None]] | None
    on_error: Callable[[Exception], Awaitable[None]] | None
    on_close: Callable[[], Awaitable[None]] | None
```

三种实现都必须结构性满足这个 Protocol；`MCPClient` 本身只通过这个接口和传输交互，不感知消息来
自哪种传输（User Story 3 Acceptance Scenario 2 的字面要求）。

## StdioTransport（`transports/stdio.py`）

```python
class StdioTransport:
    def __init__(self, command: str, args: list[str], *, env: dict[str, str] | None = None) -> None: ...
```

1. `start()` 用 `asyncio.create_subprocess_exec(..., start_new_session=True)`（POSIX：新建进程组，
   等价于 pi 的 `detached: true`）启动子进程，开始一个后台任务逐行读取 stdout 解析 JSON-RPC 消
   息（单行超过 `DEFAULT_MAX_MESSAGE_BYTES`=16MB 时报错而不是无限增长内存），stderr 读入一个容
   量上限 64KB 的环形缓冲区。
2. `close()` 必须按顺序执行：(a) 关闭子进程 stdin，等待 `STDIN_CLOSE_GRACE_MS`（默认 500ms，受
   `close_timeout_ms` 封顶）；(b) 仍未退出则对整个进程组发 SIGTERM（POSIX：
   `os.killpg(os.getpgid(pid), signal.SIGTERM)`；Windows：`taskkill /T /F` 等效机制），等待
   `close_timeout_ms`（默认 2000ms）；(c) 仍未退出则发 SIGKILL（或 Windows 等效）。
3. 子进程自己拉起的孙进程（如 `npx`/`uvx` 包装器启动的真正服务进程）必须随进程组一起终止——验
   证方式是进程组而非单个 pid。
4. 宿主应用异常退出时，已启动但未正常 `close()` 的子进程不应变成孤儿——用 `atexit.register` 登
   记一个清理函数，遍历一个模块级 `set()` 记录的全部存活进程组 id，对仍存活的发 SIGTERM。

## StreamableHttpTransport（`transports/streamable_http.py`）

```python
class StreamableHttpTransport:
    def __init__(
        self, url: str, *, headers: dict[str, str] | None = None,
        auth_provider: AuthProvider | None = None,
    ) -> None: ...
```

1. `send()` 用 `httpx.AsyncClient` 发 `POST`（`Accept: application/json, text/event-stream`）；
   响应可能是 `application/json`（一次性读完）或 `text/event-stream`（逐事件解析，手写 SSE 帧解
   析器，不引入 SSE 专用第三方库，单事件大小有上限保护）。
2. 响应流在对应的响应到达前中断：自动重连（指数退避，初始延迟/最大延迟/最大重试次数对齐 pi
   的默认值），用上次收到的 SSE `id:` 字段作为 `Last-Event-ID` 请求头发 GET 续传，不丢失、不重
   复已经消费过的内容（SC-008）。
3. `initialize` 完成后开一个独立的、自行重连的 GET 流用于接收服务端主动推送（`405` 响应视为"服
   务端不提供 GET 流"，正常关闭不报错）。
4. 响应里带 `Mcp-Session-Id` 头时记录下来，后续所有请求都带上这个头。
5. 调用方配置的自定义请求头必须出现在每一次实际发出的 HTTP 请求里（User Story 3 Acceptance
   Scenario 3）。
6. 收到 401（或 403 + `insufficient_scope`）且构造时提供了 `auth_provider`：调用
   `auth_provider.on_unauthorized()` 一次后重试这次请求一次；仍失败则把错误原样抛给调用方（对
   应 `auth-provider.md`/OAuth 契约里"自动重试"的边界——重试失败是调用方该知道的真实失败）。

## InMemoryTransport（`transports/in_memory.py`）

```python
def create_in_memory_transport_pair() -> tuple[McpTransport, McpTransport]: ...
```

一对互相配对的传输，一端给 `MCPClient`，一端给测试写的假服务端 handler；`send()` 内部直接把消
息（深拷贝，避免共享可变状态导致的测试假阳性）投递给对端的 `on_message`，不涉及任何真实子进
程/网络 I/O。供 `protocol-core.md` 的全部独立测试使用。

## 独立测试方式

- stdio：启动一个故意忽略 SIGTERM、只在 SIGKILL 时退出的测试脚本，断言 `close()` 最终让它退
  出且耗时符合"宽限期+SIGTERM 等待期"的预期量级；启动一个会再拉起子进程的包装脚本，断言两层
  进程都消失（`ps`/`pgrep` 核实，不只是检查最外层 pid）。
- HTTP：一个测试用最小 ASGI/HTTP handler（不依赖真实公网），模拟"响应流写到一半断开连接"，断
  言客户端自动重连并用 `Last-Event-ID` 续传，最终拿到完整、不重复的内容。
- 内存：见 `protocol-core.md` 的独立测试方式。
