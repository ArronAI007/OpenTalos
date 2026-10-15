# Tasks: 对齐 pi 的统一模型 Provider 功能

**Input**: Design documents from `/specs/004-model-provider-registry/`
**Prerequisites**: plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md（全部已就绪）

**Tests**: 本仓库宪法 Principle I（TDD 不可协商）要求所有业务代码配套测试、先写测试再实现——下面
每个 User Story 阶段都包含测试任务，必须先于对应实现任务完成并确认失败（RED），再写实现让它们通
过（GREEN）。

**Organization**: 按 User Story 分组，每个 Story 独立可测试、独立可交付。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 对应 spec.md 的 User Story 编号
- 每个任务都带精确文件路径

## Path Conventions

单仓库多 Python 包：`packages/core/`（本次改动核心）、`apps/api/`（压缩阈值接入点）、
`tests/core/`、`tests/apps/api/`。

---

## Phase 1: Setup

**Purpose**: 确认改动前的基线，供后续"只增不减"回归对比

- [X] T001 运行 `.venv/bin/pytest` 记录当前测试通过数，运行 `.venv/bin/python
      scripts/check_core_boundary.py` 确认当前零违规——作为本次改动完成后的回归对比基准（不新
      增/修改任何文件，纯核对）

**Checkpoint**：基线已知，可以开始写代码。

---

## Phase 2: Foundational（阻塞性前置，必须先于任何 User Story 完成）

**⚠️ CRITICAL**: 本阶段完成前不能开始任何 User Story 的任务。User Story 1 和 User Story 3 都依
赖同一个完整的 `ProviderPreset` 数据结构（含 `supports_stream_usage`/`reasoning_param_name`
两个 User Story 3 才会真正消费、但数据形状必须一次性定义完整的字段），放在这里统一建好，避免
后续任务互相修改同一个 dataclass 定义。

- [X] T002 [P] 失败测试：`get_provider_preset("no-such-provider")` 抛 `SettingsError` 且错误信
      息包含全部已注册 provider 名字（按字母排序）；`get_provider_preset("anthropic")`/
      `"openai"`/`"deepseek"`/`"moonshot"`/`"openai-compatible"`/`"mock"` 六个名字都能查到对
      应的 `ProviderPreset`，字段值和 research.md 决策 2 的表格一致（`anthropic`/
      `openai-compatible`/`mock` 三条的 `default_base_url`/`api_key_env_var` 取值必须等价于现
      状行为——即分别是 `None`/`ANTHROPIC_API_KEY`，`None`/`None`，`None`/`None`），写入
      `tests/core/test_providers.py`
- [X] T003 实现 `ProviderPreset` dataclass（`frozen=True`；字段：`name: str`、
      `default_base_url: str | None`、`api_key_env_var: str | None`、
      `supports_stream_usage: bool | None`、`backend: Literal["anthropic", "openai-compatible",
      "mock"]`、`reasoning_param_name: str | None = None`）+ 模块级 `_REGISTRY: dict[str,
      ProviderPreset]`（登记 research.md 决策 2 表格里的全部 6 条数据，`openai`/`deepseek`/
      `moonshot` 三条新增预设的 `supports_stream_usage`/`reasoning_param_name` 都留空为 `None`，
      按 research.md 决策 6/7 的理由）+ `get_provider_preset(name: str) -> ProviderPreset`（未
      注册名字抛 `SettingsError(f'Unknown MODEL_PROVIDER "{name}". Supported:
      {", ".join(sorted(_REGISTRY))}.')`），写入 `packages/core/providers.py`（依赖 T002）

**Checkpoint**：具名 provider 注册表就绪（6 条预设数据完整），User Story 1 和 3 都可以开始。

---

## Phase 3: User Story 1 - 按名字选择预置 Provider，自动套用对应的密钥环境变量和默认服务地址 (Priority: P1) 🎯 MVP

**Goal**：`ModelClient` 构造时按 `MODEL_PROVIDER` 自动解析对应的密钥环境变量名和默认服务地
址，不需要手动填 `MODEL_BASE_URL`。

**Independent Test**：用 `monkeypatch` 组合设置/不设置各环境变量，构造 `ModelClient`，断言
`api_key`/`base_url` 的最终取值符合 FR-003/FR-004 的优先级；验证现状三个 provider 不回归。

### Tests for User Story 1 ⚠️ 先写，确认失败，再实现

