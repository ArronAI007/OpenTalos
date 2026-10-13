# Contract: 事件总线（`Agent.subscribe`/`AgentEvent`）

对应 FR-001/FR-002/FR-003，User Story 1。实现见 `research.md` 决策 1、`data-model.md` 的
`AgentEvent`/`EventKind`。

## `Agent.subscribe`

```python
def subscribe(self, listener: Callable[[AgentEvent], Awaitable[None]]) -> Callable[[], None]: ...
```

- **参数**：`listener` —— 收到每个 `AgentEvent` 时被 `await` 一次的异步回调。
- **返回值**：取消订阅函数；调用后 `listener` 不再被通知，已经在飞的一次 `_emit` 调用不受影响（不
  保证"调用瞬间"的原子性，只保证"调用之后发生的事件"不再通知它）。
- **顺序语义**：多个监听器按 `subscribe()` 调用的先后顺序被依次 `await`（不是并发 `gather`）——
  前一个监听器跑完才轮到下一个。
- **错误处理**：单个监听器抛出的异常被吞掉，不传播、不打断其余监听器或 Agent 主流程（延续
  `_notify()` 现有的"回调故障不应该打断主流程"策略）。不设超时（与 FR-003 冲突，见下）。

## `_emit`（内部方法，不对外导出）

- 每次状态变化时调用，构造一个 `AgentEvent` 并依次 `await` 全部已订阅的监听器。

## FR-003 的具体约束

- `RUN_END` 必须是这次运行发出的最后一个 `AgentEvent`——`_emit(RUN_END 事件)` 之后不得再调用
  `_emit` 产生任何其他事件。
- 调用方若需要"这次运行彻底空闲"的信号，必须等 `subscribe()` 传入的 `listener` 在收到 `RUN_END`
  事件后自己的 `await` 完全返回，而不是看到 `RUN_END` 事件本身就假定运行已经空闲——`_emit` 的调
  用者（`Agent` 内部）会等所有监听器跑完 `RUN_END` 对应的那次分发才真正让 `arespond`/`arespond_
  with_callbacks` 返回。

## `arespond_with_callbacks` 的向后兼容行为

```python
async def arespond_with_callbacks(
    self, input_text: str,
    on_start: PhaseCallback = None, on_finish: PhaseCallback = None, on_error: PhaseCallback = None,
    **kwargs: object,
) -> str: ...
```

签名不变；内部实现改为：若 `on_start`/`on_finish`/`on_error` 任一不为 `None`，构造一个临时监听器
订阅事件总线，收到 `RUN_START` 转调 `on_start`、收到 `RUN_END` 按 `status` 字段转调 `on_finish`
（`completed`）或 `on_error`（`failed`），方法返回前取消订阅。这是一个**薄兼容层**，不是这次范围
里要求任何调用方必须迁移到的新 API——但 FR-019 要求 `apps/api/runtime.py` 实际迁移到直接用
`subscribe()`（见 `research.md` 决策 9），所以这层兼容在交付时不会有真实生产调用方在用，只作为公
共 API 的非破坏性保证存在。

## 验证要点（供 quickstart.md / tasks.md 引用）

1. 纯文本问答（无工具调用）的事件序列恰好是：`RUN_START → TURN_START → MESSAGE_START(user) →
   MESSAGE_END(user) → MESSAGE_START(assistant) → MESSAGE_UPDATE(assistant)* →
   MESSAGE_END(assistant) → TURN_END → RUN_END`。
2. 触发工具调用的运行里，`TOOL_EXECUTION_START`/`TOOL_EXECUTION_END` 成对出现，且携带的
   `call_id` 能和对应的 `MESSAGE_*` 事件、日志中的工具调用对应上。
3. 两个监听器订阅同一次运行：用一个共享列表记录各自收到事件的顺序，断言监听器 A 的某个事件处理
   完全结束后，监听器 B 才开始处理同一个事件（而不是两者交错）。
