# Feature Specification: 对齐 pi 的统一模型 Provider 功能

**Feature Branch**: `004-model-provider-registry`

**Created**: 2026-10-15

**Status**: Draft

**Input**: User description: "请根据 https://github.com/earendil-works/pi/tree/main/packages/ai 完善一下该项目统一Provider功能"

## 参考实现核实记录（写 spec 前直接核实过的事实，不是猜测）

直接读了 `earendil-works/pi` `packages/ai` 的 README 目录结构和 `src/providers/all.ts`（provider
注册方式）、`src/providers/compat-schema.ts`（通用 OpenAI 兼容工厂）、`src/model-catalog.ts`/
`src/models.ts`（静态模型目录）、`src/auth/resolve.ts`/`src/env-api-keys.ts`（按 provider 名字自
动解析对应环境变量的鉴权机制），以及 README 的 Provider Factories/Custom Providers/Faux
Provider 等章节。`packages/ai` 本身规模巨大（150+ 源文件，约 40 个具名 provider、完整的
per-provider OAuth 设备码流程、图像生成、分类器 API、一个从外部数据源自动生成的模型目录构建管
线）——这些都明显超出"完善统一 Provider 功能"这句话在本仓库语境下的合理范围，不在本次之内（见
Assumptions）。

同时逐行读了本仓库现状 `packages/core/model.py`（739 行）、`packages/core/pricing.py`（46
行）、`.env.example` 里模型相关的环境变量。确认的关键事实：

- **现状只有 3 个 provider**：`anthropic`（`ClaudeBackend`）、`openai-compatible`
  （`OpenAICompatibleBackend`，已经支持任意自托管/第三方端点——靠调用方自己填
  `MODEL_BASE_URL`）、`mock`（仅测试用）。`create_model_backend(provider, ...)` 按这三个字符
  串做分支，没有注册表，没有"预置具名 provider"的概念。
- **鉴权是单一通用环境变量**：不管选哪个 provider，密钥统一从 `MODEL_API_KEY` 读——不是 pi 那
  种"每个具名 provider 自动认自己那个约定俗成的环境变量名（如 `ANTHROPIC_API_KEY`/
  `OPENAI_API_KEY`）"的自动解析机制。换一个 OpenAI 兼容服务商，用户得自己去 `.env` 里同时填对
  `MODEL_BASE_URL` 和把密钥塞进同一个 `MODEL_API_KEY`，容易在切换 provider 时忘记同步改
  base_url。
- **没有任何模型能力/静态目录数据**：`model_name` 只是一个透传字符串，系统完全不知道某个模型
  的上下文窗口大小、是否支持工具调用、是否支持 thinking/reasoning——`apps/api/runtime.py` 的
  `compaction_token_limit` 现状必须由调用方手动指定一个数字（或不指定、不压缩），不存在任何"根
  据模型自动给一个合理默认值"的机制。
- **`pricing.py` 刻意不内置任何默认价目表**——文件自己的 docstring 明确写着"价格会变，硬编码的
  过期价格比没有成本更糟"，价目表完全由 `MODEL_PRICES` 环境变量（JSON）提供，查不到就返回
  `None` 而不是猜一个数。这是一条已经做出、且有明确理由的设计决策，经 Clarifications 确认这次
  新增的模型能力目录和它完全独立，不包含任何价格数据（见 User Story 2）。
- **OpenAI 兼容后端已经有一条"反应式学习 quirk"的先例**：`_stream_usage_enabled` 这个实例标志
  ——第一次请求带 `stream_options.include_usage` 被某个不支持的供应商拒绝后，记住"以后不再带"，
  但这是运行时试出来的，不是声明式配置；`.env.example` 里 `MODEL_REASONING_EFFORT` 的注释明确
  提到"kimi-k3"这个具体供应商，说明本仓库已经在实际场景里对接过至少一个 OpenAI 兼容但有自己专属
  字段怪癖的第三方模型服务，但目前每换一个这样的服务都要靠口口相传的 `.env.example` 注释，不是
  系统内置的、可枚举的配置。
