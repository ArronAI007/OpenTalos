# Phase 1 Data Model: packages/core 对齐 pi 的 agent-core 内核架构

所有类型都定义在 `packages/core` 内部（`protocol.py`/`protocols.py`，或 research.md 决策里提到的新
增小模块），延续 `001-core-isolation-selftest` 的风格：数据类型放 `protocol.py`，协作方契约
（`typing.Protocol`）放 `protocols.py`。字段名用 Python 惯用的 `snake_case`，不照抄 pi 的
`camelCase`。

## 新增数据类型（`packages/core/protocol.py` 或等价位置）

### EventKind（枚举）

```python
class EventKind(Enum):
    RUN_START = "run_start"
    RUN_END = "run_end"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    MESSAGE_START = "message_start"
    MESSAGE_UPDATE = "message_update"
    MESSAGE_END = "message_end"
    TOOL_EXECUTION_START = "tool_execution_start"
    TOOL_EXECUTION_UPDATE = "tool_execution_update"
    TOOL_EXECUTION_END = "tool_execution_end"
```

对应 FR-002。`AgentPhase`（现有的 `STARTED`/`FINISHED`/`FAILED`）被这个枚举取代；`FAILED` 状态折进
`RUN_END` 事件的 `data["status"]`，不单独设成员。

### AgentEvent（dataclass，`PhaseSignal` 的泛化）

| 字段 | 类型 | 说明 |
|------|------|------|
| `kind` | `EventKind` | 事件种类 |
| `timestamp` | `float` | `time.time()`，构造时自动填 |
| `agent_name` | `str` | 产生这个事件的 Agent 实例名字 |
| `data` | `dict[str, Any]` | 该事件种类特定的载荷，见下表 |

各 `kind` 对应的 `data` 载荷约定（非强制 schema，调用方按约定读取，保持 `PhaseSignal` 原有的"灵活
dict"风格而不是为每种事件定义一个独立 dataclass——十种事件各开一个类型会让 `agent_loop.py` 这层代
码膨胀，不符合宪法原则 IV）：

| `kind` | `data` 里应包含 |
|--------|----------------|
| `RUN_START` | `input_text` |
| `RUN_END` | `status`（`"completed"`\|`"failed"`\|`"cancelled"`）、成功时的 `result`、失败时的 `error`/`error_type` |
| `TURN_START`/`TURN_END` | `step`（第几轮） |
| `MESSAGE_START`/`MESSAGE_END` | `role`（`"system"`\|`"user"`\|`"assistant"`\|`"tool"`）、`content`（`MESSAGE_START` 时可能为空，助手消息要等流式结束才有完整内容） |
| `MESSAGE_UPDATE` | `role="assistant"`、`delta`（本次增量内容）、`delta_kind`（`"text"`\|`"reasoning"`，和 `on_text_delta`/`on_reasoning_delta` 转发的是同一份数据，用这个字段区分来源，供下游按原有的两种 SSE 事件类型分流） |
| `TOOL_EXECUTION_START` | `call_id`、`tool_name`、`arguments_json` |
| `TOOL_EXECUTION_UPDATE` | `call_id`、进度相关的任意附加信息（本次范围内工具都是一次性返回，暂不产生真正的"进度"更新，这个 kind 先占住位置，调用方可以不处理） |
| `TOOL_EXECUTION_END` | `call_id`、`tool_name`、`result`/`is_error`、`duration_ms` |

### QueueMode（枚举）

```python
class QueueMode(Enum):
    ONE_AT_A_TIME = "one-at-a-time"
    ALL = "all"
```

对应 FR-005。

### BeforeCallResult / AfterCallResult（dataclass）

| 类型 | 字段 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `BeforeCallResult` | `block` | `bool` | `False` | 是否拦截这次调用 |
| | `reason` | `str \| None` | `None` | 拦截时给模型看的错误文案；`block=False` 时忽略 |
| | `terminate` | `bool` | `False` | 建议这次调用处理完后把整批标记为"参与提前结束" |
| `AfterCallResult` | `content` | `str \| None` | `None` | 覆写最终内容；`None` 保留原值 |
| | `details` | `Any` | `None` | 附加结构化细节；`None` 保留原值 |
| | `is_error` | `bool \| None` | `None` | 覆写是否视为错误；`None` 保留原值 |
| | `terminate` | `bool` | `False` | 同上 |

对应 FR-009/FR-010/FR-012；fail-closed 行为（钩子自身抛异常）在 `resolve_tool_call` 内部转换成
`BeforeCallResult(block=True, reason=...)`，不新增专门的"钩子错误"类型。

### TurnDecision

```python
TurnDecision = Literal["continue", "end"] | None
```

对应 FR-011；`None` 表示"不表态，维持原调度"，不单独定义 `TurnContext` 以外的包装类型。

### TurnContext（dataclass）

| 字段 | 类型 | 说明 |
|------|------|------|
| `step` | `int` | 第几轮 |
| `completion` | `ToolCompletion` | 这一轮模型响应（已有类型，不新增） |
| `tool_results` | `list[dict[str, str]]` | 这一轮工具执行结果（已有的 `messages` 片段形状） |

对应 FR-011，供 `finish_turn` 钩子读取。