- [X] T004 [P] [US1] 失败测试：`MODEL_PROVIDER` 设成未注册的名字时，`ModelClient.__init__`（构
      造阶段，不是发请求时）抛出 `SettingsError`，写入 `tests/core/test_model.py`
- [X] T005 [P] [US1] 失败测试：`provider="deepseek"`，同时设置 `DEEPSEEK_API_KEY` 和通用
      `MODEL_API_KEY` 两个环境变量，构造后 `ModelClient.api_key` 取自 `DEEPSEEK_API_KEY`，通用
      变量的值被忽略，写入 `tests/core/test_model.py`
- [X] T006 [P] [US1] 失败测试：`provider="anthropic"`，只设置通用 `MODEL_API_KEY`（不设
      `ANTHROPIC_API_KEY`，和现状部署方式一致），构造后 `ModelClient.api_key` 取自
      `MODEL_API_KEY`；`provider="openai-compatible"`/`"mock"` 同理验证不回归，写入
      `tests/core/test_model.py`
- [X] T007 [P] [US1] 失败测试：`provider="deepseek"`，显式构造参数 `base_url="https://
      custom-mirror.example"` 或设置 `MODEL_BASE_URL` 环境变量时，`ModelClient.base_url` 取显
      式值，不是 `deepseek` 的默认服务地址，写入 `tests/core/test_model.py`
- [X] T008 [P] [US1] 失败测试：`provider="openai"`/`"deepseek"`/`"moonshot"` 三者在不设置
      `MODEL_BASE_URL` 时，`ModelClient.base_url` 分别等于 research.md 决策 2 表格里各自的
      `default_base_url`，写入 `tests/core/test_model.py`

### Implementation for User Story 1

- [X] T009 [US1] 在 `ModelClient.__init__` 入口处新增 `preset = get_provider_preset(self.
      provider)` 查询（替换现状直接在 `create_model_backend` 里报错的位置，确保未注册名字在构
      造阶段、密钥/base_url 解析之前就报错），写入 `packages/core/model.py`（依赖 T003）
- [X] T010 [US1] 用 T009 查到的 `preset` 实现 `self.api_key` 解析：显式构造参数 > `preset.
      api_key_env_var` 对应的环境变量（`preset.api_key_env_var` 为 `None` 时跳过这一级）> 现
      状通用 `MODEL_API_KEY` 环境变量；`provider == "mock"` 分支（固定占位密钥）不受影响，写入
      `packages/core/model.py`（依赖 T009）
- [X] T011 [US1] 用 T009 查到的 `preset` 实现 `self.base_url` 解析：显式构造参数 >
      `MODEL_BASE_URL` 环境变量 > `preset.default_base_url`，写入 `packages/core/model.py`
      （依赖 T009）
- [X] T012 [US1] 改造 `create_model_backend`：按 `get_provider_preset(provider).backend` 动态
      分发到 `ClaudeBackend`/`OpenAICompatibleBackend`/`FakeModelBackend`，不再是硬编码的
      `if provider == "anthropic": ... elif ...` 字符串匹配链（未知名字的报错已经在 T009 处理，
      这里不需要重复校验），写入 `packages/core/model.py`（依赖 T009）
- [X] T013 [US1] 运行 `.venv/bin/pytest tests/core/test_model.py tests/core/test_providers.py
      -v`，确认全部通过（GREEN checkpoint）

**Checkpoint**：User Story 1（具名 provider 的密钥/base_url 自动解析）独立可用——这是 MVP。

---

## Phase 4: User Story 2 - 小型手工维护的模型能力目录（上下文窗口/工具调用/thinking 支持） (Priority: P2)

**Goal**：按模型名查询能力数据（不含价格），并接入 `apps/api/runtime.py` 的压缩阈值默认值。

**Independent Test**：查询已登记/未登记模型名的能力数据；构造 `ChatRuntime` 不传
`compaction_token_limit`，断言实际生效阈值来自目录换算（已知模型）或回退 16000（未知模型）。

### Tests for User Story 2 ⚠️ 先写，确认失败，再实现

- [X] T014 [P] [US2] 失败测试：`get_model_capabilities("claude-sonnet-5")` 等已登记模型名返回
      完整的 `ModelCapabilities`（`context_window`/`supports_tools`/`supports_thinking` 三个
      字段都有值）；`get_model_capabilities("some-unregistered-model")` 返回 `None`，写入
      `tests/core/test_model_catalog.py`
