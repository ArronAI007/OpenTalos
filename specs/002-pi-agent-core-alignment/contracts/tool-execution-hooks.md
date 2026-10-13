# Contract: 工具执行模式 + `beforeToolCall`/`afterToolCall`

对应 FR-008/FR-009/FR-010/FR-012，User Story 3。实现见 `research.md` 决策 3、决策 4。

## 工具执行模式

```python
ToolExecutionMode = Literal["sequential", "parallel"]
```

- 全局默认通过 `Agent`/`ReActAgent` 构造参数 `tool_execution_mode: ToolExecutionMode = "parallel"`
  设置，一路透传到 `execute_model_step`。
- `ToolInfo.execution_mode: ToolExecutionMode | None = None`——`None` 表示这个工具不覆盖全局默认。
- 判定规则：这一批 `requested_tools` 里，只要有任意一个工具（经 `tool_registry.get(name)` 查到
  的）`execution_mode == "sequential"`，**整批**退化为顺序执行；否则按全局默认模式执行。

## `before_tool_call`

```python
BeforeCallResult = dataclass(block: bool = False, reason: str | None = None, terminate: bool = False)

before_tool_call: Callable[[ToolInvocation], Awaitable[BeforeCallResult]] | None
```

- 调用时机：`resolve_tool_call()` 里，参数 JSON 解析、审批检查（`requires_approval`）之后，真正执
  行工具（`tool_registry.acall`）之前。
- `block=True`：这次工具调用不会真正执行，返回给模型的 `content` 是 `reason`（未提供 `reason` 时
  用一个固定的默认文案，如 `"Blocked by beforeToolCall hook."`）。
- `block=False`：正常执行工具；`terminate` 字段仍然会被记录，供批次级 `terminate` 聚合使用（即使
  这次调用本身放行执行）。
- **钩子自身异常（fail-closed）**：`before_tool_call` 调用过程中抛出任何异常，等价于收到
  `BeforeCallResult(block=True, reason="beforeToolCall hook 自身出错：{异常信息}")`——不重新抛出，
  不静默放行。

## `after_tool_call`

```python
AfterCallResult = dataclass(
    content: str | None = None, details: Any = None, is_error: bool | None = None, terminate: bool = False,
)

after_tool_call: Callable[[ToolInvocation, ToolCallResult], Awaitable[AfterCallResult]] | None
```

- 调用时机：工具真正执行完毕（`tool_registry.acall` 返回）之后，结果被追加进 `messages` 之前。
- 字段覆写规则：`content`/`details`/`is_error` 非 `None` 时覆写对应字段，`None` 时保留工具原始执
  行结果——不是整体替换。
- **钩子自身异常（fail-closed）**：等价于 `AfterCallResult(content=None, is_error=True)`
  外加把最终返回给模型的 `content` 替换成一条标注"afterToolCall hook 自身出错"的错误文案（工具本
  身已经执行完毕，不能假装它没执行过，但最终呈现给模型的结果必须明确反映"这里出了问题"，不能静默
  放行原始结果）。

## `terminate` 聚合规则（FR-010）

这一批 `requested_tools`（可能大小为 1）里，每个调用最终携带的 `terminate` 标记（来自
`BeforeCallResult`/`AfterCallResult` 里非拦截即覆写路径下更晚生效的那个值）被收集成一个布尔列表；
**当且仅当这批非空且全部为 `True`** 时，这一步结束后运行提前结束（在 `finish_turn` 被调用之前，见
`queues-and-finish-turn.md`）。单个工具调用没有标记 `terminate` 或标记为 `False`，整批就不提前结
束，运行按正常流程继续到下一步。

## 验证要点

1. 一批 3 个工具里 1 个标记 `execution_mode="sequential"`：断言整批顺序执行（用一个共享列表记录
   开始/结束时间戳，断言没有重叠）。
2. 没有任何工具标记 `execution_mode`：断言仍然并发执行（现状行为不变）。
3. `before_tool_call` 返回 `block=True`：断言工具函数本身完全没有被调用（用一个 mock 断言调用计
   数为 0），模型收到的内容包含 `reason`。
4. `before_tool_call`/`after_tool_call` 内部抛异常：断言这次调用被当作拦截/错误处理，异常不向上
   传播、不打断整轮运行。
5. `after_tool_call` 只覆写 `details`：断言 `content`/`is_error` 保持工具原始执行结果。
6. 一批里只有部分调用标记 `terminate=True`：断言运行不提前结束，按正常流程继续。
