# Phase 1 Data Model: Agent Loop 核心边界隔离 + 真实模型自测

本功能不涉及业务数据实体；这里的"模型"指 `packages/core` 对外暴露的结构化契约——七类新增的
`typing.Protocol`（供 core 要求它的协作方满足；`ToolInfo`/`ToolCallResult` 是 `ToolExecutor` 的
附属数据类型，不单独计数）+ core 本来就拥有、保持不变的协议层类型。所有 Protocol 定义都放在新文件
`packages/core/protocols.py`。

## 新增 Protocol

### HistoryStore

替代现在 `Agent` 直接构造并持有的 `memory.WorkingMemory` 实例。

| 方法 | 签名 | 对应 `WorkingMemory` 现有方法 |
|------|------|-------------------------------|
| `append` | `(message: ChatMessage) -> None` | `append` |
| `messages` | `() -> list[ChatMessage]` | `messages` |
| `clear` | `() -> None` | `clear` |
| `compress` | `(summary: str) -> bool` | `compress` |
| `snapshot` | `() -> dict` | `snapshot` |
| `restore` | `(data: dict) -> None` | `restore` |
| `build_messages` | `(system_prompt: str \| None, user_text: str) -> list[dict]` | `build_messages` |
| `assemble` | `(user_query: str, *, transcript: list[ChatMessage], system_instructions: str \| None, extra_slices: list[ContextSlice] \| None) -> str` | **新增**透传方法（见 research.md 决策 5），转发给 `self.assembler.assemble(...)` |

`ChatMessage`/`ContextSlice` 这两个类型名只是方法签名里的类型标注；`ContextSlice` 本身仍然定义在
`context` 包里——`HistoryStore.assemble()` 的 `extra_slices` 参数类型标注用 `Any` 近似（避免 core
反过来 `import context.ContextSlice`），实际运行时由调用方传入真实的 `ContextSlice` 列表。

### ToolExecutor / ToolInfo

替代现在 `agent_loop.py` 直接类型标注的 `tool.registry.ToolRegistry`。

| 方法/属性 | 签名 |
|-----------|------|
| `ToolExecutor.get` | `(name: str) -> ToolInfo \| None` |
| `ToolExecutor.acall` | `(name: str, arguments: dict, *, call_id: str \| None = None) -> ToolCallResult`（见下） |
| `ToolExecutor.function_schemas` | `() -> list[dict]` |
| `ToolInfo.requires_approval` | `bool` 属性 |
| `ToolInfo.untrusted_output` | `bool` 属性 |
| `ToolCallResult.succeeded` | `bool` 属性 |
| `ToolCallResult.duration_ms` | `float` 属性 |
| `ToolCallResult.output` | `str` 属性 |

`tool.registry.ToolRegistry`/`tool.tool.Tool`/`tool.outcome.ToolOutcome` 三个具体类已经结构性满足
这三个 Protocol（字段名完全对应，参见 `packages/tool/registry.py`/`tool.py`/`outcome.py` 现有定
义），不需要改它们的代码。

### TraceRecorder

替代现在 `Agent.begin_trace()` 直接构造的 `observability.RunRecorder`。

| 方法 | 签名 | 对应 `RunRecorder` 现有方法 |
|------|------|------------------------------|
| `log_event` | `(event: str, payload: dict, step: int \| None = None) -> None` | `log_event` |
| `finalize` | `() -> dict` | `finalize` |

`Agent.__init__` 新增一个可选的 `trace_recorder_factory: Callable[[], TraceRecorder] | None` 参
数，取代原来的 `trace_dir: str | None`；`begin_trace()` 改成 `self.recorder =
self._trace_recorder_factory()`（工厂为空则整体是 no-op，行为与"未配置 trace_dir"完全等价）。

### MetricsSink

替代现在 `agent_loop.py` 直接调用的模块级 `observability.metrics` 单例。

| 方法 | 签名 |
|------|------|
| `inc` | `(name: str, *, labels: dict \| None = None, value: int = 1) -> None` |
| `observe` | `(name: str, value: float, *, labels: dict \| None = None) -> None` |

core 内部提供 `NullMetricsSink`（两个方法都是空实现）作为默认值；`execute_model_step`/
`resolve_tool_call` 新增 `metrics: MetricsSink = NullMetricsSink()` 参数。

### SteerQueue

替代现在 `packages/agents/react_agent.py` 的 `ReActAgent.arespond()` 自己手写的 `inject_steer()`
闭包——这部分能力原来不在 core 里（`/speckit-analyze` 发现的缺口，见 research.md 决策 5），现在正式
纳入 `execute_model_step` 的注入参数。

| 方法/属性 | 签名 |
|-----------|------|
| `drain` | `() -> list[str]`（取出所有待注入的纠偏/后续消息，原队列随之清空） |
| `clear_interrupt` | `() -> None`（清掉本轮的打断标记，供下一次模型调用前重置） |
| `interrupt_event` | `asyncio.Event` 属性（供 `_call_model` 的 `interrupt` 参数使用） |