- [X] T015 [P] [US2] 失败测试：`default_compaction_token_limit("claude-sonnet-5")` 等已登记模
      型返回 `int(该模型 context_window * 0.5)`；`default_compaction_token_limit(
      "some-unregistered-model")` 返回 `16000`（和改动前 `apps/api/main.py` 的硬编码默认值完
      全一致），写入 `tests/core/test_model_catalog.py`
- [X] T016 [P] [US2] 失败测试：`ModelCapabilities` dataclass 的字段集合里不包含任何价格/成本相
      关字段；`packages/core/model_catalog.py` 和 `packages/core/pricing.py` 互不 import，写入
      `tests/core/test_model_catalog.py`
- [X] T017 [P] [US2] 失败测试：构造 `ChatRuntime` 不传 `compaction_token_limit`，
      `model_client.model_name` 命中目录（如 `"claude-sonnet-5"`），触发一次 `_get_agent()`
      后，构造出的 `Agent.compaction_token_limit` 等于目录换算值；`model_name` 不在目录里时等
      于 `16000`；显式传 `compaction_token_limit=5000` 时该值优先、不被目录数据覆盖，写入
      `tests/apps/api/test_runtime.py`

### Implementation for User Story 2

- [X] T018 [US2] 实现 `ModelCapabilities` dataclass（`frozen=True`；字段：`context_window:
      int`、`supports_tools: bool`、`supports_thinking: bool`，不含任何价格字段）+ 模块级
      `_CATALOG: dict[str, ModelCapabilities]`（按 research.md 决策 4 登记首批模型数据：
      `claude-sonnet-5`/`claude-opus-5`/`gpt-4o`/`deepseek-chat`/`moonshot-v1-128k`）+
      `get_model_capabilities(model_name: str) -> ModelCapabilities | None`，写入
      `packages/core/model_catalog.py`（依赖 T014）
- [X] T019 [US2] 实现 `_LEGACY_DEFAULT_COMPACTION_TOKEN_LIMIT = 16000` 常量 +
      `default_compaction_token_limit(model_name: str) -> int`（已知模型返回
      `int(capabilities.context_window * 0.5)`，未知模型返回
      `_LEGACY_DEFAULT_COMPACTION_TOKEN_LIMIT`），写入 `packages/core/model_catalog.py`（依赖
      T018, T015）
- [X] T020 [US2] 改造 `apps/api/runtime.py` 的 `_get_agent()`：在调用 `build_agent(...,
      compaction_token_limit=self._compaction_token_limit, ...)` 之前，若
      `self._compaction_token_limit is None`，用 `default_compaction_token_limit(self._client
      ().model_name)` 算出一个非 `None` 的 `effective_limit` 并传给 `build_agent`（`self.
      _client()` 的调用顺序必须保证在这个判断之前已经执行过，确保 `model_name` 已知），写入
      `apps/api/runtime.py`（依赖 T019, T017）
- [X] T021 [US2] 改造 `apps/api/main.py` 的 `create_app()`：`compaction_token_limit` 参数不再
      无条件传 `int(os.environ.get("COMPACTION_TOKEN_LIMIT", "16000"))`；改成
      `int(os.environ["COMPACTION_TOKEN_LIMIT"]) if os.environ.get("COMPACTION_TOKEN_LIMIT")
      else None`（环境变量未设置时传 `None`，把决定权交给 T020 的新逻辑；显式设置时行为不
      变），写入 `apps/api/main.py`（依赖 T020）
- [X] T022 [US2] 运行 `.venv/bin/pytest tests/core/test_model_catalog.py
      tests/apps/api/test_runtime.py tests/apps/api/test_api_routes.py -v`，确认全部通过
      （GREEN checkpoint）

**Checkpoint**：User Story 1 + 2 都独立可用——压缩阈值现在有一个比"硬编码 16000"更聪明的默认
值来源。

---

## Phase 5: User Story 3 - 为 OpenAI 兼容类 Provider 声明式配置请求参数怪癖 (Priority: P3)

**Goal**：`supports_stream_usage`/`reasoning_param_name` 两个声明式配置真正接入请求构造逻辑。