- **当前架构允许同一进程里存在多个独立的 `ModelClient` 实例**（纯 Python 对象，没有进程级单例限
  制），本次不需要、也不会引入"运行时切换/多 provider 同时存在"这类架构改动去对齐 pi 的
  cross-provider handoff 能力——那本身也明确不在这次范围内（见 Assumptions）。

## Clarifications

### Session 2026-10-15

- Q: 当一个具名 provider 自己的专属环境变量（如 `DEEPSEEK_API_KEY`）和现状的通用
  `MODEL_API_KEY` 同时被设置时，密钥解析该听谁的？ → A: 具名 provider 自己的专属环境变量优先
  于通用 `MODEL_API_KEY`——更具体的配置覆盖更通用的配置，是常见约定（pi 自己也是"具名
  provider 的专属环境变量优先"），且现状配置（只设了 `MODEL_API_KEY`、没设任何具名专属变量）
  行为完全不变，不构成破坏性变更。
- Q: 这个能力目录要不要顺带内置一个默认价目表（作为 `MODEL_PRICES` 查不到时的兜底），还是价格
  继续完全只从 `MODEL_PRICES` 来、目录只提供能力数据？ → A: 目录不包含任何价格数据，
  `pricing.py`"价格只从环境变量来、查不到就是 `None`"这条现状设计原封不动——新目录和定价是两
  件独立的事，不应该因为这次顺手加目录就悄悄推翻一条已经写明理由的设计决策。
- Q: 目录里的上下文窗口数据要不要直接接入 `apps/api/runtime.py`，在调用方未显式指定
  `compaction_token_limit` 时自动算一个默认值，还是这次只把目录建好、查得到，接入运行时留给以
  后？ → A: 接入——未显式指定 `compaction_token_limit` 时，用目录里的上下文窗口自动算一个默认
  值；这是让目录从"建好但没人用的数据"变成真正有价值的改动所必需的，且改动范围可控（只影响
  `apps/api/runtime.py` 一处消费点）。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 按名字选择预置 Provider，自动套用对应的密钥环境变量和默认服务地址 (Priority: P1)

维护者/部署者想换一个模型服务商时，只设置 `MODEL_PROVIDER=<具名服务商>` 和该服务商自己的密钥
环境变量（例如 `DEEPSEEK_API_KEY`），不需要同时手动查并填写 `MODEL_BASE_URL`，也不需要把密钥
塞进一个和服务商无关的通用变量名里——这是"统一 Provider"最核心的可见价值：加一个新服务商只是
"在注册表里登记一条"，而不是每次都要翻官方文档找 base_url 再手填。

**本次经确认**：具名 provider 自己的专属环境变量优先于现状的通用 `MODEL_API_KEY`
（Clarifications 已确认），现状只设通用变量的部署行为完全不变。

**Why this priority**：这是"统一 Provider"这句话字面意义上最核心的部分——pi 的 Provider
Factories/auth 自动解析正是"统一"这个词想表达的东西；现状的"手动填 base_url+塞进通用变量名"
是这次要解决的真实不便。

**Independent Test**：不设置 `MODEL_BASE_URL`、只设置 `MODEL_PROVIDER=<某个新增的具名预置
provider>` 和该 provider 自己的密钥环境变量，构造 `ModelClient` 并发起一次真实/可录制的请求，
验证请求确实发到了这个 provider 的默认服务地址；再验证现状的 `anthropic`/`openai-compatible`/
`mock` 三个 provider 行为不受影响（不回归）。

**Acceptance Scenarios**:

1. **Given** 环境变量只设置了 `MODEL_PROVIDER=deepseek`（或其他新增的具名预置 provider）和
   `DEEPSEEK_API_KEY`（该 provider 自己的密钥变量名），**When** 构造 `ModelClient()`，**Then**
   客户端使用这个 provider 的默认服务地址发起请求，不需要额外设置 `MODEL_BASE_URL`。
2. **Given** 一个具名预置 provider 自己的密钥环境变量和通用 `MODEL_API_KEY` 同时被设置，
   **When** 构造 `ModelClient()`，**Then** 密钥取自该 provider 自己的环境变量，通用变量的值被
   忽略。
