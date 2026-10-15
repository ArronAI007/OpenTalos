# Tasks: 独立的 Provider 包 + Web 端配置界面

**Input**: Design documents from `/specs/005-provider-package-ui/`
**Prerequisites**: plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md（全部已就绪）

**Tests**: 本仓库宪法 Principle I（TDD 不可协商）要求所有业务代码配套测试、先写测试再实现。
User Story 1（纯粹的文件搬移 + 新 Protocol）的 TDD 落脚点是"新增的 `ModelClientProtocol` 本
身先写结构性满足测试"，而搬移本身用"原样迁移现状测试、确认依然全绿"来验证行为不变（不是对已
经正确的行为重新走一遍 RED）；User Story 2/3 的新业务逻辑（CRUD、掩码、免重启生效）完整遵循
先写失败测试再实现的节奏。

**Organization**: 按 User Story 分组。User Story 2/3 依赖 User Story 1 先完成（新 UI/CRUD 需
要包已经搬好的稳定数据源），这是本次任务图里唯一的顺序依赖，已在 Dependencies 一节说明。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 对应 spec.md 的 User Story 编号
- 每个任务都带精确文件路径

## Path Conventions

单仓库多 Python 包 + 一个 Next.js 前端：`packages/ai/`（新建）、`packages/core/`、
`packages/memory/`、`apps/api/`、`apps/web/`、对应的 `tests/`。

---

## Phase 1: Setup

**Purpose**: 确认改动前的基线，供后续"只增不减"回归对比

- [X] T001 运行 `.venv/bin/pytest` 记录当前测试通过数，运行 `.venv/bin/python
      scripts/check_core_boundary.py` 确认当前零违规，运行 `cd apps/web && npx vitest run`
      记录当前前端测试通过数——作为本次改动完成后的回归对比基准（不新增/修改任何文件，纯核
      对）

**Checkpoint**：基线已知，可以开始写代码。

---

## Phase 2: Foundational（阻塞性前置，必须先于任何 User Story 完成）

**⚠️ CRITICAL**: 本阶段完成前不能开始任何 User Story 的任务。

- [X] T002 创建 `packages/ai/__init__.py`（空文件，和现状 `packages/core/__init__.py` 同样的
      约定），建立新包的 import 路径——这是后续 User Story 1 把 4 个文件搬进来之前的最小骨
      架

**Checkpoint**：新包骨架就绪，User Story 1 可以开始。

---

## Phase 3: User Story 1 - Provider/模型配置独立成包，和 agent 循环解耦 (Priority: P1) 🎯 MVP

**Goal**：`packages/core` 对模型客户端的依赖通过自己声明的 `ModelClientProtocol` 表达，
`ModelClient` 及其配套的 provider 注册表/模型能力目录/定价模块搬到独立的 `packages/ai` 包。

**Independent Test**：运行 `scripts/check_core_boundary.py` 确认零违规；运行 004 feature 的
全部现状测试（原样搬到新位置后）确认全部通过，行为逐字不变。

> **范围修正（implementation 阶段发现，/speckit-plan 的研究不够详尽）**：全仓库重新 grep
> `from .model import`/`from core.model import`/`core.providers`/`core.model_catalog` 后发
> 现实际耦合比 plan.md/research.md 记录的大得多：
> 1. **`pricing.py` 不搬**——`packages/core/agent_loop.py` 直接 `from .pricing import
>    estimate_cost` 并在 `execute_model_step` 内部调用（第 360 行），这是 agent 循环自己的成
>    本追踪功能，不是"provider 配置"；如果搬到 `packages/ai`，`agent_loop.py` 又会违反边界。
>    `pricing.py` 本身不依赖 `model.py`/`providers.py`/`model_catalog.py` 中任何一个，留在
>    `packages/core` 没有技术障碍。只搬 `model.py`/`providers.py`/`model_catalog.py` 三个文件。
> 2. `packages/core/compaction.py` 也直接 `from .model import ModelClient`（`summarize_
>    history` 的参数类型），需要和 `agent.py`/`agent_loop.py` 同样的 Protocol 改造。
> 3. `packages/core/__init__.py` 把 `ModelClient` 列进自己的公开 `__all__`——需要移除（已确
>    认仓库内没有任何代码用 `from core import ModelClient` 这种包级别引用，只有
>    `from core.model import ModelClient` 这种更具体的写法，移除零风险）。
> 4. 真正 `from core.model import ModelClient` 的调用方远不止 `builder.py`/`react_agent.py`/
>    `runtime.py` 三个，完整列表（已重新 grep 确认）：`apps/api/{agentgen.py,deepresearch.py,
>    evaluation.py,suggest.py,runtime.py}`、`packages/agents/{builder.py,react_agent.py,
>    subagent_tool.py}`、`packages/a2apeer/{demo_server.py,main.py}`、
>    `tests/{conftest.py,agents/test_builder.py,agents/test_react_agent.py,
>    core/test_agent.py,core/test_agent_loop.py,core/test_compaction.py,
>    core/test_real_model_selftest.py,apps/api/test_runtime.py,apps/api/test_api_routes.py}`。
> 下面的任务按这份更正后的完整清单重写。

