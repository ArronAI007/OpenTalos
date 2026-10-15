# Contract: `packages/core` 与 `packages/ai` 的边界

对应 User Story 1、FR-001~FR-005、SC-001/SC-002。

## 公共契约

```python
# packages/core/protocols.py
@runtime_checkable
class ModelClientProtocol(Protocol):
    model_name: str
    last_stream_summary: Any | None
    async def acomplete(self, messages: list[dict], **kwargs: Any) -> Completion: ...
    async def astream(self, messages: list[dict], **kwargs: Any) -> AsyncIterator[str]: ...
    async def acomplete_with_tools(self, messages: list[dict], tools: list[dict], **kwargs: Any) -> ToolCompletion: ...
    async def astream_with_tools(
        self, messages: list[dict], tools: list[dict], *,
        on_text_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> ToolCompletion: ...
```

```python
# packages/ai/model.py（原 packages/core/model.py 原样搬入）
class ModelClient:
    ...  # 结构性满足 ModelClientProtocol，不显式继承
```

## 行为契约

1. **边界零违规**：`scripts/check_core_boundary.py packages/core` 在这次改动后必须报告零违
   规——`packages/core` 下任何文件的顶层 import 不能指向 `packages/ai`。
2. **类型标注改变，行为不变**：`packages/core/agent.py`/`agent_loop.py` 的 `model_client`
   参数类型标注从 `ModelClient`（具体类）改成 `ModelClientProtocol`；这是纯类型层面的改动，
   运行时行为（传入什么对象、调用什么方法）必须完全不变。
3. **结构性满足，不需要适配器**：把 `packages/ai.model.ModelClient` 的实例直接传给
   `packages/core` 的 `Agent`/`execute_model_step` 等既有接口，不需要任何包装类——
   `ModelClient` 已有的 6 个公开成员原样满足 Protocol。
4. **004 feature 行为逐字不变**：搬移后，具名 provider 自动密钥/base_url 解析、未注册名字报
   错、模型能力目录查询、压缩阈值自动默认值、声明式请求参数怪癖——全部行为必须和搬移前完全
   一致，唯一允许的变化是 import 路径。

## 独立测试方式

- 运行 `.venv/bin/python scripts/check_core_boundary.py`，断言 `packages/core` 零违规。
- 对 `packages/core/agent_loop.py` 的 `execute_model_step` 等函数，用一个只结构性满足
  `ModelClientProtocol`（不是真正的 `ModelClient` 子类、甚至不在同一个模块定义）的假对象调
  用，断言类型检查（mypy/pyright，如果本仓库配置了）和运行时行为都正常——证明确实是结构化类
  型而不是意外地要求具体类。
- 004 feature 的全部现状测试（`test_model.py`/`test_providers.py`/`test_model_catalog.py`）
  原样搬到新目录、只改 import 路径后重新运行，必须全部通过。