### RequestOverrides（dataclass）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `context` | `list[ChatMessage] \| None` | `None` | 替换这次/下一次请求用的历史；`None` 保留原值 |
| `model` | `ModelClient \| None` | `None` | 替换这次/下一次请求用的模型；`None` 保留原值 |
| `thinking_level` | `ThinkingLevel \| None` | `None` | 替换这次/下一次请求用的推理等级；`None` 保留原值 |

对应 FR-015/FR-016，`prepare_request`/`prepare_next_turn` 的共同返回类型。

### ThinkingLevel

```python
ThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"]
```

对应 FR-017/FR-018。

## 修改的既有类型

### `ChatMessage.role`（`packages/core/protocol.py`）

```python
# 改前
SpeakerRole = Literal["user", "assistant", "system", "tool", "summary"]

# 改后
SpeakerRole = str  # 放宽为开放字符串，让应用专属角色（如 "notification"）能塞进同一个历史列表
```

对应 FR-013；`_LLM_ROLES = frozenset({"user", "assistant", "system"})`（`packages/memory/
working.py`）作为过滤依据——`tool`/`summary` 两个特殊角色继续被 `build_messages()` 的专门分支处理，
不受这次放宽影响；不在 `_LLM_ROLES ∪ {"tool", "summary"}` 里的角色被 `build_messages()` 过滤掉，不
出现在最终发给模型的 `messages` 列表里。

### `ToolInfo`（`packages/core/protocols.py`）

新增字段：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `execution_mode` | `Literal["sequential", "parallel"] \| None` | `None` | `None` 表示不覆盖全局默认模式 |

对应 FR-008；`packages/tool/tool.py` 的 `Tool.__init__` 新增同名构造参数，结构性满足这个新字段。

### `SteerQueue`（`packages/core/protocols.py`）

```python
# 改前
class SteerQueue(Protocol):
    def drain(self) -> list[str]: ...
    def clear_interrupt(self) -> None: ...
    @property
    def interrupt_event(self) -> asyncio.Event: ...

# 改后
class SteerQueue(Protocol):
    def drain(self) -> list[str]: ...
```

对应 FR-006；`clear_interrupt()`/`interrupt_event` 两个成员整体删除。Follow-up 队列复用同一个
Protocol 形状（两个独立实例，各自管理自己的 `QueueMode`），不新增一个几乎一样的
`FollowUpQueue` Protocol——两者的调用方契约（"给我一批待注入的消息字符串"）完全相同，区别只在于
"什么时候被轮询"，那是调用方（`execute_model_step`）的编排逻辑，不是 Protocol 形状本身的差异。

### `ModelClient`（`packages/core/model.py`）

新增：

| 成员 | 类型 | 说明 |
|------|------|------|
| `thinking_level` | `ThinkingLevel`（运行期可读写的实例属性） | 默认 `"off"`；替代原来固定于构造期的 `reasoning_effort` 用法 |
| `thinking_budgets` | `dict[ThinkingLevel, int] \| None`（构造参数） | 每档自定义 token 预算；`None` 时用仓库内置默认表 |

`reasoning_effort` 构造参数保留（向后兼容现有脚本/`.env`），内部统一折算成等价的 `thinking_level`
初值，不再是请求参数拼装的唯一来源。

## 保持不变的既有类型

`ToolInvocation`/`ToolCompletion`/`Completion`/`StreamSummary`（`packages/core/protocol.py`）、
`ToolCallResult`（`packages/core/protocols.py`）、`HistoryStore`/`ToolExecutor`/`TraceRecorder`/
`MetricsSink`/`NullMetricsSink`/`TokenEstimator`/`OutputTrimmerLike`（`packages/core/protocols.py`）
——这些都不是本次改动对象，字段/方法签名不变。

## 关系图（文字版）

```
Agent (core.agent)
├── subscribe(listener) / _emit(event: AgentEvent)       # 决策 1
├── transform_context: Callable | None                    # 决策 6
└── arespond_with_callbacks(...)                          # 向后兼容包装，内部转发到事件总线

execute_model_step() / run_tool_turn() (core.agent_loop)
├── emit: Callable[[AgentEvent], Awaitable[None]] | None  # 决策 1，Agent._emit 绑定过来
├── steer: SteerQueue | None            → poll steering    # 决策 2
├── followup: SteerQueue | None         → poll follow-up   # 决策 2
├── tool_execution_mode: Literal[...]   → 并发/顺序批次执行 # 决策 3
├── before_tool_call / after_tool_call  → resolve_tool_call 内部调用，fail-closed  # 决策 4
├── finish_turn: Callable → TurnDecision                   # 决策 5
└── prepare_request / prepare_next_turn → RequestOverrides # 决策 7

ModelClient (core.model)
└── thinking_level（运行期可变）+ thinking_budgets（构造期映射表）  # 决策 8

ReActAgent (agents.react_agent)
├── 继承 Agent.subscribe()，接 apps/api/runtime.py 的事件处理器   # 决策 9
├── 删除 FINISH_TOOL_NAME/FINISH_TOOL_SCHEMA/_read_final_answer
└── 删除 ModelInterrupted 重试循环，_ReActSteerQueue 瘦身 + 新增 follow-up 版本
```
