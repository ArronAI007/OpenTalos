# Contract: `packages/core` 的协作方接口

这是 `packages/core` 对外暴露的"你想接进 agent loop，就必须满足这些形状"的契约。完整的方法签名表
见 [data-model.md](../data-model.md)；这里只记录**调用方必须遵守的行为约定**（data-model.md 没覆盖
的部分）。

面向谁：`packages/agents`（当前唯一的 core 调用方，也是 `SteerQueue` 适配器的实际构造位置），
`apps/api/runtime.py`（构造 Agent 实例并驱动它，持有 `SteerQueue` 背后真正的 `asyncio.Queue`/
`asyncio.Event` 原始状态，但不直接构造或实现 `SteerQueue` 本身），以及未来任何想复用
`packages/core` agent loop 能力的新功能包。

## 总则

- `packages/core` 内部永远不会 `isinstance()` 检查这些 Protocol（它们是结构化类型，不是需要显式继
  承的基类）——调用方传入的对象只要方法签名/属性名对得上就能工作，不需要让 `WorkingMemory`/
  `ToolRegistry` 等具体类声明"实现了"某个 Protocol。
- 七类 Protocol 里，`TraceRecorder` 工厂、`MetricsSink`、`OutputTrimmerLike`、`SteerQueue` 允许不
  传（`None` / 默认空实现 / 不启用纠偏能力）；`HistoryStore`、`ToolExecutor`（当 agent 策略确实要
  用工具时）、`TokenEstimator` 是 agent loop 正常工作所必需的，不传会在构造时报错，而不是在运行中
  途才失败。

## SteerQueue

- `drain()` 必须是幂等地"取出并清空"——同一批消息不能被 `execute_model_step` 的下一次调用重复注
  入。
- `drain()`/`clear_interrupt()` 都必须是非阻塞的同步调用（不是 `async def`）——`execute_model_step`
  在发起模型调用之前同步调用它们，不应该因为这一步额外等待。
- `interrupt_event` 返回的必须是同一个底层 `asyncio.Event` 对象在整个运行期间被持续复用，不能每次
  访问都新建一个——否则"清除打断标记"和"等待下一次打断"会作用在两个不同的 Event 上，彼此感知不到。
- **实现位置**：`SteerQueue` 的具体实现是 `packages/agents/react_agent.py` 的 `_ReActSteerQueue`
  适配器类，不是 `apps/api/runtime.py` 的 `_LiveRun`。`_LiveRun` 只负责持有原始的
  `steer: asyncio.Queue[str]`/`steer_event: asyncio.Event`，依旧通过既有的 `drain_steer=`/
  `steer_event=` 两个独立 kwargs 传给 `ReActAgent.arespond()`；`_ReActSteerQueue` 在内部把这两个原
  始参数包成满足本 Protocol 的对象，再传给 `execute_model_step`。这样设计是因为 `drain()` 取出的消
  息还必须被记进 Agent 自己的 transcript（`record_message(...)`），这件事只有持有 Agent 实例的那
  一层能做，`_LiveRun` 不适合、也不需要直接实现这个 Protocol。

## HistoryStore

- 调用方必须保证同一个 `HistoryStore` 实例在一次完整对话（可能跨多个 HTTP 请求）里被复用，而不是
  每次请求都新建一个空的——否则历史会丢失。
- `restore(data)` 接收的 `data` 必须是此前同一个实现的 `snapshot()` 原样返回值；不同 `HistoryStore`
  实现之间不保证快照格式兼容。

## ToolExecutor

- `get(name)` 对未注册的工具名必须返回 `None`，不能抛异常——`agent_loop.py` 据此判断"这个工具是否
  需要审批"，`None` 会被当成"不需要审批、直接执行"处理。
- `acall(...)` 必须自己兜住执行过程中的异常并体现在返回的 `ToolCallResult.succeeded=False` 里，不
  能让异常直接从 `acall` 抛出到 `agent_loop.py`（`resolve_tool_call` 不会额外 try/except 包
  `acall` 本身）。

## TraceRecorder（工厂）

- `Agent` 持有的是一个**工厂函数**（`Callable[[], TraceRecorder]`），不是现成的实例——每一轮对话
  开始时（`begin_trace()`）都会调用一次工厂拿一个新的 recorder，对应"一轮运行一份 trace"的既有语
  义。工厂函数自己决定要不要真的创建底层资源（比如 `RunRecorder` 会在构造时就建目录、开文件）。

## MetricsSink

- `inc`/`observe` 必须是不抛异常的（观测性失败不应该打断 agent loop 主流程）；调用方如果用真实的
  `observability.metrics` 单例，这一点已经成立。

## TokenEstimator / OutputTrimmerLike

- 两者都是纯函数式的只读计算，不持有跨调用的状态要求（`TokenBudget` 内部虽然有缓存，但缓存是性能优
  化，不是语义要求的一部分）。
