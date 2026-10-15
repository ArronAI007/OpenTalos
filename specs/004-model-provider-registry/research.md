# Phase 0 Research: 对齐 pi 的统一模型 Provider 功能

本次调研基于对真实代码的阅读（`packages/core/{model.py,pricing.py,agent.py,compaction.py}`、
`apps/api/{main.py,runtime.py}`、`tests/core/test_model.py`、`.env.example`）和对
`earendil-works/pi` `packages/ai` 关键文件的阅读（`src/providers/all.ts`、
`src/providers/compat-schema.ts`、`src/model-catalog.ts`、`src/auth/resolve.ts`、
`src/env-api-keys.ts`），不是对 spec.md 的转述。

## 决策 1：具名 provider 注册表的具体形状和落地位置

**决策**：新增 `packages/core/providers.py`，定义：

```python
@dataclass(frozen=True)
class ProviderPreset:
    name: str
    default_base_url: str | None      # None 表示用 SDK 自己的默认值（如 Anthropic 官方端点）
    api_key_env_var: str | None        # None 表示不自动解析（如 mock）
    supports_stream_usage: bool | None # None = 沿用现状的反应式学习；True/False = 声明式，跳过学习
    backend: str                       # "anthropic" | "openai-compatible" | "mock"（决定实例化哪个后端类）
    reasoning_param_name: str | None = None  # None = 沿用现状的 "reasoning_effort" 字段名；
                                              # 非 None 时请求体改用这个字段名承载推理强度
                                              # （FR-001 的"可选覆盖"——首批全部留空，见决策 7）
```

一个模块级 `_REGISTRY: dict[str, ProviderPreset]` + `get_provider_preset(name: str) ->
ProviderPreset`（未注册名字抛 `SettingsError`，错误信息列出 `sorted(_REGISTRY)` 全部可用名
字，满足 FR-005）。`ModelClient.__init__` 在解析 `api_key`/`base_url` 之前先查一次这个注册
表；`create_model_backend` 不再是硬编码的 `if provider == "anthropic": ... elif ...`，而是
`preset = get_provider_preset(provider); return _BACKEND_CLASSES[preset.backend](...)`。

对应 FR-001/FR-002/FR-005。

**备选方案**：把注册表数据直接塞进 `model.py` 的一个字典常量，不单开文件。被否决——
`model.py` 现状已经 739 行，接近宪法"文件保持短小聚焦（最多 800 行）"的上限，新增一个独立文
件更符合"职责单一"的既有约定（这次新增的两个文件都遵循同样的理由，见 plan.md 的 Complexity
Tracking）。

## 决策 2：首批具名 provider 的真实默认值（不是占位符）

**决策**：首批新增 4 个具名 provider（加上保留不变的 `anthropic`/`openai-compatible`/`mock`，
共 7 个注册表条目）：

| provider 名 | default_base_url | api_key_env_var | backend |
|---|---|---|---|
| `anthropic`（现状，迁移进注册表） | `None`（Anthropic SDK 自己的默认端点） | `ANTHROPIC_API_KEY` | `anthropic` |
| `openai`（新增） | `None`（OpenAI SDK 自己的默认端点 `https://api.openai.com/v1`） | `OPENAI_API_KEY` | `openai-compatible` |
| `deepseek`（新增） | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` | `openai-compatible` |
| `moonshot`（新增，对应 `.env.example` 注释提到的 kimi-k3） | `https://api.moonshot.cn/v1` | `MOONSHOT_API_KEY` | `openai-compatible` |
| `openai-compatible`（现状，不变） | `None`（必须调用方自己提供 `MODEL_BASE_URL`） | 无（继续走通用 `MODEL_API_KEY`） | `openai-compatible` |
| `mock`（现状，不变） | `None` | 无（固定占位密钥） | `mock` |

这些 base_url 是各服务商公开文档记录的真实默认端点，不是占位猜测；`anthropic`/
`openai-compatible`/`mock` 三条現状条目的 `default_base_url`/`api_key_env_var` 字段取值刻意保
持"等价于现状行为"（`anthropic` 现状本来就没有自定义 base_url 默认值，这次只是把它也纳入注册
表统一管理，不改变任何实际解析结果）。

对应 FR-002。

**备选方案**：覆盖 pi 的全部约 40 个 provider。被否决——spec.md 的 Assumptions 已经明确排除，
这里不再复述。

## 决策 3：API 密钥解析优先级的具体实现

**决策**：`ModelClient.__init__` 现状这一行：