3. **Given** 只设置了通用 `MODEL_API_KEY`（没有设置任何具名 provider 专属变量，和现状部署方式
   完全一样），**When** 构造 `ModelClient()`，**Then** 行为和这次改动之前完全一致（不回归）。
4. **Given** 一个具名预置 provider，**When** 调用方显式传入 `base_url` 构造参数或设置
   `MODEL_BASE_URL`，**Then** 显式值覆盖这个 provider 的默认服务地址（自托管镜像/代理场景）。
5. **Given** `MODEL_PROVIDER` 设置成一个不存在的名字，**When** 构造 `ModelClient()`，**Then**
   立刻抛出清晰的错误，列出当前全部可用的 provider 名字，而不是在第一次真正发请求时才报错。

---

### User Story 2 - 小型手工维护的模型能力目录（上下文窗口/工具调用/thinking 支持） (Priority: P2)

维护者需要系统知道"这个模型支持不支持工具调用"“支持不支持 thinking/reasoning”“上下文窗口多
大”，而不是对每个模型的能力一无所知、全靠调用方自己记住并手动传参数。

**本次经确认**：这个目录**不包含任何价格数据**（Clarifications 已确认，`pricing.py` 现状的
"价格只从 `MODEL_PRICES` 来"原则不变）；目录里的上下文窗口数据**接入**
`apps/api/runtime.py`——调用方未显式指定 `compaction_token_limit` 时，用目录给出的上下文窗口
算一个默认值（Clarifications 已确认）。

**Why this priority**：这是 pi"统一 Provider"里除了鉴权自动解析之外最有实际价值的部分——没有
这个数据，`compaction_token_limit` 现状只能靠用户自己瞎猜一个数字，或者干脆不压缩、冒着跑满上
下文窗口被服务端拒绝的风险。

**Independent Test**：对目录里登记过的模型名查询能力数据，断言返回值字段完整；对一个目录里没
有的模型名查询，断言返回"无数据"（`None`/等价空值），不是编造出来的猜测值；构造
`ChatRuntime` 时不传 `compaction_token_limit`、`model_name` 在目录里有数据，断言实际生效的压
缩阈值确实来自目录换算，而不是硬编码的全局默认值。

**Acceptance Scenarios**:

1. **Given** 一个目录里登记过能力数据的模型名，**When** 查询它的能力，**Then** 返回包含上下文
   窗口大小、是否支持工具调用、是否支持 thinking/reasoning 的完整数据。
2. **Given** 一个目录里没有登记过的模型名（比如用户自己部署的私有模型），**When** 查询它的能
   力，**Then** 返回明确的"无数据"结果，系统继续正常工作（现状行为：不因为没有能力数据就报错
   或拒绝构造 `ModelClient`）。
3. **Given** 构造 `ChatRuntime`/`ModelClient` 时没有显式传 `compaction_token_limit`，且
   `model_name` 在目录里有上下文窗口数据，**When** 真正触发一次压缩判断，**Then** 生效的阈值
   是根据目录里的上下文窗口算出来的默认值，不是之前的硬编码/无压缩状态。
4. **Given** 构造时显式传了 `compaction_token_limit`，**When** 真正触发一次压缩判断，**Then**
   显式值优先，目录数据不覆盖调用方的明确选择。
5. **Given** 目录数据和 `MODEL_PRICES` 环境变量都存在（两套机制并存），**When** 分别查询能力
   数据和估算成本，**Then** 两者走完全独立的代码路径，查能力目录这件事本身不会读取或改变
   `MODEL_PRICES` 的查找结果。

---

### User Story 3 - 为 OpenAI 兼容类 Provider 声明式配置请求参数怪癖 (Priority: P3)

维护者需要给一个新的 OpenAI 兼容服务商接入"这个服务商不支持 `stream_options.include_usage`"
“这个服务商的 reasoning 相关字段叫别的名字”这类怪癖时，是在注册表里声明一行配置，而不是像现
状 `_stream_usage_enabled` 那样只能靠真实发一次请求失败了才"学"到。

