# Implementation Plan: 独立的 Provider 包 + Web 端配置界面

**Branch**: `005-provider-package-ui` | **Date**: 2026-10-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-provider-package-ui/spec.md`

## Summary

把 004 feature 放进 `packages/core` 的 provider 注册表/模型能力目录/`ModelClient`
（`providers.py`/`model_catalog.py`/`model.py`/`pricing.py`）整体搬到新的独立顶层包
`packages/ai`，像 pi 的 `packages/ai` 相对 `packages/agent` 那样和 agent 循环编排解耦；
`packages/core/agent.py`/`agent_loop.py` 改成依赖 `packages/core` 新增的
`ModelClientProtocol`（`typing.Protocol`），不直接 import 新包，保持 `scripts/
check_core_boundary.py` 零违规。在此基础上新增一张 `provider_configs` 数据库表，支持通过
Web UI（新的侧边栏入口 + 页面）新增/编辑/删除/激活聊天和 embedding 两种用途的 provider 配
置——激活后的配置立刻对"下一个新建的任务/下一次 embedding 调用"生效，不需要重启后端进程；没
有任何激活配置时完整回退到现状的环境变量行为（004 feature 的 chat 配置、现状的 `EMBED_*`
embedding 配置）。三项范围经 `/speckit-specify` 内联的 Clarifications 会话确认，全部选择了比
Recommended 更大范围的选项。

## Technical Context

**Language/Version**: Python 3.12+（后端）+ TypeScript/Next.js（前端，与现状 `apps/web` 一
致）。

**Primary Dependencies**: 不新增任何第三方依赖。后端复用 004 feature 已有的 `openai`/
`anthropic` SDK；前端复用现状 `apps/web` 已有的 fetch 封装模式（`lib/mcp-api.ts` 式的
`fetchJson` helper）和 UI 组件（`PageSkeleton`/图标组件）。

**Storage**: 新增一张 SQLite 表 `provider_configs`（`apps/api/db.py` 的 `_SCHEMA`），字段/
校验规则见 data-model.md。和现状 `mcp_servers`/`agent_roles` 用同一个物理数据库文件
（`.data/chat.db`），同一套 `ChatStore._connect()` 连接管理方式。

**Testing**: pytest（后端，`.venv/bin/pytest`）+ Vitest（前端，`cd apps/web && npx vitest
run`，沿用 `apps/mcp/page.test.ts` 的既有测试风格）。

**Target Platform**: 本仓库现有的 `apps/api`（FastAPI，:8400）+ `apps/web`（Next.js，
:3010）两个进程，不涉及新部署目标。

**Project Type**: 单仓库多 Python 包 + 一个 Next.js 前端应用。本次改动范围横跨四个层面：
(1) `packages/core` 新增 Protocol、移除对 `model.py` 等文件的直接依赖；(2) 新建顶层包
`packages/ai`（原 `packages/core/{model.py,providers.py,model_catalog.py,pricing.py}` 的新
家）；(3) `apps/api`（新表、新路由、`ChatRuntime`/`SemanticMemory` 的免重启生效改造）；
(4) `apps/web`（新页面、新侧边栏入口、新图标）。

**Performance Goals**: 不是本次关注点；唯一的行为要求是"新任务/新 embed 调用必须读到最新激
活配置"，这是正确性要求，不是性能指标。

**Constraints**: `scripts/check_core_boundary.py` 必须在拆分后依然零违规（FR-002，不可协商
的硬约束）；004 feature 交付的全部能力行为必须逐字保持不变（FR-004/SC-002）；API 响应/界面
任何时候都不能返回完整明文密钥（FR-011/SC-005）；没有任何激活配置时必须完整回退到现状环境
变量行为，不报错（FR-012/SC-006）。

**Scale/Scope**: 新建顶层包 `packages/ai`（4 个文件原样搬入 + `__init__.py`）；
`packages/core` 修改 2 个文件（`protocols.py` 新增 Protocol、`agent_loop.py`/`agent.py` 改类
型标注，预计各 <10 行）；`apps/api` 新增约 150 行（db.py 的表+CRUD、main.py 的路由）+ 改造
`runtime.py`/`packages/memory/semantic.py` 的免重启生效逻辑（预计各 20-30 行）；`apps/web` 新
增 1 个页面文件（参照 `mcp/page.tsx` 的 364 行规模）+ 1 个 API client 文件（参照
`mcp-api.ts`）+ 2 处侧边栏改动 + 1 个新图标。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

依据 `.specify/memory/constitution.md` v1.0.0 的五条原则逐一检查：

- **I. TDD（不可协商）**：`/speckit-tasks` 产出的每个任务都先写测试再实现；"行为必须逐字不
  变"的搬移类任务（User Story 1）要求先把 004 feature 的现有测试原样搬到新位置跑通，再做任
  何额外改动。✅ 通过。
- **II. 代码规范一致性**：Python 遵循 ruff/black；TypeScript 遵循现状 `apps/web` 的 ESLint
  配置和既有组件风格（直接复用 `mcp/page.tsx`/`mcp-api.ts` 的代码风格，不引入新模式）。
  ✅ 通过。
- **III. 输入必须校验**：新增的 `POST /api/providers`（及等价路由）必须校验 `purpose`/
  `backend`（仅 chat 需要）等枚举字段，参照现状 `CreateMCPServerBody` 的 Pydantic 校验模
  式；API 密钥等敏感输入在写入数据库前不需要额外格式校验（密钥格式由各家服务商自己定义，这
  个仓库不替用户判断"像不像一个合法密钥"）。✅ 通过。
- **IV. 简洁至上，拒绝过度工程**：新增的 provider 配置表复用现状 `mcp_servers`/
  `agent_roles` 已经验证过的"列表+枚举+启用标记"模式，不发明新的数据建模方式；chat/
  embedding 两种用途共用同一张表（`purpose` 列区分），不建两张结构几乎相同的表。✅ 通过。
- **V. 接口文档完整性**：新增的全部路由在 `contracts/` 下有完整的请求/响应契约；
  `data-model.md` 列出 `provider_configs` 表的全部字段和校验规则。✅ 通过。

无违反项。**说明性记录**（非违规申诉）：这次范围比典型 feature 大（横跨 4 个层面），
Complexity Tracking 表格记录了"为什么不拆成多个 feature"的理由。

**Post-Design Re-check（Phase 1 完成后复查）**：`data-model.md` 定稿的 `provider_configs` 表
字段都能在 `contracts/` 里找到对应的请求/响应契约；`research.md` 的每条决策都标注了对应的
Functional Requirement；`quickstart.md` 覆盖全部 3 个 User Story 的 Acceptance Scenarios。五
条原则依然全部通过，无新增违规。

## Project Structure

### Documentation (this feature)

```text
specs/005-provider-package-ui/
├── plan.md               # This file (/speckit-plan command output)
├── research.md           # Phase 0 output (/speckit-plan command)
├── data-model.md         # Phase 1 output (/speckit-plan command)
├── quickstart.md         # Phase 1 output (/speckit-plan command)
├── contracts/            # Phase 1 output (/speckit-plan command)
│   ├── model-client-protocol.md
│   ├── provider-configs-api.md
│   └── live-reload.md
└── tasks.md               # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
packages/ai/                   # 新建顶层包（原 packages/core 的 4 个文件原样搬入）
├── __init__.py
├── client.py                   # 原 packages/core/model.py 原样搬入（文件名可以保持
│                               #     model.py，留给 /speckit-tasks 决定；内部逻辑不变）
├── providers.py                 # 原 packages/core/providers.py 原样搬入
├── model_catalog.py              # 原 packages/core/model_catalog.py 原样搬入
└── pricing.py                     # 原 packages/core/pricing.py 原样搬入；
                                   # 4 个文件内部的 `from .errors import ...` 改成
                                   # `from core.errors import ...`（唯一需要改的 import，
                                   # 其余文件间相对引用不变）