### Tests for User Story 1 ⚠️ 先写，确认失败，再实现

- [X] T003 [P] [US1] 失败测试：一个只结构性满足 `ModelClientProtocol`（`model_name`/
      `last_stream_summary`/`acomplete`/`astream`/`acomplete_with_tools`/
      `astream_with_tools` 六个成员，不继承任何具体类）的假对象，`isinstance(fake,
      ModelClientProtocol)` 为真（`@runtime_checkable`），且能被
      `packages/core/agent_loop.py` 的 `execute_model_step` 正常调用（用这个假对象跑一次最
      小的无工具调用往返），写入 `tests/core/test_protocols.py`（文件已存在，新增一个测试函
      数，风格对齐文件里已有的 `_FakeSteerQueue`/`test_a_minimal_fake_satisfies_steer_queue`）

### Implementation for User Story 1

- [X] T004 [US1] 在 `packages/core/protocols.py` 新增 `ModelClientProtocol`（
      `@runtime_checkable`，风格对齐文件里已有的 `HistoryStore`/`ToolExecutor` 等
      Protocol；六个成员的精确签名见 data-model.md），写入 `packages/core/protocols.py`
      （依赖 T003）
- [X] T005 [US1] 改造 `packages/core/agent.py`：删除 `from .model import ModelClient`，
      构造函数的 `model_client: ModelClient` 参数标注改成 `model_client:
      ModelClientProtocol`（`from .protocols import ModelClientProtocol`），写入
      `packages/core/agent.py`（依赖 T004）
- [X] T006 [US1] 改造 `packages/core/agent_loop.py`：删除 `from .model import ModelClient`
      （保留 `from .pricing import estimate_cost` 不变——`pricing.py` 不搬家），
      `execute_model_step`/`run_tool_turn` 等全部函数的 `model_client` 参数标注改成
      `ModelClientProtocol`，写入 `packages/core/agent_loop.py`（依赖 T004）
- [X] T006a [US1] 改造 `packages/core/compaction.py`：删除 `from .model import ModelClient`，
      `summarize_history` 的 `model_client: ModelClient` 参数标注改成 `model_client:
      ModelClientProtocol`，写入 `packages/core/compaction.py`（依赖 T004）
- [X] T006b [US1] 改造 `packages/core/__init__.py`：删除 `from .model import ModelClient`
      这一行，`__all__` 列表里移除 `"ModelClient"`，写入 `packages/core/__init__.py`（依赖
      T005, T006, T006a）
- [X] T007 [US1] 把 `packages/core/{model.py,providers.py,model_catalog.py}` **三个**文件
      （不含 `pricing.py`）用 `git mv` 搬到 `packages/ai/` 下（文件名不变）；`model.py` 内部
      原本的 `from .errors import ModelError, SettingsError` 改成 `from core.errors import
      ModelError, SettingsError`（绝对导入，因为 `errors.py` 留在 `packages/core`）；三个文
      件之间原有的相对导入（如 `model.py` 的 `from .providers import get_provider_preset`）
      保持不变（依赖 T002, T006b）