**Why this priority**：这是三个 User Story 里收益相对最小、风险也最小的一块——现状的反应式学
习机制本身能工作（只是第一次请求会白打一次），声明式配置是锦上添花而不是修复一个真正的 bug。

**Independent Test**：为一个新增的具名预置 provider 声明"不支持 stream usage"，构造
`ModelClient` 发起一次流式请求，断言请求从一开始就不带 `stream_options`（不需要先失败一次才学
会）；再验证现状的 `openai-compatible`（没有预声明、靠反应式学习）行为不受影响。

**Acceptance Scenarios**:

1. **Given** 一个声明了"不支持 stream usage"的具名预置 provider，**When** 发起首次流式请求，
   **Then** 请求从一开始就不带 `stream_options.include_usage`，不经历"先失败一次再降级"的过
   程。
2. **Given** 现状的 `openai-compatible`（没有任何预声明），**When** 发起流式请求，**Then** 行
   为和这次改动之前完全一致（先尝试带 `stream_options`，不支持的供应商第一次失败后降级且记
   住）。

### Edge Cases

- 同一个具名 provider 的专属环境变量和通用 `MODEL_API_KEY`、以及构造函数显式传入的 `api_key`
  参数三者都存在——显式构造参数优先级最高（现状已经是这样，这次不改变这条优先级），具名专属
  环境变量其次，通用 `MODEL_API_KEY` 最后。
- 模型能力目录的数据本身过时（比如某个模型服务商后来扩大了上下文窗口）——这是手工维护的数据
  本来就有的局限，不在这次范围内解决（没有自动从外部数据源同步的机制，这点 pi 自己也有相应的
  自动化构建管线，但明确排除在本次范围之外）。
- 新增的具名预置 provider 本质上仍然是"OpenAI 兼容"家族的一员（走同一套请求/响应解析代码），
  不是重新实现一整套协议——只是"预先知道 base_url/密钥环境变量名/请求参数怪癖"这三类配置数据,
  不应该被误解成每个具名 provider 都需要一个独立的后端实现类。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须提供一个具名 provider 的注册表，每个具名 provider 声明自己的：默认服务
  地址（base_url）、自己专属的 API 密钥环境变量名、是否支持流式用量上报（stream usage）、以及
  可选的请求参数字段名覆盖（例如某些服务商的 reasoning 相关字段名和 OpenAI 原生命名不同）。
- **FR-002**: 系统必须至少包含 `anthropic`、`openai`（官方 OpenAI API，作为独立于通用
  `openai-compatible` 之外的具名条目）、以及至少两个来自真实使用场景的第三方 OpenAI 兼容服务
  商（例如 DeepSeek、Moonshot/Kimi——`.env.example` 现状注释已经提到 kimi-k3），覆盖面不低于
  现状的 3 个 provider。
- **FR-003**: 构造 `ModelClient` 解析 API 密钥时，优先级必须是：显式构造参数 > 该具名 provider
  自己的专属环境变量 > 现状的通用 `MODEL_API_KEY` 环境变量；`mock` provider 不受此优先级影响
  （继续使用固定占位密钥）。
- **FR-004**: 具名 provider 的默认服务地址必须可以被显式构造参数或 `MODEL_BASE_URL` 环境变量
  覆盖（自托管镜像/企业代理场景）。
- **FR-005**: `MODEL_PROVIDER` 设置成一个未注册的名字时，必须在构造阶段就抛出清晰错误并列出
  当前全部已注册的 provider 名字，不能拖到第一次真正发请求时才报错。
- **FR-006**: 系统必须提供一个小型、手工维护的模型能力目录，按模型名查询返回：上下文窗口大
  小、是否支持工具调用、是否支持 thinking/reasoning；查询一个目录里没有的模型名必须返回明确的
  "无数据"结果，不能编造或猜测数值。
- **FR-007**: 这个能力目录不得包含任何价格/成本数据；`packages/core/pricing.py` 现状"价格只
  从 `MODEL_PRICES` 环境变量来、查不到返回 `None`"的行为必须保持不变。