**Independent Test**：用测试专属的合成 `ProviderPreset`（不对应任何真实服务商）验证声明值从首
次请求就生效，不经历反应式学习；验证现状 `openai-compatible`（未声明）行为不回归。

### Tests for User Story 3 ⚠️ 先写，确认失败，再实现

- [X] T023 [P] [US3] 失败测试：构造 `OpenAICompatibleBackend(..., supports_stream_usage=False)`
      （测试专属合成配置，不对应任何真实服务商），首次流式请求的调用参数里没有
      `stream_options`，不经历"先失败一次再降级"，写入 `tests/core/test_model.py`
- [X] T024 [P] [US3] 失败测试：构造 `OpenAICompatibleBackend(..., supports_stream_usage=None)`
      （对应现状 `openai-compatible` 的默认行为），首次流式请求仍然尝试带
      `stream_options.include_usage`，失败后降级并记住——和改动前完全一致，写入
      `tests/core/test_model.py`
- [X] T025 [P] [US3] 失败测试：`preset.reasoning_param_name="custom_reasoning_field"` 时，
      `ModelClient._build_call_kwargs` 构造出的请求参数里用 `"custom_reasoning_field"` 这个键
      承载推理强度，而不是 `"reasoning_effort"`；`reasoning_param_name=None`（现状全部 6 个预
      设的取值）时行为和改动前完全一致，写入 `tests/core/test_model.py`

### Implementation for User Story 3

- [X] T026 [US3] `OpenAICompatibleBackend.__init__` 新增可选构造参数
      `supports_stream_usage: bool | None = None`；`self._stream_usage_enabled` 的初值改为
      `True if supports_stream_usage is None else supports_stream_usage`（`None` 时保留现状
      反应式学习；非 `None` 时 `_create_stream()` 直接用声明值，不再需要试探-降级那条分支），
      写入 `packages/core/model.py`（依赖 T023, T024）
- [X] T027 [US3] `ModelClient.__init__` 构造 `OpenAICompatibleBackend` 时，把 T009 查到的
      `preset.supports_stream_usage` 传给它的新构造参数，写入 `packages/core/model.py`（依赖
      T026）
- [X] T028 [US3] `ModelClient._build_call_kwargs` 读取 `preset.reasoning_param_name`（为 `None`
      时继续用字面量 `"reasoning_effort"`）决定请求参数字典里推理强度字段的键名，写入
      `packages/core/model.py`（依赖 T025）
- [X] T029 [US3] 运行 `.venv/bin/pytest tests/core/test_model.py -v`，确认全部通过（GREEN
      checkpoint）