- [X] T008 [US1] 更新全部直接 `from core.model import ModelClient`（或连带
      `FakeModelBackend`）的生产代码调用方，import 路径改成 `from ai.model import
      ModelClient`（`FakeModelBackend` 同理）：`apps/api/{agentgen.py,deepresearch.py,
      evaluation.py,suggest.py}`、`packages/agents/{builder.py,react_agent.py,
      subagent_tool.py}`、`packages/a2apeer/{demo_server.py,main.py}`（依赖 T007）
- [X] T009 [US1] 更新 `apps/api/runtime.py`：`from core.model import ModelClient` 改成
      `from ai.model import ModelClient`，`from core.model_catalog import
      default_compaction_token_limit` 改成 `from ai.model_catalog import
      default_compaction_token_limit`（依赖 T007）
- [X] T009a [US1] 更新全部直接 `from core.model import ModelClient`（或连带
      `FakeModelBackend`）的测试文件，import 路径改成 `from ai.model import ...`：
      `tests/conftest.py`、`tests/agents/{test_builder.py,test_react_agent.py}`、
      `tests/core/{test_agent.py,test_agent_loop.py,test_compaction.py,
      test_real_model_selftest.py}`、`tests/apps/api/{test_runtime.py,test_api_routes.py}`
      （`test_runtime.py` 另外还要把第 978 行局部 `from core.model_catalog import
      get_model_capabilities` 改成 `from ai.model_catalog import get_model_capabilities`）
      （依赖 T007）
- [X] T010 [US1] 把 `tests/core/{test_model.py,test_providers.py,test_model_catalog.py}` 三
      个文件用 `git mv` 搬到新建的 `tests/ai/` 目录下，文件内 `from core.model import ...`/
      `from core.providers import ...`/`from core.model_catalog import ...` 全部改成
      `from ai.model import ...`/`from ai.providers import ...`/`from ai.model_catalog
      import ...`，断言内容不改；`tests/core/test_pricing.py` **不移动**（`pricing.py` 留在
      `packages/core`，这个测试文件的 `core.pricing` 引用保持不变）（依赖 T007）
- [X] T010a [P] [US1] 更新 `packages/core/protocol.py` 第 110 行注释里的
      `core.model.ModelClient` 为 `ai.model.ModelClient`（纯文档准确性修正，不影响任何代码
      行为）
- [X] T011 [US1] 运行 `.venv/bin/python scripts/check_core_boundary.py`（确认
      `packages/core` 零违规）+ `.venv/bin/pytest -v`（全量——这次改动面横跨太多文件，不能只
      跑 `tests/ai/`/`tests/core/` 两个子目录，必须全量回归确认 004 feature 行为逐字不变、
      本次新发现的全部调用方改动没有破坏任何现状测试），确认全部通过（GREEN checkpoint）

**Checkpoint**：`packages/core` 和 provider/模型配置彻底解耦，边界零违规——这是 MVP。

---

## Phase 4: User Story 2 - Web 端可编辑的聊天 Provider 配置界面 (Priority: P2)

**Goal**：新增 `provider_configs` 表 + CRUD API + 前端页面/侧边栏入口，支持新增/编辑/删除/
激活聊天 provider 配置，改动对下一个新建任务立刻生效、不需要重启进程。

**Independent Test**：通过 API 新增一条配置并激活，构造一个新 `ChatRuntime` 任务，确认用了
这条配置；删除/取消激活后确认回退到环境变量配置。

### Tests for User Story 2 ⚠️ 先写，确认失败，再实现

- [X] T012 [P] [US2] 失败测试：`ChatStore.create_provider_config(name=..., purpose="chat",
      backend="anthropic", base_url=None, api_key="sk-test", model_name="claude-sonnet-5")`
      创建成功并可以被 `get_provider_config`/`list_provider_configs` 查到；
      `list_provider_configs(purpose="chat")` 只返回该 purpose 的行，写入
      `tests/apps/api/test_db.py`