```python
self.api_key = api_key or os.getenv("MODEL_API_KEY")
```

改成：

```python
preset = get_provider_preset(self.provider)
self.api_key = (
    api_key
    or (os.getenv(preset.api_key_env_var) if preset.api_key_env_var else None)
    or os.getenv("MODEL_API_KEY")
)
```

`mock` 的 `api_key_env_var` 是 `None`，所以这条链不影响 `mock` 现状"固定占位密钥"的分支（那个
分支在更早的 if `self.provider == "mock"` 里单独处理，优先级更高，不受这次改动影响）。
`base_url` 同理：`self.base_url = base_url or os.getenv("MODEL_BASE_URL") or
preset.default_base_url`（现状 `anthropic`/`openai-compatible` 都没有 `default_base_url`，这
个新增的第三优先级分支对它们是 no-op，行为不变）。

对应 FR-003/FR-004、Clarifications Q1、Edge Cases 第一条。

## 决策 4：模型能力目录的形状、数据来源、以及"不知道"的表达方式

**决策**：新增 `packages/core/model_catalog.py`：

```python
@dataclass(frozen=True)
class ModelCapabilities:
    context_window: int
    supports_tools: bool
    supports_thinking: bool

_CATALOG: dict[str, ModelCapabilities] = {...}  # 手工维护，key 是精确的 model_name 字符串

def get_model_capabilities(model_name: str) -> ModelCapabilities | None:
    return _CATALOG.get(model_name)
```

首批登记的模型名和数据来自各家官方文档公开记录的规格（`claude-sonnet-5`/`claude-opus-5`：
200K 上下文，支持工具调用和 thinking；`gpt-4o`：128K，支持工具调用，不支持 thinking；
`deepseek-chat`：64K，支持工具调用，支持 thinking；`moonshot-v1-128k`：128K，支持工具调用，
不支持 thinking）。和 `pricing.py`"手工维护、查不到就是 `None`、不编造"的哲学完全一致（Edge
Cases 已经写明：这些数据会过时，这次不解决"自动同步"问题，和 `MODEL_PRICES` 的现状局限性是同
一类取舍）。

对应 FR-006、Clarifications Q2（目录不含价格——`ModelCapabilities` 没有任何价格字段，和
`pricing.py` 的 `dict[str, dict[str, float]]` 价目表是两个完全独立的模块，互不 import）。

**备选方案**：目录数据从一个外部模型规格数据源（如 pi 自己用的那个）自动拉取/生成。被否决——
spec.md Assumptions 已经明确排除这个"自动生成管线"属于独立子项目的范畴。

## 决策 5：压缩阈值默认值怎么接入 `apps/api/runtime.py`（关键的时序细节）

**决策**：核实 `apps/api/runtime.py` 现状发现一个容易踩的坑——`ChatRuntime.__init__` 的
`compaction_token_limit` 参数默认值是 `None`，但真实部署路径 `apps/api/main.py` 的
`create_app()` **总是**传一个具体整数：

```python
compaction_token_limit=int(os.environ.get("COMPACTION_TOKEN_LIMIT", "16000")),
```

也就是说，即使用户完全没配置 `COMPACTION_TOKEN_LIMIT`，真实跑起来的 `ChatRuntime` 实例的
`self._compaction_token_limit` 也从来不是 `None`，而是字面量 `16000`——如果只在
`ChatRuntime.__init__` 里加"为 `None` 时查目录"的逻辑，这个分支在真实部署里永远不会触发，
FR-008/SC-003 形同虚设。

**两处都要改，但逻辑只长在一个地方**：
1. `apps/api/main.py` 的这一行改成 `int(os.environ["COMPACTION_TOKEN_LIMIT"]) if
   os.environ.get("COMPACTION_TOKEN_LIMIT") else None`——不再提供自己的硬编码兜底，让 `None`
   真正流到 `ChatRuntime`。这是纯机械的"去掉一个遮住新逻辑的硬编码默认值"，不包含任何新的策
   略判断。
2. 真正的策略逻辑全部在 `apps/api/runtime.py` 的 `_get_agent()`（`self._compaction_token_
   limit` 为 `None` 时才会用到）：

```python
effective_limit = self._compaction_token_limit
if effective_limit is None:
    effective_limit = default_compaction_token_limit(self._client().model_name)
agent = build_agent(..., compaction_token_limit=effective_limit, ...)
```

