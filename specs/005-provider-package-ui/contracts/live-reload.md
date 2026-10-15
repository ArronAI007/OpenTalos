# Contract: 免重启生效机制（聊天 + Embedding）

对应 User Story 2/3 Acceptance Scenario 5-6（聊天）、Acceptance Scenario 2-3（embedding）、
FR-013、Clarifications Q2。

## 聊天：`apps/api/runtime.py`

```python
class ChatRuntime:
    def _resolve_chat_model_client(self) -> ModelClient:
        """查一次 provider_configs 表的激活 chat 配置；没有则回退现状的环境变量构造方式。"""
        ...

    async def _get_agent(self, task: dict[str, Any]) -> Agent:
        agent = self._agents.get(task["id"])
        if agent is not None:
            return agent
        model_client = self._resolve_chat_model_client()  # 每个新任务重新解析一次
        ...
```

## 行为契约

1. **已缓存任务不受影响**：`self._agents` 里已经存在的任务，`_get_agent()` 直接返回缓存的
   `Agent`，不重新解析配置、不重新构造 `ModelClient`。
2. **新任务读最新配置**：一个此前从未调用过 `_get_agent()` 的 `task_id`，构造 `Agent` 之前
   必须先查一次当前激活的 provider 配置。
3. **回退顺序**：没有激活配置 → 完整走 004 feature 的环境变量构造路径（`ModelClient()` 无参
   构造），不得抛出任何新异常、不得要求额外的环境变量。
4. **`ChatRuntime.model_name` 属性**：必须反映"如果现在构造一个新任务，会用哪个模型名"，不
   是某个过时的缓存值。

## Embedding：`packages/memory/semantic.py` + `apps/api/db.py`

```python
# packages/memory/semantic.py
class SemanticMemory:
    def __init__(self, path: Path, embedder: Callable[[], EmbeddingClient]) -> None: ...
    # 内部调用点：self._embedder().embed(text)
```

```python
# apps/api/db.py
def _resolve_embedding_client() -> EmbeddingClient:
    """查一次 provider_configs 表的激活 embedding 配置；没有则回退现状的环境变量构造方式。"""
    ...

class ChatStore:
    def __init__(self, path: Path, embedder: EmbeddingClient | None = None) -> None:
        ...
        embedder_factory = (lambda: embedder) if embedder is not None else _resolve_embedding_client
        self.semantic = SemanticMemory(self._path, embedder_factory)
```

## 行为契约

1. **每次调用都重新解析**：`SemanticMemory` 的每一次 `embed` 相关操作都通过
   `self._embedder()` 重新拿一个 `EmbeddingClient`，不缓存上一次的实例。
2. **显式注入优先**：测试/调用方通过 `ChatStore(..., embedder=...)` 显式传入一个具体实例时
   （现状测试的既有用法），行为保持不变——这个具体实例被包进一个永远返回它自己的工厂里，不
   会意外去查数据库。
3. **回退顺序**：没有激活的 embedding 配置 → 完整走现状的 `EMBED_MODEL_NAME`/
   `EMBED_API_KEY`/`EMBED_BASE_URL` 环境变量路径。

## 独立测试方式

- 聊天：构造 `ChatRuntime`，新增并激活一条配置，新建一个任务，断言其 `Agent` 持有的
  `ModelClient` 用了这条配置的字段；激活另一条配置后新建第二个任务，断言第二个任务用了新配
  置，第一个任务已缓存的 `Agent` 不受影响（无需重新验证——它根本不会再被重新解析）。
- Embedding：构造 `ChatStore`（不显式传 `embedder`），新增并激活一条 embedding 配置，触发一
  次 `semantic.store(...)`，断言底层 `EmbeddingClient` 使用了这条配置的字段；删除/取消激活
  后再触发一次，断言回退到环境变量配置（可以用 `monkeypatch.setenv` 验证具体取值）。
- 两个场景都要验证"没有任何配置时（全新数据库）"的默认行为和改动前完全一致。
