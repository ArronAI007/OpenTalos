# Implementation Plan: Agent Loop 核心边界隔离 + 真实模型自测

**Branch**: `001-core-isolation-selftest` | **Date**: 2026-10-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-core-isolation-selftest/spec.md`

## Summary

`packages/core` 目前通过直接 `import` 依赖 `context`（上下文组装/token 估算/输出截断）、`tool`
（工具注册与执行）、`memory`（工作记忆）、`observability`（trace 记录与指标）四个同级包。本次工作
要把这四个依赖全部移除，同时保留 core 现在实际承担的能力（agent loop 编排、消息流转、工具调用的识
别与校验、阶段性事件广播、steering/follow-up 的排队与打断、协议类型定义）。技术方案：在
`packages/core` 内部为每一种被依赖的能力定义一个 `typing.Protocol`（结构化类型，不需要被依赖方显式
继承），核心的类/函数只接受满足 Protocol 形状的对象（由调用方——`packages/agents`、
`apps/api/runtime.py`——构造并注入），不再在 core 内部直接 `import`/构造具体实现。这个模式在仓库里
已有先例（`packages/context/message.py` 的 `MessageLike` Protocol，让 `context` 包不需要依赖
`core.ChatMessage`），这次是把同一个模式反过来用在 core 身上。这其中包括把 steering/follow-up 的
"排队"逻辑（现在手写在 `packages/agents/react_agent.py` 里）正式下沉进 `agent_loop.py`（经
`/speckit-analyze` 发现这是 FR-002 的一个真实缺口，见 research.md 决策 5）。另外新增一个边界检查
脚本（静态扫描 `packages/core` 的导入语句）和一条会真实调用大模型的 pytest 测试（无凭据时自动跳
过）。

## Technical Context

**Language/Version**: Python 3.12+（`pyproject.toml` 的 `requires-python = ">=3.12"`，`.venv` 实
际跑在 Python 3.13.5）

**Primary Dependencies**: `packages/core` 自身已经直接依赖的第三方库——`openai`、`anthropic`（两家
模型 SDK）、`pydantic`（`RuntimeSettings`/`ChatMessage` 等）、`python-dotenv`（加载 `.env`）；本次
不新增任何第三方依赖，新增的只是 `packages/core` 内部的 `typing.Protocol` 定义和一个独立的边界检
查脚本（标准库 `ast`/`pathlib` 足够，不需要额外的静态分析库）。

**Storage**: N/A（这次不涉及任何持久化数据结构变更）

**Testing**: pytest + pytest-asyncio（`.venv/bin/pytest`），新增的真实模型自测用
`pytest.mark.skipif` 按环境变量是否配置自动跳过，与 `tests/memory/test_embedding.py` 对
`EMBED_API_KEY` 未配置时的降级测试风格一致

**Target Platform**: 本仓库现有的后端进程（`apps/api`，macOS/Linux 均可运行），不涉及新的部署目标

**Project Type**: 单仓库多 Python 包（`packages/*` + `apps/api`），这次改动范围限定在
`packages/core`（重构）+ 新增一个独立的边界检查脚本 + `tests/core/` 下新增/修改测试；`packages/
agents`、`apps/api/runtime.py` 需要做配合性的"调用点改造"（构造并注入 core 新增的 Protocol 实现），
但它们本身不受"不能依赖其他 packages/*"这条约束（那条约束只对 `packages/core` 生效）。

**Performance Goals**: 边界检查脚本必须能在不超过几秒的时间内扫完 `packages/core` 全部源文件（文件
数量级在十个左右，静态文本扫描，性能不是关注点）；真实模型自测必须在 spec 的 SC-003 要求的 60 秒
内完成一次真实模型往返

**Constraints**: 真实模型自测依赖网络访问和真实 API 凭据，属于本质上不可全程确定性的测试——必须用
`skipif` 保证本机无凭据时不污染常规测试结果；边界检查必须对"未来才出现的新 `packages/*` 目录"同样
有效（白名单而非黑名单逻辑）

**Scale/Scope**: `packages/core` 当前 8 个源文件（约 \~800 行，不含测试），本次改动预计触及其中 2
个文件（`agent.py`、`agent_loop.py`）+ 新增 1-2 个文件（Protocol 定义、可能拆成独立模块）；配合性
改造涉及 `packages/agents/react_agent.py`、`packages/agents/builder.py`、`apps/api/runtime.py` 三
个调用点

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

依据 `.specify/memory/constitution.md` v1.0.0 的五条原则逐一检查：

- **I. TDD（不可协商）**：本计划的每个任务都会先写测试（边界检查的"检测到违规导入"用例、Protocol
  注入后 agent loop 行为不变的回归用例、真实模型自测本身）后再改实现。✅ 通过。
- **II. 代码规范一致性**：本次改动是纯 Python，遵循现有 ruff/black 风格；不涉及前端，ESLint 原则
  不适用。✅ 通过。
- **III. 输入必须校验**：边界检查脚本的输入（目标包路径）会校验路径存在且是目录；真实模型自测在
  凭据缺失时走清晰的 skip 路径而不是让未校验的 `None` 值一路往下传导致看不懂的报错。✅ 通过。
- **IV. 简洁至上，拒绝过度工程**：新增的每一个 Protocol 都直接对应 `packages/core` 现在已经在用
  的某个具体能力（`HistoryStore`/`ToolExecutor`/`TraceRecorder`/`MetricsSink`/`TokenEstimator`/
  `OutputTrimmerLike`/`SteerQueue`），没有一个是为"未来可能需要"而预先设计的；这正是 spec 的
  FR-001/FR-002 明确要求的边界，不是自选的额外抽象。✅ 通过（见下方 Complexity Tracking 的说明性
  记录，非违规申诉）。
- **V. 接口文档完整性**：每个新增 Protocol 本身就是一份可读的契约（方法签名即文档），额外在
  `contracts/core-collaborator-protocols.md` 里补充每个方法的语义说明；边界检查脚本的调用方式和退
  出码约定写进 `contracts/boundary-check-cli.md`。✅ 通过。

无违反项，不需要在 Complexity Tracking 表格里做"违规申诉"；下方表格仅作说明性记录。

**Post-Design Re-check（Phase 1 完成后复查）**：data-model.md 定稿的七类 Protocol 全部对应现有
具体能力（无一为speculative 预留）；`contracts/` 两份文档和每个 Protocol/CLI 行为都对得上；
quickstart.md 的 7 个验证场景覆盖了全部三条 User Story 的 Acceptance Scenarios。五条原则依然全部
通过，无新增违规。

**二次复查（`/speckit-analyze` 发现 FR-002 的"排队"缺口后，补 `SteerQueue` Protocol 之后再复
查）**：新增的 `SteerQueue` 同样直接对应现有能力（`_LiveRun` 已经持有的 `steer` 队列/`steer_event`），
不是新设计出来的需求；原则 IV 依然成立。研究/设计/任务三份文档已同步更新，不存在遗留不一致。

## Project Structure

### Documentation (this feature)

```text
specs/001-core-isolation-selftest/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── core-collaborator-protocols.md
│   └── boundary-check-cli.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
packages/core/
├── __init__.py
├── agent.py              # 改：Agent.__init__ 改接受注入的 HistoryStore/TraceRecorder/
│                          #     MetricsSink/OutputTrimmerLike/TokenEstimator 实例，
│                          #     不再直接 import context/memory/observability
├── agent_loop.py          # 改：ToolRegistry 类型标注改为本地 ToolExecutor Protocol，
│                          #     metrics.inc/observe 改为注入的 MetricsSink，
│                          #     RunRecorder 类型标注改为本地 TraceRecorder Protocol，
│                          #     execute_model_step 新增 steer: SteerQueue | None 参数，
│                          #     调模型前先 drain() 注入纠偏消息、接管 interrupt_event
├── protocols.py           # 新增：HistoryStore / ToolExecutor+ToolInfo+ToolCallResult /
│                          #       TraceRecorder / MetricsSink / TokenEstimator /
│                          #       OutputTrimmerLike / SteerQueue 七类 Protocol 定义
├── cancellation.py         # 不变
├── compaction.py            # 不变（已经只依赖 core 自身的 model.py）
├── errors.py                 # 不变
├── model.py                   # 不变（已经只依赖第三方 SDK）
├── pricing.py                   # 不变
└── protocol.py                    # 不变（ChatMessage/ToolInvocation/Completion 等类型定义）

packages/memory/
└── working.py             # 改：新增一个 assemble(...) 透传方法，让调用方不需要再摸
                            #     WorkingMemory.assembler 这个内部属性（它的类型来自
                            #     context 包，不应该被 core 感知）

packages/agents/
├── react_agent.py          # 改：构造 Agent 基类时改传入 Protocol 实现，而不是原始的
│                           #     trace_dir/output_trimmer 等参数；新增 _ReActSteerQueue
│                           #     适配器类，包住 arespond() 本来就接收的 drain_steer=/
│                           #     steer_event= 两个参数使其满足 SteerQueue，删除自己手写的
│                           #     inject_steer() 闭包和 steer_event.clear() 调用
└── builder.py              # 不变：build_agent() 透传的参数集合没有变化

apps/api/
└── runtime.py              # 不变：ReActAgent 对外的 drain_steer=/steer_event= kwargs 契约
                             #     和 trace_dir= 等构造参数都没有变化，_LiveRun 不需要新增任何
                             #     方法（实现阶段发现：排队消息要记进 Agent 自己的 transcript，
                             #     这件事只能在持有 Agent 实例的 react_agent.py 里做，_LiveRun
                             #     不适合直接实现 SteerQueue；见 research.md 决策 5 的"实现时的
                             #     修正"）

scripts/
└── check_core_boundary.py  # 新增：边界检查 CLI（扫描 packages/core 的导入语句，报告违规）

tests/core/
├── test_protocols.py        # 新增：验证 WorkingMemory/ToolRegistry/RunRecorder/OutputTrimmer/
│                            #       TokenBudget 在不改代码的情况下结构性满足对应 Protocol
├── test_agent.py             # 改：按新的注入式构造方式更新现有测试
├── test_agent_loop.py        # 改：ToolRegistry 测试替身改用满足 ToolExecutor Protocol 的假对象
└── test_real_model_selftest.py  # 新增：真实模型自测，按凭据是否存在 skipif

tests/
└── test_check_core_boundary.py  # 新增：边界检查脚本自身的单测（含"新增一个不存在的功能包"场景）
```

**Structure Decision**: 单仓库多包结构不变（`packages/*` + `apps/*`），这次改动完全落在既有目录布局
内，不新增顶层目录；`scripts/check_core_boundary.py` 和仓库里已有的 `scripts/start.sh` 等运维脚本
放在同一层级，保持"运维/检查类脚本放 scripts/"的既有习惯。

## Complexity Tracking

> 无 Constitution 违规需要申诉；以下表格仅作说明性记录，解释"为什么是七类 Protocol 而不是更少"。

| 决策 | 为什么需要 | 更简单的替代方案被否决的原因 |
|------|-----------|-----------------------------|
| 七类独立 Protocol（而非合并成一个大接口） | 每个 Protocol 对应 core 现在就在用的一种独立能力，边界检查工具/测试替身可以只实现用得到的那一小部分，符合单一职责 | 合并成一个大接口会强迫每个注入方实现一整套方法，即使它只用到其中一两个；违反"文件/接口保持聚焦"的既有编码风格 |
| `SteerQueue` 单独作为一个 Protocol（而不是塞进 `HistoryStore` 或 `ToolExecutor`） | steering 排队和历史消息存取、工具执行是三件语义上独立的事，调用方（比如未来某个不支持纠偏的新 agent 策略）应该能选择不传 `steer` 而不影响另外两个能力 | 塞进别的 Protocol 会让那个 Protocol 的实现方被迫同时处理排队语义，即使它用不到 |