`default_compaction_token_limit(model_name)`（定义在 `model_catalog.py`，因为它是"目录查不到
时怎么办"这条策略的自然归属地）**保证总是返回一个可用的 int**，不是 `Optional`：

```python
_LEGACY_DEFAULT_COMPACTION_TOKEN_LIMIT = 16000  # 和改动前 apps/api/main.py 的硬编码默认值完全一致

def default_compaction_token_limit(model_name: str) -> int:
    capabilities = get_model_capabilities(model_name)
    if capabilities is None:
        return _LEGACY_DEFAULT_COMPACTION_TOKEN_LIMIT
    return int(capabilities.context_window * 0.5)
```

0.5（上下文窗口的一半）作为压缩阈值的比例：给摘要本身、新一轮工具调用、模型输出都留出余量，
是一个保守、合理的默认值（不是精确科学，调用方永远可以显式传 `compaction_token_limit` 覆盖）。
`model_name` 不在目录里时，回退到和现状完全相同的 16000——这保证了"模型已知→用更聪明的数
字；模型未知→行为和改动前一模一样"，不会有任何现状部署因为这次改动而默认值突然变化
（SC-002/FR-010）。

对应 FR-008、Clarifications Q3。

**备选方案**：只改 `ChatRuntime.__init__`，不碰 `apps/api/main.py`。被否决——上面已经证明这样
改了也不会在真实部署里生效，等于白做；发现这个时序细节正是这次 Phase 0 研究最有价值的一条产
出。

## 决策 6：流式用量上报怪癖的声明式配置，以及"不编造未经验证的第三方事实"的取舍

**决策**：`OpenAICompatibleBackend.__init__` 新增一个可选构造参数
`supports_stream_usage: bool | None = None`：

```python
self._stream_usage_enabled = True if supports_stream_usage is None else supports_stream_usage
```

`None`（默认）完全保留现状行为（反应式学习：先尝试带 `stream_options`，失败了才降级并记
住）；`True`/`False` 时直接采用声明值，`_create_stream()` 不再需要试探。`ModelClient` 构造后
端时把 `preset.supports_stream_usage` 传给 `OpenAICompatibleBackend`。

首批 4 个新增具名 provider（`openai`/`deepseek`/`moonshot`，加上不变的
`openai-compatible`）**全部把 `supports_stream_usage` 留空（`None`）**——我没有可验证的、确凿
的证据证明这几个真实服务商当前到底支不支持 `stream_options.include_usage`（这是会随服务商 API
版本变化的事实，不应该在 spec/plan 阶段凭印象断言）。User Story 3 的 Independent Test 改用
**测试专属的合成 provider 条目**（不对应任何真实服务商，只在测试里临时注册）来验证"声明
`False` 时从一开始就不带 `stream_options`"这条机制本身是正确的，不需要也不应该拿一个无法现场
验证的真实第三方 API 行为来做断言——这和 `pricing.py`"宁可没有数据也不要猜测"的哲学一致。

对应 FR-009、User Story 3 Independent Test。

**备选方案**：断言 DeepSeek/Moonshot 其中一个真实不支持 `stream_options`。被否决——我无法在当
前环境里对这两个服务商发起真实请求验证这件事，断言一个可能是错的"事实"比留白更糟（直接呼应
`pricing.py` 自己的设计哲学："过期/错误的硬编码数据比没有数据更糟"）。

## 决策 7：reasoning 字段名覆盖——声明但暂不填充

**决策**：`ProviderPreset` 按决策 1 新增 `reasoning_param_name: str | None = None` 字段（满足
FR-001 字面要求的"可选覆盖"能力本身必须存在），但首批 4 个具名 provider **全部留空**（用
默认值 `None`，即沿用现状 `reasoning_effort` 字段名）——现状 `.env.example` 唯一提到的真实案
例（kimi-k3）用的就是标准 `reasoning_effort` 语义（三档 low/high/max），和现状
`_THINKING_LEVEL_TO_REASONING_EFFORT` 映射表已经兼容，没有证据表明首批任何一个 provider 需要
不同字段名。`ModelClient._build_call_kwargs` 需要相应读取 `preset.reasoning_param_name`（为
`None` 时用字面量 `"reasoning_effort"`），让这个字段从"存在但没人用"变成"真正接入请求构造
路径、随时可以被某个新 provider 行使"的能力，而不是摆设数据。

对应 FR-001 的措辞（"可选的"——这次选择不为任何首批 provider 行使这个可选项，不代表这个能力
本身没有接入请求构造逻辑）。