`execute_model_step` 新增 `steer: SteerQueue | None = None` 参数：调用 `_call_model` 之前，若
`steer` 不为空，先 `drain()` 并把结果各自追加成一条 `{"role": "user", "content": ...}` 消息、调用
`clear_interrupt()`，并把这次调用的 `interrupt` 参数换成 `steer.interrupt_event`。

**实现时的修正**（`_LiveRun` 最终没有改动）：最初设想让 `apps/api/runtime.py` 的 `_LiveRun`
（已经持有 `steer: asyncio.Queue[str]`/`steer_event: asyncio.Event`）直接新增三个方法结构性满足
这个 Protocol，由 runtime.py 传 `steer=run`。实现 `packages/agents/react_agent.py` 时发现：
`drain()` 取出的纠偏消息除了要喂进这一次请求的 `messages` 列表，还必须被记进 Agent 自己的
transcript（`self.record_message(...)`）——这个记录动作只有 Agent 实例能做，`_LiveRun` 不持有、
也不该持有 Agent 引用。于是改为在 `react_agent.py` 内部定义一个 `_ReActSteerQueue` 适配器，包住
`arespond()` 本来就接收的 `drain_steer`/`steer_event` 两个原始参数，适配器的 `drain()` 在转发给原
始 `drain_steer()` 的同时顺手调用 `record_message`。`_LiveRun`/`apps/api/runtime.py` 因此不需要任
何改动，`ReActAgent.arespond()` 对外的 `drain_steer=`/`steer_event=` kwargs 契约也完全不变。

### TokenEstimator

替代现在 `Agent.__init__` 直接构造的 `context.TokenBudget`。

| 方法 | 签名 | 对应 `TokenBudget` 现有方法 |
|------|------|------------------------------|
| `estimate_messages` | `(messages: list[ChatMessage]) -> int` | `estimate_messages` |

### OutputTrimmerLike

替代现在 `agent_loop.py` 类型标注的 `context.OutputTrimmer`。

| 方法 | 签名 | 对应 `OutputTrimmer` 现有方法 |
|------|------|-------------------------------|
| `trim` | `(tool_name: str, output: str, metadata: dict \| None = None) -> TrimResult` | `trim` |

`TrimResult`（`.trimmed`/`.preview`/`.stats`/`.full_output_path`）保持是 `context` 包里定义的具体
dataclass——`agent_loop.py` 只在类型标注层面需要知道它的字段形状，不需要新增 Protocol 包一层（它本
身已经是一个简单的只读数据容器，不是"行为"）。为避免 core 反过来 `import context.TrimResult`，
`agent_loop.py` 对这个返回值只做属性访问（鸭子类型），不写死类型标注，或标注为局部定义的等价
`@dataclass`（二选一，留给 `/speckit-tasks` 阶段按实现时的便利性决定）。

## 保持不变的既有类型（`packages/core/protocol.py`）

这些类型本来就定义在 `packages/core` 内部，不受这次边界隔离影响：

- `ChatMessage`（pydantic `BaseModel`：`role`/`content`/`metadata` 等字段）
- `ToolInvocation`（`call_id`/`tool_name`/`arguments_json`）
- `ToolCompletion` / `Completion`（模型补全结果，含 `text`/`requested_tools`/`token_usage`/
  `finish_reason` 等）
- `StreamSummary`

## 保持不变的既有类型（`packages/core/agent.py`）

- `PhaseSignal` / `AgentPhase` / `PhaseCallback`（阶段性事件广播机制，本来就是 core 自己定义的纯
  Python 类型，不依赖任何其他 `packages/*` 目录，这次不需要改）

## 关系图（文字版）

```
packages/agents (ReActAgent.__init__) ──构造──> HistoryStore 实现 = memory.WorkingMemory 实例
                                       ──构造──> ToolExecutor 实现 = tool.registry.ToolRegistry 实例
                                       ──构造──> TraceRecorder 工厂 = lambda: observability.RunRecorder(...)
                                       ──构造──> MetricsSink 实现 = observability.metrics 单例
                                       ──构造──> TokenEstimator 实现 = context.TokenBudget 实例
                                       ──构造──> OutputTrimmerLike 实现 = context.OutputTrimmer 实例

apps/api/runtime.py (_LiveRun) ──drain_steer=/steer_event= 两个原始参数──>
    packages/agents/react_agent.py 的 _ReActSteerQueue 适配器（包装后满足 SteerQueue；
    _LiveRun 本身不需要改动，排队消息经适配器一并记入 Agent 自己的 transcript）

                    │ 以上全部作为构造/调用参数注入
                    ▼
        packages/core.Agent / agent_loop.py
                    │
                    ▼ 内部只认 Protocol 形状，不 import 任何一个具体包
```