- [X] T013 [P] [US2] 失败测试：`create_provider_config` 在 `purpose` 不是
      `"chat"`/`"embedding"` 之一、或 `purpose="chat"` 但 `backend` 缺失/不是
      `"anthropic"`/`"openai-compatible"`/`"mock"` 之一时拒绝（抛出清晰错误，不是数据库约
      束报错），写入 `tests/apps/api/test_db.py`
- [X] T014 [P] [US2] 失败测试：`_provider_config_row_to_dict`（或等价的序列化函数）返回的
      dict 里，密钥长度 ≤4 时整体是 `"****"`，否则只保留末 4 位、其余替换成 `*`；直接查数据
      库原始行，确认存的是完整明文（证明掩码只在序列化层），写入
      `tests/apps/api/test_db.py`
- [X] T015 [P] [US2] 失败测试：`set_provider_config_active(id, purpose="chat")`（或等价方
      法名）激活一条后，同 purpose 下此前激活的那条自动变为未激活；跨 purpose 的激活互不影
      响，写入 `tests/apps/api/test_db.py`
- [X] T016 [P] [US2] 失败测试：`POST /api/providers`（`purpose="chat"` 缺 `backend` → 400；
      `purpose="embedding"` 但传了 `backend` → 400）、`GET /api/providers` 响应体密钥已掩
      码、`PATCH /api/providers/{id}` 传 `{"active": true}` 后同 purpose 下其余行取消激
      活、`DELETE /api/providers/{id}` 成功 204/未知 id 404，写入
      `tests/apps/api/test_api_routes.py`
- [X] T017 [P] [US2] 失败测试：构造 `ChatRuntime`，新增并激活一条 `purpose="chat"` 的配置，
      对一个全新的 `task_id` 调用 `_get_agent()`，确认返回的 `Agent` 持有的 `ModelClient`
      使用了这条配置的 `model_name`/`api_key`；对此前已经调用过 `_get_agent()`（已缓存）的
      `task_id` 再次调用，确认返回同一个 `Agent` 实例（配置变更不影响已缓存任务）；删除/取
      消激活该配置后对另一个全新 `task_id` 调用 `_get_agent()`，确认回退到环境变量构造方
      式，写入 `tests/apps/api/test_runtime.py`

### Implementation for User Story 2

- [X] T018 [US2] 在 `apps/api/db.py` 的 `_SCHEMA` 新增 `provider_configs` 表（字段：`id`
      TEXT 主键、`created_at` TEXT、`name` TEXT、`purpose` TEXT、`backend` TEXT 可空、
      `base_url` TEXT 可空、`api_key` TEXT 非空、`model_name` TEXT 非空、`active` INTEGER
      默认 0），精确 DDL 见 data-model.md（依赖 T012）
- [X] T019 [US2] 在 `apps/api/db.py` 实现 `create_provider_config`（校验 `purpose` ∈
      `{"chat","embedding"}`；`purpose="chat"` 时校验 `backend` ∈
      `{"anthropic","openai-compatible","mock"}` 且非空，`purpose="embedding"` 时要求
      `backend` 为空，不满足则抛 `ValueError`/等价异常）+ `get_provider_config` +
      `list_provider_configs(purpose: str | None = None)` + `_provider_config_row_to_dict`
      （密钥掩码：长度 ≤4 → `"****"`，否则 `"*" * (len-4) + key[-4:]`），写入
      `apps/api/db.py`（依赖 T018, T013, T014）
- [X] T020 [US2] 在 `apps/api/db.py` 实现 `update_provider_config`（支持更新
      `name`/`base_url`/`api_key`/`model_name`）+ `set_provider_config_active`（同一事务
      内先把同 `purpose` 的其余行 `active` 置 0，再把目标行置 1）+
      `delete_provider_config`，写入 `apps/api/db.py`（依赖 T019, T015）
- [X] T021 [US2] 在 `apps/api/main.py` 新增 `CreateProviderConfigBody`/
      `UpdateProviderConfigBody`（Pydantic，字段见 contracts/provider-configs-api.md）+
      `POST /api/providers`、`GET /api/providers`（支持 `?purpose=` 查询参数）、`PATCH
      /api/providers/{id}`、`DELETE /api/providers/{id}` 四个路由，写入 `apps/api/main.py`
      （依赖 T020, T016）
