# Contract: 具名 Provider 注册表

对应 User Story 1、User Story 3、FR-001~FR-005/FR-009/FR-010、SC-001/SC-002。

## 公共入口

```python
# packages/core/providers.py
def get_provider_preset(name: str) -> ProviderPreset: ...  # 未注册名字抛 SettingsError
```

```python
# packages/core/model.py（改动后）
class ModelClient:
    def __init__(self, ..., provider: str | None = None, ...) -> None: ...
```

## 行为契约

1. **未知 provider 立刻报错**：`MODEL_PROVIDER`/构造参数 `provider` 不在注册表里时，
   `ModelClient.__init__` 必须在构造阶段（不是第一次发请求时）抛出 `SettingsError`，错误信息
   包含当前全部已注册的 provider 名字（按字母排序）。
2. **密钥解析优先级**：`api_key` 的最终取值必须严格按"显式构造参数 > 该 provider 的
   `api_key_env_var` 对应环境变量 > 通用 `MODEL_API_KEY` 环境变量"的顺序；`mock` provider 不
   受这条优先级影响，继续使用固定占位密钥。
3. **base_url 解析优先级**：`base_url` 的最终取值必须严格按"显式构造参数 > `MODEL_BASE_URL`
   环境变量 > 该 provider 的 `default_base_url`"的顺序。
4. **不回归**：`provider="anthropic"`/`"openai-compatible"`/`"mock"` 三者在这次改动前后的全
   部可观察行为（给定相同的构造参数/环境变量组合）必须完全一致——包括"只设置通用
   `MODEL_API_KEY`、不设置任何新引入的专属环境变量"这种现状部署方式。
5. **流式用量上报声明**：`preset.supports_stream_usage` 非 `None` 时，`OpenAICompatibleBackend`
   的首次流式请求必须直接采用这个声明值，不经历"先尝试带 `stream_options`、失败后才降级并记
   住"的现状反应式学习路径；为 `None` 的 provider（含现状 `openai-compatible`）继续保留反应式
   学习。
6. **reasoning 字段名覆盖**：`preset.reasoning_param_name` 非 `None` 时，请求体里承载推理强度
   的字段名使用这个值而不是字面量 `"reasoning_effort"`；为 `None` 时行为和现状完全一致。

## 独立测试方式

- 构造 `ModelClient(provider="no-such-provider", ...)`，断言抛出 `SettingsError` 且消息里包含
  `"anthropic"`等已注册名字。
- 用 `monkeypatch.setenv` 组合设置/不设置各环境变量（专属变量 vs 通用 `MODEL_API_KEY` vs 都设
  置），断言 `ModelClient.api_key`/`ModelClient.base_url` 的最终取值符合优先级契约。
- 用一个测试专属的合成 `ProviderPreset`（`supports_stream_usage=False`，不对应任何真实服务
  商，仅在测试里临时注册）构造 `OpenAICompatibleBackend`，断言首次流式请求的调用参数里没有
  `stream_options`。
- 复用现状 `tests/core/test_model.py` 里 `anthropic`/`openai-compatible`/`mock` 的既有测试用
  例，确认全部仍然通过（不回归）。