packages/core/
├── protocols.py              # 改：新增 ModelClientProtocol（acomplete/astream/
│                             #     acomplete_with_tools/astream_with_tools/
│                             #     last_stream_summary/model_name 六个成员），风格对齐
│                             #     文件里已有的 HistoryStore/ToolExecutor 等 Protocol
├── agent.py                   # 改：`from .model import ModelClient` 删除，
│                              #     `model_client: ModelClient` 参数标注改成
│                              #     `model_client: ModelClientProtocol`（from .protocols
│                              #     import ModelClientProtocol）
└── agent_loop.py                # 改：同上，`execute_model_step`/`run_tool_turn` 等函数
                                 #     的 model_client 参数标注改成 ModelClientProtocol

packages/agents/
├── builder.py                 # 改：`from core.model import ModelClient` 改成
│                             #     `from ai.client import ModelClient`（或等价模块名，
│                             #     留给 /speckit-tasks 定稿）
└── react_agent.py              # 改：同上

apps/api/
├── db.py                      # 改：_SCHEMA 新增 provider_configs 表；新增
│                             #     create/list/get/update/delete_provider_config 等 CRUD
│                             #     方法（镜像现状 mcp_servers 的方法命名/结构）；
│                             #     ChatStore.__init__ 构造 SemanticMemory 时改用一个
│                             #     "按需解析当前激活 embedding 配置"的工厂函数，不再传一
│                             #     个构造时就固定下来的 EmbeddingClient 实例
├── main.py                    # 改：import 路径从 `mcp.client` 风格改成新包路径（如
│                             #     `from ai.client import ...`）；新增
│                             #     POST/GET/PATCH/DELETE /api/providers 等路由（镜像
│                             #     mcp_servers 路由结构），响应体对密钥做掩码
└── runtime.py                  # 改：import 路径更新；`_get_agent()` 构造 `ModelClient`
                                #     前，先查一次 provider_configs 表有没有激活的 chat 配
                                #     置，有则用它的字段构造 ModelClient，没有则保持现状
                                #     "读环境变量"的构造方式；这次改动让 ModelClient 不再是
                                #     `ChatRuntime` 级别的永久单例，而是每个新任务（第一次
                                #     调用 _get_agent 时）重新解析一次（已有任务缓存
                                #     self._agents 不受影响，不会反复重建）

