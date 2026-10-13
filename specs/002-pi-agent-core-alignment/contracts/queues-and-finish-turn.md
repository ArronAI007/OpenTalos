# Contract: Steering/Follow-up 轮询队列 + `finishTurn`

对应 FR-005/FR-006/FR-007/FR-010/FR-011，User Story 2 + User Story 4。实现见 `research.md` 决策
2、决策 5。

## `SteerQueue`（steering 与 follow-up 共用的 Protocol 形状）

```python
class SteerQueue(Protocol):
    def drain(self) -> list[str]: ...
```

- 调用方（`execute_model_step`）在"这次模型调用之前"调用一次 `drain()`，拿到的字符串按顺序追加成
  `{"role": "user", "content": ...}` 消息。
- **不存在**任何取消/打断正在进行中的模型调用或工具执行的机制——`interrupt_event`/
  `clear_interrupt()` 已从这个 Protocol 中彻底移除，`agent_loop.ModelInterrupted` 异常类同时删除。
- `QueueMode`（`ONE_AT_A_TIME`/`ALL`）是队列实现自己的内部状态，不是 `SteerQueue` Protocol 的一部
  分——`drain()` 的调用方不需要知道、也不应该关心这次调用具体吐出几条消息。

## 轮询时机

| 时机 | 轮询哪个队列 |
|------|-------------|
| 每一步 `execute_model_step` 发起模型调用之前（含第一步） | steering |
| 一步结束后发现没有 `requested_tools`、本来要停了 | 先 follow-up（steering 已经在本步开头轮询过，不重复轮询） |

Steering 和 follow-up 都有消息排队时，steering 天然优先——因为 follow-up 只有在"确定要停"的那一刻
才会被问到，而那个时间点已经晚于本步 steering 的轮询点。

## `finish_turn`

```python
TurnDecision = Literal["continue", "end"] | None

def finish_turn(context: TurnContext) -> Awaitable[TurnDecision]: ...
```

- **调用时机**：这一轮的 assistant 消息和全部工具结果都已经追加进 `messages` 之后，外层循环决定
  "继续下一步还是停"之前。
- **返回 `"end"`**：无条件停止，哪怕 `context.completion.requested_tools` 非空；不再轮询
  follow-up、不再发起下一次模型请求。
- **返回 `"continue"`**：哪怕这一步没有 `requested_tools`、follow-up 队列也是空的，仍然确保再发起
  恰好一次模型请求（不重复发起——如果 `requested_tools` 非空或 follow-up 注入了消息，本来就会继
  续，不因为这个返回值额外多发一次）。
- **返回 `None`**：维持现有调度（有 `requested_tools` 就继续，没有就走 follow-up 轮询，follow-up
  也空就停）。
- **不调用的情况**：这一轮的响应是 `OutputLimitError`/`EmptyModelResponse`（撞输出上限/完全空响
  应）——这两个异常在 `execute_model_step` 内部直接 `raise`，调用栈根本不会走到"决定是否继续"这一
  步，`finish_turn` 没有机会被调用、也没有机会覆盖这个硬性退出。

## 工具批次 `terminate` 与 `finish_turn` 的优先级

工具批次的 `terminate` 聚合（见 `tool-execution-hooks.md`）在 `finish_turn` 之前被检查——一旦这一
批所有被终结的调用都标记了 `terminate=True`，运行立即结束，不再调用 `finish_turn` 征询意见。

## `ReActAgent` 的集成方式

- 删除 `FINISH_TOOL_NAME`/`FINISH_TOOL_SCHEMA`/`_read_final_answer`/`finish_calls` 拦截。
- 不传 `finish_turn`（或传入的钩子返回 `None`）时，终止逻辑等价于"模型不再请求工具时直接把
  `completion.text` 当作最终答案"——这正是现有代码 `if not completion.requested_tools: answer =
  completion.text; break` 已经在做的事，取消 `finish` 工具后这条路径自然成为唯一的"正常结束"路径。
- `STEP_LIMIT_MESSAGE`（用光 `max_steps` 没有结束）的兜底逻辑不受这次改动影响，是独立于
  `finish_turn` 的预算耗尽处理。

## 验证要点

1. 工具调用执行期间排队一条 steering 消息：断言这次工具调用正常跑完（没有任何
   `asyncio.CancelledError`/`ModelInterrupted` 产生），消息在下一次模型请求前出现在 `messages`
   里。
2. 没有更多工具调用时排队一条 follow-up 消息：断言它被注入、运行多跑一轮。
3. `finish_turn` 返回 `"end"`：断言运行在那一轮之后立刻停止，不再调用模型。
4. `finish_turn` 返回 `"continue"` 但没有工具调用：断言确实又发起了一次模型请求。