- [X] T022 [US2] 在 `apps/api/runtime.py` 实现 `ChatRuntime._resolve_chat_model_client()`
      （查 `provider_configs` 表 `purpose="chat"` 且 `active=1` 的行，有则用其字段构造
      `ModelClient`，没有则 `ModelClient()` 无参构造）；`_get_agent()` 对一个还没有缓存
      `Agent` 的 `task_id`，用这个方法替代现状的 `self._client()` 单例缓存；`model_name`
      属性相应改为反映"如果现在构造新任务会用哪个模型"，写入 `apps/api/runtime.py`（依赖
      T021, T017）
- [X] T023 [US2] 运行 `.venv/bin/pytest tests/apps/api/test_db.py tests/apps/api/
      test_api_routes.py tests/apps/api/test_runtime.py -v`，确认全部通过（GREEN
      checkpoint）
- [X] T024 [P] [US2] 在 `apps/web/components/ui/icons.tsx` 新增 `KeyIcon`（复用文件里已有
      的 `Icon` 包装函数，lucide 风格钥匙图形）
- [X] T025 [P] [US2] 新增 `apps/web/lib/providers-api.ts`：`ProviderConfig`/
      `CreateProviderConfigInput` 类型（data-model.md）+ `createProviderConfig`/
      `listProviderConfigs`/`activateProviderConfig`/`updateProviderConfig`/
      `deleteProviderConfig` 函数，镜像 `lib/mcp-api.ts` 的 `fetchJson` 封装结构
- [X] T026 [US2] 新增 `apps/web/app/providers/page.tsx`：镜像 `app/mcp/page.tsx`
      的结构——已知具名 provider（`anthropic`/`openai`/`deepseek`/`moonshot`，前端硬编码,
      对应各自的 `backend`/默认 `base_url`）快捷新增卡片 + 通用新增表单（名字/用途选择
      chat 时额外出现后端类型下拉/服务地址/密钥/模型名）+ chat 用途配置列表（显示名字/后
      端类型/掩码密钥/激活状态，提供"激活"/删除按钮）+ 复用现状
      `ConfirmDeleteServerDialog` 模式新建 `ConfirmDeleteProviderDialog`（依赖 T024, T025）
- [X] T027 [US2] 更新 `apps/web/components/sidebar/Sidebar.tsx`：在现状 `/mcp` 链接附近新增
      `<Link href="/providers">`（`KeyIcon` + "Provider" 文案），写入
      `apps/web/components/sidebar/Sidebar.tsx`（依赖 T024）
- [X] T028 [US2] 更新 `apps/web/components/sidebar/SidebarClient.tsx`：`SidebarRail` 里新
      增对应的 `<Link href="/providers">` 图标按钮，写入
      `apps/web/components/sidebar/SidebarClient.tsx`（依赖 T024）
- [X] T029 [US2] 新增 `apps/web/app/providers/page.test.ts`，镜像 `app/mcp/page.test.ts`
      的测试风格，覆盖新增/激活/删除交互；运行 `cd apps/web && npx vitest run
      app/providers/page.test.ts`，确认通过（GREEN checkpoint）

**Checkpoint**：聊天 provider 可以通过界面完整管理，改动免重启生效——这是用户请求里"能在浏
览器里管起来 Provider"的核心价值落地。

---

## Phase 5: User Story 3 - Web 端的 Embedding Provider 配置界面 (Priority: P3)

**Goal**：复用 User Story 2 建好的整套机制（同一张表、同一组 API、同一个页面），让
`packages/memory` 的 `EmbeddingClient` 也支持通过界面配置、免重启生效。

**Independent Test**：新增并激活一条 `purpose="embedding"` 的配置，触发一次
`SemanticMemory` 的 embed 调用，确认用了这条配置；取消激活后确认回退到 `EMBED_*` 环境变量。

### Tests for User Story 3 ⚠️ 先写，确认失败，再实现