- **FR-008**: 当调用方构造 `ChatRuntime`/`Agent` 时未显式提供 `compaction_token_limit`，且当
  前 `model_name` 在能力目录里有上下文窗口数据时，系统必须根据该上下文窗口自动算出一个默认的
  压缩阈值；调用方显式提供的值始终优先于这个自动默认值。
- **FR-009**: 具名 provider 声明的"不支持流式用量上报"必须在首次请求时就生效（不依赖现状
  `_stream_usage_enabled` 那种"先失败一次才学会"的反应式机制）；没有声明的 provider（含现状
  的通用 `openai-compatible`）继续保留现状的反应式学习行为。
- **FR-010**: 现状的 `anthropic`、`openai-compatible`、`mock` 三个 provider 的全部现有行为
  （包括没有设置任何新引入的环境变量时的默认行为）必须保持不变，不允许出现"之前能用、这次之
  后报错或行为不同"的情况。

### Key Entities

- **具名 Provider 注册表条目**：一个具名 provider 的静态配置——provider 名字、默认 base_url、
  专属密钥环境变量名、是否支持流式用量上报、可选的请求参数字段名覆盖。
- **模型能力目录条目**：一个模型名对应的静态能力数据——上下文窗口大小、是否支持工具调用、是否
  支持 thinking/reasoning。不含任何价格信息（和现状 `pricing.py` 的价目表是两套完全独立的数
  据）。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 切换到一个新增的具名预置 provider 时，用户只需要设置两个环境变量（
  `MODEL_PROVIDER` + 该 provider 自己的密钥变量），不需要另外查找并填写服务地址。
- **SC-002**: 现状仅设置通用 `MODEL_API_KEY`、`MODEL_PROVIDER=anthropic`/
  `openai-compatible`/`mock` 的全部已有部署方式，在这次改动后行为保持 100% 一致，没有任何已有
  测试或真实部署因为这次改动而失败。
- **SC-003**: 一个在能力目录里登记过的模型，未显式配置压缩阈值时，运行一段足够长的对话能在接
  近其真实上下文窗口之前被自动压缩，而不是一直不压缩直到被服务端以上下文超限拒绝。
- **SC-004**: 查询一个目录里没有数据的模型能力时，得到的是明确的"不知道"信号，不会被误当成某
  个具体的能力取值（比如误以为"不支持工具调用"而不是"不知道支不支持"）。

## Assumptions

- "完善统一 Provider 功能"理解为对齐 pi `packages/ai` 的**架构模式**（具名 provider 注册表
  +自动密钥环境变量解析+小型模型能力目录+声明式请求怪癖配置），而不是逐一搬运 pi 的全部约 40
  个具名 provider、完整的 per-provider OAuth 设备码登录流程、图像生成 API、分类器 API、或者
  从外部数据源自动生成模型目录的构建管线——这些要么和本仓库当前的实际使用场景（纯文本/工具调
  用的 agent 对话）无关，要么本身是足以独立立项的大型子系统，明确排除在本次范围之外。
- 新增的具名 provider 全部归类为"OpenAI 兼容"家族的配置条目（复用现状
  `OpenAICompatibleBackend` 的请求/响应解析逻辑），不需要为每一个新服务商单独实现一个后端类
  ——这是现状架构本身已经验证过的模式（现状的 `openai-compatible` 已经能对接任意兼容端点）。
- 模型能力目录的数据来源是维护者手工填写/更新，不要求从任何外部服务实时查询或定期自动同步
  ——这点和现状 `pricing.py`"宁可没有数据也不要猜测过期数据"的哲学一致。
- 不引入"同一进程内多个 provider/模型同时服务不同请求"的运行时切换机制——现状架构本来就允许独
  立构造多个 `ModelClient` 实例，这次不需要为此新增任何框架层面的支持；pi 的 cross-provider
  handoff/context 序列化能力明确排除在外。
- `EMBED_MODEL_NAME`/`EMBED_API_KEY`（`packages/memory` 用于长期记忆的独立 embedding 模型配
  置）不在这次范围内——这是一条和 `ModelClient` 并行、服务于不同目的的配置路径，这次只改动
  `ModelClient`/`packages/core/model.py` 相关的 provider 解析逻辑。
