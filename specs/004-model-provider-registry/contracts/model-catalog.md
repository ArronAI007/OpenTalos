# Contract: 模型能力目录 + 压缩阈值默认值接入

对应 User Story 2、FR-006~FR-008、SC-003/SC-004。

## 公共入口

```python
# packages/core/model_catalog.py
def get_model_capabilities(model_name: str) -> ModelCapabilities | None: ...
def default_compaction_token_limit(model_name: str) -> int: ...  # 永远返回可用的 int
```

```python
# apps/api/runtime.py（改动后，_get_agent() 内部）
effective_limit = self._compaction_token_limit
if effective_limit is None:
    effective_limit = default_compaction_token_limit(self._client().model_name)
```

## 行为契约

1. **已知模型返回完整数据**：`get_model_capabilities(model_name)` 对目录里登记过的模型名，必
   须返回包含 `context_window`/`supports_tools`/`supports_thinking` 三个字段的完整
   `ModelCapabilities` 实例。
2. **未知模型返回 `None`，不编造**：对目录里没有的模型名，必须返回 `None`，不能返回一个"猜
   测"出来的 `ModelCapabilities`（比如全部字段猜 `False`/0）。
3. **目录不含价格**：`ModelCapabilities` 的字段集合里不得出现任何价格/成本相关字段；
   `packages/core/pricing.py` 的 `load_prices()`/`estimate_cost()` 行为必须保持逐字不变，且
   这个模块不 import `model_catalog.py`，反之亦然。
4. **压缩阈值默认值**：`apps/api/runtime.py` 的 `_get_agent()` 在 `self._compaction_token_limit
   is None` 时，必须用 `default_compaction_token_limit(self._client().model_name)` 得到一个
   非 `None` 的默认值再传给 `build_agent`；`self._compaction_token_limit` 非 `None`（调用方显
   式提供，或 `apps/api/main.py` 透传了显式设置的 `COMPACTION_TOKEN_LIMIT` 环境变量）时，这个
   显式值必须原样生效，不被目录数据覆盖。
5. **未知模型的默认值不变**：`default_compaction_token_limit` 对目录里没有的模型名，必须返回
   和改动前 `apps/api/main.py` 硬编码默认值完全相同的数字（16000），保证现状部署在模型未登记
   进目录时默认行为不变。
6. **`apps/api/main.py` 的一行改动**：`COMPACTION_TOKEN_LIMIT` 环境变量未设置时，传给
   `ChatRuntime` 的 `compaction_token_limit` 必须是 `None`（不是硬编码字面量），把默认值判断权
   交给 `runtime.py`；环境变量显式设置时，继续原样解析成 `int` 并透传（不变）。

## 独立测试方式

- 对一个目录里登记过的模型名查询能力，断言三个字段都有合理取值；对一个随机未登记的模型名查
  询，断言返回 `None`。
- 构造 `ChatRuntime` 不传 `compaction_token_limit`、`model_client` 的 `model_name` 命中目录，
  触发一次 `_get_agent()`，断言实际构造出的 `Agent.compaction_token_limit` 等于
  `int(该模型 context_window * 0.5)`。
- 同样场景但 `model_name` 不在目录里，断言 `Agent.compaction_token_limit == 16000`（不回归）。
- 构造时显式传 `compaction_token_limit=5000`，断言最终生效值是 `5000`，不被目录覆盖。
- `apps/api/main.py` 层面：设置/不设置 `COMPACTION_TOKEN_LIMIT` 环境变量两种情况下调用
  `create_app()`，断言构造出的默认 `ChatRuntime` 实例的 `_compaction_token_limit` 符合契约第 6
  条。