- [ ] T030 [P] [US3] 失败测试：`SemanticMemory.__init__` 接收一个零参可调用对象（而不是具
      体 `EmbeddingClient` 实例）作为 `embedder`；两次调用触发 embed 的方法之间，如果这个
      工厂函数返回了不同的 `EmbeddingClient` 实例，`SemanticMemory` 必须每次都用最新返回的
      那个（不缓存第一次的结果），写入 `tests/memory/test_semantic.py`
- [ ] T031 [P] [US3] 失败测试：`apps/api/db.py` 的默认 embedding 工厂函数（名称见 T032）在
      `provider_configs` 表存在 `purpose="embedding"` 且 `active=1` 的行时，返回一个用该
      行字段构造的 `EmbeddingClient`；没有该行时返回 `EmbeddingClient()`（无参，读环境变
      量），写入 `tests/apps/api/test_db.py`
- [ ] T032 [P] [US3] 失败测试：`ChatStore(path, embedder=<某个具体 EmbeddingClient 实例>)`
      （现状测试的既有构造方式）之后，`SemanticMemory` 内部每次调用那个工厂函数都返回同一
      个传入的实例（不会意外去查数据库）——验证非回归，写入 `tests/apps/api/test_db.py`

### Implementation for User Story 3

- [ ] T033 [US3] 改造 `packages/memory/semantic.py`：`SemanticMemory.__init__` 的
      `embedder` 参数类型从 `EmbeddingClient` 改成 `Callable[[], EmbeddingClient]`；4 处
      `self._embedder.embed(...)` 调用点改成 `self._embedder().embed(...)`，写入
      `packages/memory/semantic.py`（依赖 T030）
- [ ] T034 [US3] 在 `apps/api/db.py` 实现 `_resolve_embedding_client()`（查
      `provider_configs` 表 `purpose="embedding"` 且 `active=1` 的行，有则用其
      `model_name`/`api_key`/`base_url` 构造 `EmbeddingClient`，没有则 `EmbeddingClient()`
      无参构造）；`ChatStore.__init__` 构造 `SemanticMemory` 时，显式传入 `embedder` 存在
      则包成 `lambda: embedder`，否则传 `_resolve_embedding_client`，写入
      `apps/api/db.py`（依赖 T033, T031, T032）
- [ ] T035 [US3] 更新 `apps/web/app/providers/page.tsx`：embedding 用途分组改为功能完整
      （新增表单在 `purpose="embedding"` 时隐藏后端类型下拉，只保留模型名/密钥/可选服务地
      址），写入 `apps/web/app/providers/page.tsx`（依赖 T026, T034）
- [ ] T036 [US3] 运行 `.venv/bin/pytest tests/memory/test_semantic.py
      tests/apps/api/test_db.py -v`，确认全部通过（GREEN checkpoint）

**Checkpoint**：全部 3 个 User Story 独立可用，chat 和 embedding 两种用途的 provider 都能通
过同一个界面管理。

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T037 [P] 安全检查（research.md 决策 9）：核对 `apps/api/main.py`/`apps/api/db.py`
      全部涉及 `api_key` 的代码路径，确认没有任何日志/trace/错误信息会意外带出完整或部分
      明文密钥；核对前端 `apps/web/app/providers/page.tsx`/`lib/providers-api.ts` 没有把
      密钥打印到 console 或遗留在网络请求的非预期字段里
- [ ] T038 运行全量回归：`.venv/bin/pytest`、`.venv/bin/python
      scripts/check_core_boundary.py`、`cd apps/web && npx vitest run`，和 T001 记录的基
      线对比，确认 0 回归、测试数只增不减
- [ ] T039 [P] 执行 quickstart.md 的全部 7 个验证场景（含真机验证：打开
      http://localhost:3010/，核实侧边栏两处入口、新增/激活/删除交互、新任务确实使用激活
      配置）
- [ ] T040 [P] 更新项目 memory（`project_opentalos_python_rebuild.md` 追加本次 shipped 记
      录 + `MEMORY.md` 索引行同步）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup（Phase 1）**：无依赖，立即开始
