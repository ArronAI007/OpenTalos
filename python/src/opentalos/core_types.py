"""对应 packages/core-types/src/index.ts —— 全仓库共享的数据类型和接口协议。"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, AsyncIterator, Callable, Literal, Protocol

from pydantic import BaseModel, Field


class TenantContext(BaseModel):
    tenant_id: str
    session_id: str


MessageRole = Literal["system", "user", "assistant", "tool"]


class ToolCall(BaseModel):
    id: str
    name: str
    input: Any


class Message(BaseModel):
    role: MessageRole
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    # Base64 data URI，仅可能出现在 user 消息上；不支持 vision 的 provider 直接忽略这个字段。
    images: list[str] | None = None


JSONSchema = dict[str, Any]


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: JSONSchema
    # 缺省（或 "function"）是普通的客户端执行工具；"builtin" 是 provider 托管的工具（比如 Kimi 的
    # $web_search）——provider 适配器只发送 name，不发送 description/input_schema。
    kind: Literal["function", "builtin"] | None = None
    # True 表示这个工具的结果需要人工审批后才能发给用户。只应该标在有真实、难以撤销副作用的工具上。
    dangerous: bool | None = None


class ToolResult(BaseModel):
    id: str
    output: Any
    is_error: bool | None = None


class Tool(Protocol):
    definition: ToolDefinition

    async def execute(self, input: Any, ctx: TenantContext) -> ToolResult: ...


class ToolRegistry(Protocol):
    def register(self, tool: Tool) -> None: ...
    def get(self, name: str) -> Tool | None: ...
    def list_definitions(self) -> list[ToolDefinition]: ...
    async def execute(self, call: ToolCall, ctx: TenantContext) -> ToolResult: ...


class ModelRequest(BaseModel):
    messages: list[Message]
    tools: list[ToolDefinition] | None = None
    response_schema: JSONSchema | None = None


class TextDeltaChunk(BaseModel):
    type: Literal["text_delta"]
    text_delta: str


class ReasoningDeltaChunk(BaseModel):
    type: Literal["reasoning_delta"]
    reasoning_delta: str


class ToolCallChunk(BaseModel):
    type: Literal["tool_call"]
    tool_call: ToolCall


class MessageStopChunk(BaseModel):
    type: Literal["message_stop"]


ModelResponseChunk = Annotated[
    TextDeltaChunk | ReasoningDeltaChunk | ToolCallChunk | MessageStopChunk,
    Field(discriminator="type"),
]


class ModelProvider(Protocol):
    def complete(
        self, request: ModelRequest, *, cancel_event: asyncio.Event | None = None
    ) -> AsyncIterator[ModelResponseChunk]: ...


class MemoryRecord(BaseModel):
    key: str
    value: Any
    score: float | None = None


class MemoryStore(Protocol):
    async def read(self, key: str, ctx: TenantContext) -> Any | None: ...
    async def write(self, key: str, value: Any, ctx: TenantContext) -> None: ...
    async def search(self, query: str, ctx: TenantContext) -> list[MemoryRecord]: ...


CheckpointStatus = Literal["running", "paused", "done", "failed"]


class Checkpoint(BaseModel):
    graph_id: str
    run_id: str
    tenant_id: str
    session_id: str
    # node_cursor/pending_yields 故意用 Any：CheckpointStore 要能被任何执行引擎使用，不只是
    # GraphEngine——具体引擎在自己内部把这两个字段转换成自己的游标类型。
    node_cursor: Any
    state: Any
    pending_yields: list[Any]
    status: CheckpointStatus
    created_at: str
    # 通过 CheckpointStore.request_cancel() 设置。只在模型调用正在流式输出时被 respond 节点尊重
    # ——工具执行期间或暂停等待审批期间收到的取消请求，要等到（如果有）下一次进入流式输出阶段才生效。
    cancel_requested: bool
    # 用户想接话插入当前正在生成的回复里的指令。单槽位，不是队列——第二次 steer 会覆盖第一次还没
    # 被消费的 steer。
    steer_message: str | None = None
    # worker 重试耗尽后放弃时设置的人类可读错误信息。只在 status == "failed" 时有意义。
    error: str | None = None


class CheckpointQuery(BaseModel):
    tenant_id: str | None = None
    session_id: str | None = None


class CheckpointStore(Protocol):
    # load/list_checkpoints/request_cancel/request_steer/clear_steer_message (the five methods
    # right below `save`) are the TRUSTED INTERNAL CALLER surface: they assume a DB connection
    # that is NOT subject to the Row-Level Security policies added for `checkpoints`/
    # `trace_events` (e.g. a superuser connection, or a role explicitly granted BYPASSRLS).
    # PostgresCheckpointStore's implementations of these five never call
    # `set_config('app.tenant_id', ...)`, so if they're called through an RLS-restricted
    # connection (e.g. authenticated as the `opentalos_app` role under `FORCE ROW LEVEL
    # SECURITY`), the policy's `current_setting('app.tenant_id', true)` is NULL and
    # `tenant_id = NULL` is never true -- every one of these methods silently sees/changes
    # nothing (e.g. `request_cancel()` becomes `UPDATE 0`) rather than raising an error. This
    # exactly mirrors the original TypeScript `store.ts`'s identical design. `save` itself is
    # NOT in this group -- it already sets `app.tenant_id` from the checkpoint's own tenant_id
    # as defense-in-depth (see PostgresCheckpointStore.save), so it works correctly under an
    # RLS-restricted connection. The `*_for_tenant` variants below are the correct surface for
    # request-driven/tenant-scoped callers -- they explicitly set `app.tenant_id` themselves.
    # Which DB role the worker actually connects as (and therefore whether the five plain
    # methods below are ever safe to call directly against a live database) is a real design
    # decision reserved for Phase 5 (scheduler+worker); it is deliberately NOT decided here.
    async def save(self, checkpoint: Checkpoint) -> None: ...
    async def load(self, run_id: str) -> Checkpoint | None: ...
    async def list_checkpoints(self, query: CheckpointQuery) -> list[Checkpoint]: ...
    # 只设置 cancel_requested，不动其它字段——刻意不走 save()，避免和并发执行中的 worker 自己的
    # save() 竞争（整行 upsert 谁后写谁赢，可能悄悄覆盖掉取消请求）。runId 不存在时静默无操作。
    async def request_cancel(self, run_id: str) -> None: ...
    # 只设置 steer_message，不动其它字段——和 request_cancel 同样的竞态规避理由。
    async def request_steer(self, run_id: str, message: str) -> None: ...
    # 把 steer_message 清回 None——worker 把待处理的消息真正投递进 run 之后立刻调用，避免下一次
    # 轮询重复投递。runId 不存在时静默无操作。
    async def clear_steer_message(self, run_id: str) -> None: ...

    # 以下四个是上面对应方法的租户限定版本，供任何由认证请求/任务驱动的调用点使用（而不是可信的
    # 内部系统代码）。和无限定版本并存而不是替换，这样现有大量测试代码不用改。Postgres 实现里，
    # 应用层按 tenant_id 过滤 + 数据库层 RLS 双重保险。runId 不存在或属于别的租户，两种情况效果
    # 一样（都当作不存在），这是设计使然，和 RLS 本身的行为一致。
    async def load_for_tenant(self, run_id: str, tenant_id: str) -> Checkpoint | None: ...
    async def request_cancel_for_tenant(self, run_id: str, tenant_id: str) -> None: ...
    async def request_steer_for_tenant(self, run_id: str, message: str, tenant_id: str) -> None: ...
    async def clear_steer_message_for_tenant(self, run_id: str, tenant_id: str) -> None: ...


TraceEventType = Literal[
    "node_enter",
    "node_exit",
    "llm_call_start",
    "llm_call_end",
    "llm_text_delta",
    "llm_reasoning_delta",
    "tool_call_start",
    "tool_call_end",
    "hitl_interrupt",
    "error",
]


class TraceEvent(BaseModel):
    type: TraceEventType
    run_id: str
    tenant_id: str
    session_id: str
    timestamp: str
    payload: dict[str, Any] | None = None


EventHandler = Callable[[TraceEvent], None]


class EventBus(Protocol):
    def emit(self, event: TraceEvent) -> None: ...
    def subscribe(self, handler: EventHandler) -> Callable[[], None]: ...
    # 等待目前为止所有 emit() 都已持久化。内存实现没什么好等的，直接 pass；Postgres 实现要等写入
    # 链跑完，这样调用方（图引擎落 checkpoint 前）能确保所有 trace 事件都已可见。
    async def flush(self) -> None: ...


GuardrailDecision = Literal["allow", "block", "require_approval"]


class GuardrailInput(BaseModel):
    node_id: str
    phase: Literal["before", "after"]
    state: Any
    ctx: TenantContext
    # 节点自己的返回值，只在 after 阶段有值（before 阶段是 None）。
    output: Any | None = None


class Guardrail(Protocol):
    async def check(self, input: GuardrailInput) -> GuardrailDecision: ...