packages/memory/
└── semantic.py                 # 改：SemanticMemory.__init__ 的 embedder 参数类型从具体的
                                 #     EmbeddingClient 实例改成一个零参可调用对象
                                 #     Callable[[], EmbeddingClient]（惰性工厂）；4 处
                                 #     self._embedder.embed(...) 调用点改成
                                 #     self._embedder().embed(...)

apps/web/
├── lib/
│   └── providers-api.ts         # 新增：fetchJson 封装的 CRUD 客户端函数，镜像
│                                #     lib/mcp-api.ts 的结构
├── app/providers/
│   └── page.tsx                  # 新增：Provider 配置页面，镜像 app/mcp/page.tsx 的结构
│                                 #     （quick-add 卡片 + 通用表单 + 列表 + 启用/激活/删
│                                 #     除 + 确认删除弹窗），按 purpose 分 chat/embedding
│                                 #     两个分组展示
├── components/sidebar/
│   ├── Sidebar.tsx                # 改：新增一条 `<Link href="/providers">` 导航项
│   └── SidebarClient.tsx           # 改：SidebarRail 里新增对应的图标按钮（这是本仓库
│                                  #     memory 里记录过的"两处都要改"的现成教训）
└── components/ui/
    └── icons.tsx                    # 改：新增一个 KeyIcon（lucide 风格，复用文件里已有
                                     #     的 Icon 包装函数）

tests/core/
├── test_protocols.py            # 改：新增 ModelClientProtocol 的结构性满足断言（如果
│                                #     这个文件存在；否则在 test_model.py 近旁新增）
├── test_agent.py / test_agent_loop.py  # 改：确认用 ModelClientProtocol 类型标注后现有
│                                       #     测试（通常用假对象/scripted_client）仍然满足
│                                       #     类型要求，无需改断言内容

packages/ai/ 对应测试目录（具体路径留给 /speckit-tasks，例如 tests/ai/）：
└── test_model.py / test_providers.py / test_model_catalog.py  # 004 feature 的现状测试
    文件原样搬入新目录，import 路径从 `core.model`/`core.providers`/`core.model_catalog`
    改成新包路径，断言内容不变（FR-004/SC-002 的字面验收标准）

tests/apps/api/
├── test_db.py                   # 改：新增 provider_configs 表的 CRUD 单测
├── test_api_routes.py            # 改：新增 /api/providers 路由的集成测试（含密钥掩码断
│                                #     言）
└── test_runtime.py                # 改：新增"激活配置立刻对下一个新任务生效""没有激活配
                                   #     置时回退环境变量"两类集成测试

apps/web/app/providers/
└── page.test.ts                  # 新增：镜像 app/mcp/page.test.ts 的测试风格
```

**Structure Decision**: 单仓库多包结构整体不变，新增一个顶层包 `packages/ai`。前端沿用现状
Next.js App Router 的按路由分目录约定（`app/providers/`），不引入新的前端架构模式。

## Complexity Tracking

> 无 Constitution 违规需要申诉；以下表格仅作说明性记录。

| 决策 | 为什么需要 | 更简单的替代方案被否决的原因 |
|------|-----------|-----------------------------|
| 一次 feature 里同时做"包拆分"+"新 CRUD 系统"+"两处免重启改造"，而不是拆成 2-3 个更小的 feature | 用户的 Clarifications 答案（可编辑 CRUD + 立刻生效 + 收编 embedding）让这三件事在技术上紧密耦合——没有包拆分（User Story 1），新 UI 没有稳定的数据源可以指向；没有免重启改造，CRUD 做出来也只是"看起来能改、实际上要重启才生效"的半成品，不满足用户明确选择的 Clarifications 答案 | 拆成多个 feature 会导致中间状态"CRUD 界面能用但改了不生效"这种半成品被短暂合并，不符合"目标驱动式开发"要求的"先定义验收标准，一次迭代直至验证通过"——用户已经在 Clarifications 阶段把完整范围定下来了 |
| `SemanticMemory` 的 embedder 从固定实例改成惰性工厂（`Callable[[], EmbeddingClient]`），而不是让 `SemanticMemory`/`ChatStore` 自己持有数据库连接去查 | `EmbeddingClient` 本身构造极轻（只存几个字符串，不做 I/O），工厂模式只需要注入一个闭包，不需要让 `packages/memory`（目前对数据库一无所知）新增一个数据库依赖；闭包由 `apps/api/db.py` 这个已经持有数据库连接的地方提供，符合现状的依赖方向 | 让 `SemanticMemory` 直接查数据库需要给 `packages/memory` 引入新的数据库依赖，扩大了这个包的职责边界，且 `packages/memory` 现状设计是"纯粹的记忆逻辑，不关心配置从哪来"——这个边界值得保留 |
