# Implementation Plan: 对齐 pi 的统一模型 Provider 功能

**Branch**: `004-model-provider-registry` | **Date**: 2026-10-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-model-provider-registry/spec.md`

## Summary

把 `packages/core/model.py` 现状"只有 3 个 provider 字符串、鉴权全靠单一通用
`MODEL_API_KEY`、对模型能力一无所知"的局面，对齐 `earendil-works/pi` `packages/ai` 的架构模
式（但不是逐一搬运其全部约 40 个具名 provider/OAuth/图像/分类器子系统，范围已经在 spec.md 的
Assumptions 里明确排除）：新增一个具名 provider 注册表（`anthropic`/`openai`/`mock` 之外，再加
至少两个真实场景已经用到的 OpenAI 兼容服务商，如 DeepSeek、Moonshot/Kimi），每个具名 provider
声明自己的默认 base_url、专属密钥环境变量名、是否支持流式用量上报；新增一个小型手工维护的模型
能力目录（上下文窗口/是否支持工具调用/是否支持 thinking，不含任何价格数据）；把这个目录接入
`apps/api/runtime.py`，在调用方未显式指定 `compaction_token_limit` 时自动算一个默认压缩阈值。
三项范围经 `/speckit-specify` 内联的 Clarifications 会话确认，全部选择"全做"（Recommended
Option A）。

## Technical Context

**Language/Version**: Python 3.12+（与 001/002/003 一致，`.venv` 实际跑 Python 3.13.5）

**Primary Dependencies**: 不新增任何第三方依赖——`openai`/`anthropic` 两家 SDK 已经是现状依赖，
新增的注册表/目录都是纯 Python `dataclass` + 字典，不需要额外的包。

**Storage**: N/A——注册表和能力目录都是进程内的静态数据结构（模块级常量字典），不落盘、不建表；
`apps/api/db.py` 的 schema 不受影响。

**Testing**: pytest（`.venv/bin/pytest`）。沿用 `tests/core/test_model.py`（已确认存在）的测试
风格——构造参数+环境变量组合断言的纯单元测试，不依赖真实网络；新增的 provider 注册表/能力目录
测试同样是纯单元测试（断言默认值解析结果），不需要真实发请求。`apps/api/runtime.py` 的压缩阈
值默认值接入点需要一条集成测试（构造 `ChatRuntime` 不传 `compaction_token_limit`、
`model_name` 命中目录，断言 `Agent.compaction_token_limit` 的实际生效值）。

**Target Platform**: 本仓库现有后端进程（`apps/api`），不涉及新部署目标。

**Project Type**: 单仓库多 Python 包。本次改动范围：`packages/core` 新增两个模块（供应商注册
表、模型能力目录）+ 改造 `model.py` 消费它们；`apps/api/runtime.py` 新增一处压缩阈值默认值解
析；`apps/api/main.py` 配合调整一行（让 `COMPACTION_TOKEN_LIMIT` 未设置时不再强制塞一个硬编码
字面量，把决定权交给 `runtime.py` 的新逻辑）。不涉及 `packages/agents`/`packages/tool` 等其他
包。

**Performance Goals**: 不是本次关注点——注册表/目录查询都是 O(1) 字典查找，不涉及网络 I/O。

**Constraints**: `scripts/check_core_boundary.py` 必须保持零违规（新增的两个模块都在
`packages/core` 内部，不引入对其他 `packages/*` 的 import）；`packages/core/pricing.py` 现状
"价格只从 `MODEL_PRICES` 来、查不到返回 `None`"的行为必须逐字保持不变（FR-007，Clarifications
已确认）；现状 `anthropic`/`openai-compatible`/`mock` 三个 provider 的全部现有行为、以及现状仅
设置通用 `MODEL_API_KEY` 的部署方式，必须 100% 保持不变（FR-010/SC-002）。

**Scale/Scope**: 新增 2 个文件（`packages/core/providers.py`、
`packages/core/model_catalog.py`，预计各 100-150 行，符合"文件保持短小聚焦"的既有约定）；修改
`packages/core/model.py`（`ModelClient.__init__` 的密钥/base_url 解析逻辑、
`create_model_backend` 的 provider 识别范围、`OpenAICompatibleBackend` 新增一个可选的声明式
"是否支持流式用量上报"构造参数）；修改 `apps/api/runtime.py`（`_get_agent()` 里压缩阈值默认值
解析，约 5-10 行）+ `apps/api/main.py`（1 行）。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

依据 `.specify/memory/constitution.md` v1.0.0 的五条原则逐一检查：

- **I. TDD（不可协商）**：`/speckit-tasks` 产出的每个任务都先写测试再实现；新增的两个模块
  （provider 注册表/模型能力目录）都是纯函数+静态数据，天然适合先写断言期望值的测试；
  `apps/api/runtime.py` 的压缩阈值接入点需要先写一个"不传 compaction_token_limit、断言生效值
  来自目录换算"的失败测试。✅ 通过。
- **II. 代码规范一致性**：纯 Python 改动，遵循现有 ruff/black 风格；不涉及前端。✅ 通过。
- **III. 输入必须校验**：`MODEL_PROVIDER` 设置成未注册的名字时必须在构造阶段报清晰错误并列出
  可用列表（FR-005）——这正是"系统边界输入必须校验、拒绝静默放行"的体现。✅ 通过。
- **IV. 简洁至上，拒绝过度工程**：新增的具名 provider 全部复用现状 `OpenAICompatibleBackend`
  的请求/响应解析逻辑，不为每个服务商新增一个后端类；模型能力目录是手工维护的小型字典，不引入
  任何自动从外部数据源同步的构建管线（pi 自己有，本次明确排除）；没有为"将来可能需要"的能力预
  留配置项（比如价格数据明确排除在目录之外）。✅ 通过。
- **V. 接口文档完整性**：provider 注册表条目、模型能力目录条目的字段都会在 `data-model.md` 里
  有完整说明；新增的公共函数（如 `default_compaction_token_limit`）需要清晰 docstring 说明"模
  型未知时的兜底行为"这个非显而易见的边界情况。✅ 通过。

无违反项，不需要在 Complexity Tracking 表格里做"违规申诉"；下方表格仅作说明性记录。

**Post-Design Re-check（Phase 1 完成后复查）**：`data-model.md` 定稿的全部新增类型都能对应到
`contracts/` 里的契约；`research.md` 的每条决策都标注了对应的 Functional Requirement；
`quickstart.md` 的验证场景覆盖全部 3 个 User Story 的 Acceptance Scenarios。五条原则依然全部通
过，无新增违规。

## Project Structure

### Documentation (this feature)

```text
specs/004-model-provider-registry/
├── plan.md               # This file (/speckit-plan command output)
├── research.md           # Phase 0 output (/speckit-plan command)
├── data-model.md         # Phase 1 output (/speckit-plan command)
├── quickstart.md         # Phase 1 output (/speckit-plan command)
├── contracts/            # Phase 1 output (/speckit-plan command)
│   ├── provider-registry.md
│   └── model-catalog.md
└── tasks.md               # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
packages/core/
├── providers.py              # 新增：具名 provider 注册表——ProviderPreset dataclass
│                             #     （default_base_url/api_key_env_var/supports_stream_usage/
│                             #     可选的 reasoning 字段名覆盖）+ 模块级注册表字典 + 查询/
│                             #     "未知名字报清晰错误并列出可用列表"的函数
├── model_catalog.py           # 新增：模型能力目录——ModelCapabilities dataclass
│                              #     （context_window/supports_tools/supports_thinking）+
│                              #     模块级字典 + 查询函数（未知模型返回 None）+
│                              #     default_compaction_token_limit(model_name) -> int
│                              #     （已知模型按上下文窗口算默认值；未知模型回退现状的 16000
│                              #     legacy 默认值，不回归）
└── model.py                   # 改：ModelClient.__init__ 的 api_key/base_url 解析改用
                                #     providers.py 的注册表（优先级：显式参数 > 具名 provider
                                #     专属环境变量 > 通用 MODEL_API_KEY）；create_model_backend
                                #     识别的 provider 字符串范围从 providers.py 的注册表动态
                                #     获取，而不是硬编码的 if/elif；OpenAICompatibleBackend 新
                                #     增可选构造参数接收声明式的"是否支持流式用量上报"，提供时
                                #     跳过现状的反应式学习（_stream_usage_enabled 首次失败才降
                                #     级）；_build_call_kwargs 读取
                                #     preset.reasoning_param_name（为 None 时继续用字面量
                                #     "reasoning_effort"）决定请求体里推理强度字段叫什么名字

apps/api/
├── runtime.py                 # 改：_get_agent() 构造 Agent 前，若 self._compaction_token_limit
│                              #     为 None，调用 model_catalog.default_compaction_token_limit
│                              #     (self._client().model_name) 得到一个保证非 None 的默认值
│                              #     （已知模型用目录算出来的数，未知模型回退现状 16000）
└── main.py                     # 改：create_app() 默认构造 ChatRuntime 时，
                                 #     compaction_token_limit 不再无条件塞
                                 #     int(os.environ.get("COMPACTION_TOKEN_LIMIT", "16000"))
                                 #     这个硬编码兜底——改成环境变量未设置时传 None，把"用什么默
                                 #     认值"的决定权交给 runtime.py 的新逻辑（环境变量显式设置时
                                 #     继续原样生效，不变）

tests/core/
├── test_providers.py            # 新增：provider 注册表的查询/校验/未知名字报错断言
├── test_model_catalog.py          # 新增：能力目录查询（已知/未知模型）+
│                                 #     default_compaction_token_limit 断言
└── test_model.py                   # 改：ModelClient 的 api_key/base_url 解析断言跟着新优先级
                                   #     调整；新增针对具名 provider 的构造断言；现状
                                   #     anthropic/openai-compatible/mock 的既有断言必须继续通
                                   #     过（不回归）

tests/apps/api/
└── test_runtime.py                  # 改：新增一条"不传 compaction_token_limit、model_name 命
                                    #     中目录"的集成测试
```

**Structure Decision**: 单仓库多包结构不变，完全落在既有目录布局内；不新增顶层目录。
`packages/core` 新增的 2 个文件都保持"文件保持短小聚焦"的既有约定，职责单一（注册表 vs 能力目
录），不合并成一个大文件。

## Complexity Tracking

> 无 Constitution 违规需要申诉；以下表格仅作说明性记录。

| 决策 | 为什么需要 | 更简单的替代方案被否决的原因 |
|------|-----------|-----------------------------|
| provider 注册表和模型能力目录拆成两个独立文件（而非合并进 `model.py` 或合并成一个文件） | 两者语义独立：注册表管"怎么连接到这个服务商"，目录管"这个模型能做什么"——一个具名 provider 下可能有多个不同能力的模型（比如同一个 OpenAI 账号下 gpt-4o 和 gpt-4o-mini 能力不同），二者不是一一对应关系，合并会让数据结构表达不清楚这种多对多关系 | 合并成一个文件表面上"更省事"，但会让 `model.py` 进一步膨胀（现状已经 739 行），且混淆"连接配置"和"能力元数据"两个不同关注点 |
| 新增具名 provider 全部复用 `OpenAICompatibleBackend`（而非每个新服务商写一个独立后端类） | 这些服务商在 API 形状上都是标准 OpenAI Chat Completions 兼容协议，现状 `openai-compatible` 已经验证过这套解析逻辑能对接任意兼容端点；额外的后端类只会是对同一套逻辑的重复 | 每个服务商一个后端类更"看起来规范"，但引入纯粹的样板代码重复，违反宪法原则 IV |
