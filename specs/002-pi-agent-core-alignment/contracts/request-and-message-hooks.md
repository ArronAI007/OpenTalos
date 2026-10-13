# Contract: 消息分层 + `prepare_request`/`prepare_next_turn` + `thinking_level`

对应 FR-013/FR-014/FR-015/FR-016/FR-017/FR-018，User Story 5 + User Story 6 + User Story 7。实现
见 `research.md` 决策 6/7/8。

## 消息分层

- `ChatMessage.role`（`SpeakerRole`）从封闭 `Literal` 放宽为 `str`——任何字符串都是合法角色，校验
  收紧到"转换成 LLM 消息时过滤"这一步，而不是"构造消息时拒绝"。
- `_LLM_ROLES = frozenset({"user", "assistant", "system"})`（`packages/memory/working.py`
  内部常量，不对外导出）；`build_messages()`（即 FR-013 要求的"转换步骤"）的角色分支：
  - `role == "tool"` → 现有的 assistant(tool_calls)+tool 还原逻辑，不变。
  - `role == "summary"` → 现有的"派生成带前缀的 system 消息"逻辑，不变。
  - `role in _LLM_ROLES` → 透传 `{"role": message.role, "content": message.content}`，不变。
  - 其余（应用专属角色）→ **跳过，不追加进 `messages`**。这是本次唯一新增的分支。

```python
transform_context: Callable[[list[ChatMessage]], Awaitable[list[ChatMessage]]] | None
```

- 可选构造参数（`Agent`/`ReActAgent`）；在 `arespond()` 里拿到 `history_snapshot()` 之后、调用
  `build_messages()` 之前执行，返回值替代原始历史被传给 `build_messages()`。
- **异常处理**：`transform_context` 内部抛出异常时，吞掉异常、记一条 trace 事件（若有 recorder），
  改用未转换的原始历史继续——这是一个读取型预处理步骤，异常时的合理降级是"忽略这次转换"而不是像
  工具钩子那样 fail-closed 拒绝整轮运行。
- 未提供时（`None`），历史原样传递给 `build_messages()`（现状行为不变）。

## `prepare_request` / `prepare_next_turn`

```python
RequestOverrides = dataclass(
    context: list[ChatMessage] | None = None,
    model: ModelClient | None = None,
    thinking_level: ThinkingLevel | None = None,
)

prepare_request: Callable[[RequestContext], Awaitable[RequestOverrides | None]] | None
prepare_next_turn: Callable[[], Awaitable[RequestOverrides | None]] | None
```

- `prepare_request`：每一次 `execute_model_step` 发起模型调用之前调用一次（含第一次）；非 `None`
  字段替换这次（及之后，直到下一次 `prepare_request`/`prepare_next_turn` 再次覆盖）请求要用的
  值；不回溯影响已经发出的请求。
- `prepare_next_turn`：外层循环确定"继续下一步"之后、下一次 `execute_model_step` 调用之前调用一
  次；同样返回 `RequestOverrides`，可以额外追加需要先插入历史的消息（具体追加机制：返回值里
  `context` 字段若提供，直接替换即将使用的历史——调用方要追加消息就自己在 `context` 里拼好完整
  列表，不单独开一个"追加"字段，保持 `RequestOverrides` 这一个类型同时服务两个钩子）。
- 两者都未提供时（`None`/`None`），维持现有行为——模型/上下文从 Agent 构造时的值不变地延续。
- **优先级**：按时间顺序，后调用的覆写先调用的——`finish_turn` → `prepare_next_turn` →（下一轮的）
  `prepare_request`。这是时间线决定的天然顺序，不是任意选择，见 `research.md` 决策 7。

## `thinking_level` / `thinking_budgets`

```python
ThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"]

class ModelClient:
    thinking_level: ThinkingLevel  # 运行期可读写
    def __init__(self, ..., thinking_budgets: dict[ThinkingLevel, int] | None = None) -> None: ...
```

- `thinking_level` 是 `ModelClient` 实例的**可变属性**（不是构造后冻结的值），每次
  `_build_call_kwargs` 现读现用，运行期任意时刻修改立即对下一次请求生效，不需要重建 `ModelClient`。
- 按后端转译（`_build_call_kwargs` 内部）：
  - **OpenAI 兼容后端**：`off` → 不发送推理强度字段；`minimal`/`low` → `"low"`；`medium`/`high`
    → `"high"`；`xhigh`/`max` → `"max"`（降维映射到后端已支持的三个字面量，绝不发送新字符串）。
  - **Anthropic 后端**：`off` → 不启用 `thinking` 参数；其余六档 → `thinking: {"type": "enabled",
    "budget_tokens": thinking_budgets[level]}`。
- `reasoning_effort` 构造参数保留（向后兼容），内部折算成等价的 `thinking_level` 初值，不再是请求
  参数拼装的唯一来源。

## 验证要点

1. 历史里插入一条自定义角色消息：断言它出现在 `history_snapshot()` 里，但不出现在实际发给模型的
   `messages` 里。
2. `transform_context` 提供时：断言它的返回值（而非原始历史）被用于生成最终 `messages`；
   `transform_context` 内部抛异常时：断言运行不崩溃、改用原始历史继续。
3. `prepare_request` 在第二次请求把 `model` 换成另一个实例：断言第二次请求确实用新模型，第一次不
   受影响。
4. `thinking_level` 从 `"low"` 改成 `"off"`：断言下一次请求不再携带任何推理强度字段，等价于现状
   默认行为。
5. 自定义 `thinking_budgets`：断言 Anthropic 后端请求里的 `budget_tokens` 是这个自定义值。