**Checkpoint**：全部 3 个 User Story 独立可用。

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T030 [P] 更新 `.env.example`：在现状 `MODEL_PROVIDER=` 那一行附近补充注释，列出新支持的
      具名 provider 名字（`anthropic`/`openai`/`deepseek`/`moonshot`/`openai-compatible`/
      `mock`）和各自对应的专属密钥环境变量名（`ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/
      `DEEPSEEK_API_KEY`/`MOONSHOT_API_KEY`），说明"专属变量优先于通用 `MODEL_API_KEY`"这条优
      先级规则
- [X] T031 运行 `.venv/bin/pytest`（全量），和 T001 记录的基线对比，确认 0 回归、测试数只增不
      减
- [X] T032 运行 `.venv/bin/python scripts/check_core_boundary.py`，确认依然零违规（新增的
      `providers.py`/`model_catalog.py` 都不 import 其他 `packages/*`）
- [X] T033 [P] 执行 quickstart.md 的全部 5 个验证场景，确认每条命令按文档预期工作
- [X] T034 [P] 更新项目 memory（`project_opentalos_python_rebuild.md` 追加本次 shipped 记录 +
      `MEMORY.md` 索引行同步）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup（Phase 1）**：无依赖，立即开始
- **Foundational（Phase 2）**：依赖 Setup 完成——阻塞 User Story 1 和 3（User Story 2 的
  `model_catalog.py` 不依赖 Foundational 阶段的 `providers.py`，理论上可以更早开始，但为了保持
  "User Story 按优先级顺序交付"的既定节奏，仍安排在 Foundational 之后）
- **User Story 1（Phase 3）**：依赖 Foundational 完成；**MVP**，独立可交付
- **User Story 2（Phase 4）**：依赖 Setup 完成即可开始（不依赖 Phase 2/3 的任何产出——
  `model_catalog.py` 是全新、独立的模块，`apps/api/runtime.py`/`apps/api/main.py` 的改动也不
  涉及 provider 注册表），可以和 User Story 1 并行推进
- **User Story 3（Phase 5）**：依赖 Foundational 完成（需要 `ProviderPreset` 的
  `supports_stream_usage`/`reasoning_param_name` 字段已经存在）；逻辑上也依赖 User Story 1 的
  T009（`ModelClient.__init__` 已经查出 `preset` 变量，T027/T028 直接复用它，不重新查一次）
- **Polish（Phase 6）**：依赖全部 User Story 完成

### Within Each User Story

- 测试任务必须先写、先确认失败（RED），再写实现任务（GREEN）
- 同一 Story 内，数据结构/类型定义先于使用它们的方法实现

### Parallel Opportunities

- Phase 3 的 T004-T008 五个测试任务可以并行编写（同一测试文件内的不同测试函数，互不依赖）
- Phase 4 的 T014-T017 四个测试任务可以并行编写
- Phase 5 的 T023-T025 三个测试任务可以并行编写
- **User Story 1 和 User Story 2 可以由不同开发者并行推进**（互不依赖，见上方 Phase Dependencies
  说明）；User Story 3 需要等 Foundational + User Story 1 的 T009 完成后才能开始

---

## Parallel Example: Foundational

```bash
# 注册表的类型定义测试（T002）和后续实现（T003）本身是严格顺序（同一文件，RED→GREEN），
# 但如果团队协作，可以让一人专注 Foundational，另一人提前开始 User Story 2（无依赖）：
Task: "编写 providers.py 的失败测试（T002）"
Task: "编写 model_catalog.py 的失败测试（T014-T017，User Story 2，无需等待 Foundational）"
```

## Parallel Example: User Story 1 的测试

```bash
# 五个测试任务可以并行编写（同一文件的不同测试函数）：
Task: "未注册 provider 名字报错的失败测试"
Task: "专属环境变量优先于通用 MODEL_API_KEY 的失败测试"
Task: "只设通用 MODEL_API_KEY 时不回归的失败测试"
Task: "显式 base_url 覆盖默认服务地址的失败测试"
Task: "三个新增具名 provider 使用各自默认服务地址的失败测试"
```

---

## Implementation Strategy

### MVP First（仅 User Story 1）

1. 完成 Phase 1：Setup
2. 完成 Phase 2：Foundational（阻塞项，必须完成）
3. 完成 Phase 3：User Story 1
4. **STOP and VALIDATE**：独立验证 User Story 1（`quickstart.md` 场景 1）
5. 此时"按名字选择预置 provider"这条核心价值已经可以独立合并/演示

### Incremental Delivery

1. Setup + Foundational → 基础就绪
2. User Story 1（具名 provider 密钥/base_url 自动解析）→ 独立测试通过 → 这是 MVP
3. User Story 2（模型能力目录 + 压缩阈值默认值）→ 独立测试通过（可以和 User Story 1 并行，见
   Dependencies 说明）
4. User Story 3（声明式请求参数怪癖）→ 独立测试通过
5. Polish → 全量回归 + 依赖边界核查 + 文档更新 + memory 更新

### Parallel Team Strategy

1. 团队一起完成 Setup + Foundational
2. Foundational 完成后：
   - 开发者 A：User Story 1（也可以提前于 Foundational 完成前就开始 User Story 2，因为它无依
     赖）
   - 开发者 B：User Story 2
3. User Story 1 完成（尤其是 T009 查 `preset` 的那段逻辑落地）后，开发者 A 或新加入的开发者 C
   接着做 User Story 3

---

## Notes

- `[P]` 任务 = 不同文件、无依赖
- `[Story]` 标签把任务对应回 spec.md 的 User Story 编号，便于追溯
- User Story 2 是本次任务图里唯一一个不依赖 Foundational/其他 Story 就能独立开始的 Story（已在
  Dependencies 一节显式说明），不代表它比其他 Story 更不重要，只是数据结构恰好完全独立
- 实现前先验证测试确实失败（RED）
- 建议每个 User Story 完成后提交一次（参照 002/003 feature 的"每个 User Story 一次提交"节奏）
- 可以在任意 Checkpoint 处停下独立验证对应 Story
- 避免：模糊任务描述、同文件冲突的并行标记、破坏 Story 独立性的跨 Story 依赖
