# Phase 1 Data Model: 对齐 pi 的统一模型 Provider 功能

所有类型都是 `packages/core` 内部的新增 `dataclass`，字段名用 Python 惯用的 `snake_case`。延续
`001-core-isolation-selftest`/`002`/`003` 的风格：数据类型 + 校验规则在同一个文件里就近定义。

## `packages/core/providers.py`

### ProviderPreset（dataclass，frozen）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | — | provider 注册表的 key（同时也是 `MODEL_PROVIDER` 环境变量/构造参数的合法取值） |
| `default_base_url` | `str \| None` | — | `None` 表示没有预置默认值，沿用 SDK 自己的默认端点（`anthropic`）或要求调用方必须自己提供（`openai-compatible`） |
| `api_key_env_var` | `str \| None` | — | 这个 provider 专属的密钥环境变量名；`None` 表示不自动解析专属变量（`mock`/现状 `openai-compatible`） |
| `supports_stream_usage` | `bool \| None` | — | `None` = 沿用现状反应式学习；`True`/`False` = 声明式，首次请求就生效，不经历"先失败一次" |
| `backend` | `Literal["anthropic", "openai-compatible", "mock"]` | — | 决定 `create_model_backend` 实例化哪个后端类 |
| `reasoning_param_name` | `str \| None` | `None` | `None` 时请求体用现状的 `"reasoning_effort"` 字段名；非 `None` 时用这个名字承载推理强度参数 |

**校验规则**：`_REGISTRY` 是模块级常量字典，构造 `ModelClient` 时查询
`get_provider_preset(name: str) -> ProviderPreset`；`name` 不在 `_REGISTRY` 里时抛
`SettingsError(f'Unknown MODEL_PROVIDER "{name}". Supported: {", ".join(sorted(_REGISTRY))}.')`
（对应 FR-005、宪法原则 III——系统边界输入必须在进入业务逻辑前完成校验并给出清晰错误）。

**首批注册表内容**（对应 research.md 决策 2，完整表格见该文档）：`anthropic`、`openai`、
`deepseek`、`moonshot`、`openai-compatible`、`mock`，共 6 条。

## `packages/core/model_catalog.py`

### ModelCapabilities（dataclass，frozen）

| 字段 | 类型 | 说明 |
|------|------|------|
| `context_window` | `int` | 该模型的上下文窗口大小（token 数） |
| `supports_tools` | `bool` | 是否支持工具调用（function calling） |
| `supports_thinking` | `bool` | 是否支持 thinking/reasoning |

不含任何价格/成本字段——这是和 `pricing.py` 的 `dict[str, dict[str, float]]` 价目表刻意保持独
立的两套数据（FR-007、Clarifications Q2）。

**校验规则**：`_CATALOG: dict[str, ModelCapabilities]` 是模块级常量字典，key 是精确的
`model_name` 字符串（和 `pricing.py` 的 `MODEL_PRICES` 用同样的 key 约定，保持一致性）。

```python
def get_model_capabilities(model_name: str) -> ModelCapabilities | None:
    return _CATALOG.get(model_name)
```

查询一个不在 `_CATALOG` 里的模型名，返回 `None`——不编造、不猜测（FR-006、Edge Cases）。调用方
（如 `default_compaction_token_limit`）必须显式处理 `None` 这个"不知道"的信号，不能把它当成某
个具体的布尔/数值取值误用。

### default_compaction_token_limit（纯函数，不是数据类型，但是这个模块对外的关键行为契约）

```python
_LEGACY_DEFAULT_COMPACTION_TOKEN_LIMIT = 16000

def default_compaction_token_limit(model_name: str) -> int:
    """保证返回一个可用的 int，不是 Optional——模型未知时回退到改动前 apps/api/main.py 的
    硬编码默认值（16000），保证这次改动不会让任何现状部署的默认压缩阈值发生变化（FR-010）。
    模型已知时用上下文窗口的一半作为压缩阈值（给摘要/新一轮工具调用/模型输出留出余量）。"""
```

对应 FR-008、Clarifications Q3、research.md 决策 5。

## 持久化边界（不变）

本次不涉及任何数据库 schema 变更——注册表和能力目录都是进程内静态数据，`apps/api/db.py` 不受
影响；`.env.example` 需要新增几行说明新的具名 provider 专属环境变量名（文档性质的改动，不是
schema）。