- **Foundational（Phase 2）**：依赖 Setup 完成——阻塞全部 User Story
- **User Story 1（Phase 3）**：依赖 Foundational 完成；**MVP**，独立可交付
- **User Story 2（Phase 4）**：依赖 User Story 1 完成（CRUD/免重启生效需要 `packages/ai`
  已经搬好、`ModelClientProtocol` 已经就位——`apps/api/runtime.py` 的改动基于 User Story 1
  已经改过的 import 路径）
- **User Story 3（Phase 5）**：依赖 User Story 2 完成（复用同一张表/同一组 API/同一个页
  面，`page.tsx` 是在 User Story 2 新建的文件基础上追加 embedding 分组的功能）
- **Polish（Phase 6）**：依赖全部 User Story 完成

### Within Each User Story

- 测试任务必须先写、先确认失败（RED），再写实现任务（GREEN）
- 同一 Story 内，数据层（db.py）先于路由层（main.py）先于运行时集成层（runtime.py/
  semantic.py）先于前端

### Parallel Opportunities

- Phase 3 的 T003 是唯一的测试任务，无需并行协调
- Phase 4 的 T012-T017 六个测试任务可以并行编写（不同断言，部分共享 `test_db.py` 文件但互
  不冲突可以顺序小步提交）；T024（图标）和 T025（API client）可以与后端任务（T018-T023）并
  行开发，因为它们不互相阻塞直到 T026 把两者接起来
- Phase 5 的 T030-T032 三个测试任务可以并行编写

---

## Parallel Example: User Story 2 的测试

```bash
# 六个测试任务可以并行编写（主要分布在 test_db.py，部分在 test_api_routes.py/test_runtime.py）：
Task: "provider_configs 基础 CRUD 的失败测试"
Task: "purpose/backend 枚举校验的失败测试"
Task: "密钥掩码的失败测试"
Task: "激活互斥的失败测试"
Task: "API 路由（含 400/404）的失败测试"
Task: "ChatRuntime 免重启生效的失败测试"
```

---

## Implementation Strategy

### MVP First（仅 User Story 1）

1. 完成 Phase 1：Setup
2. 完成 Phase 2：Foundational
3. 完成 Phase 3：User Story 1
4. **STOP and VALIDATE**：`scripts/check_core_boundary.py` 零违规 + 004 feature 全部测试通
   过——这是一个完整、可独立合并的架构改进，即使 User Story 2/3 还没开始也有价值

### Incremental Delivery

1. Setup + Foundational → 基础就绪
2. User Story 1（包拆分）→ 独立验证 → 可以单独合并
3. User Story 2（聊天 provider CRUD + 界面）→ 独立验证 → 用户已经能通过界面管理聊天模型
4. User Story 3（embedding provider）→ 独立验证 → "统一管理所有 Provider" 的完整范围交付
5. Polish → 全量回归 + 安全检查 + memory 更新

### Parallel Team Strategy

1. 团队一起完成 Setup + Foundational + User Story 1（这是后续一切的地基，建议不拆给多人，
   顺序完成）
2. User Story 1 完成后：
   - 开发者 A：User Story 2 后端（db.py/main.py/runtime.py）
   - 开发者 B：User Story 2 前端（icons.tsx/providers-api.ts/page.tsx/sidebar），在 A 的
     API 契约（contracts/provider-configs-api.md）基础上可以提前开工，不需要等 A 写完实现
3. User Story 2 完成后，一人接着做 User Story 3（工作量小，复用 User Story 2 的全部基础设
   施）

---

## Notes

- `[P]` 任务 = 不同文件、无依赖
- `[Story]` 标签把任务对应回 spec.md 的 User Story 编号，便于追溯
- User Story 2 → 3 → (Polish) 是本次任务图里唯一的强顺序依赖链（已在 Dependencies 一节说明
  原因），User Story 1 是公认的地基，不代表其余 Story 之间存在隐藏耦合
- 实现前先验证测试确实失败（RED）
- 建议每个 User Story 完成后提交一次
- 可以在任意 Checkpoint 处停下独立验证对应 Story
- 避免：模糊任务描述、同文件冲突的并行标记、破坏 Story 独立性的跨 Story 依赖（已显式说明的
  除外）
