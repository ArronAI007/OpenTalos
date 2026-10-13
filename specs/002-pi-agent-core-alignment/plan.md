# Implementation Plan: packages/core 对齐 pi 的 agent-core 内核架构

**Branch**: `002-pi-agent-core-alignment` | **Date**: 2026-10-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-pi-agent-core-alignment/spec.md`

## Summary

把 `packages/core` 现有的"三段式阶段回调（STARTED/FINISHED/FAILED）+ 几个各管一摊的专用回调
（`on_text_delta`/`on_reasoning_delta`/`on_tool_result`/`on_usage`）+ 打断式 steering"架构，换成对
齐 `earendil-works/pi` `packages/agent` 的七项能力：细粒度事件总线、steering/follow-up 轮询式双队
列、工具执行模式+前后钩子、`finishTurn` 终止判定、`AgentMessage`/`Message` 消息分层、
`prepareRequest`/`prepareNextTurn` 请求级前置钩子、`thinking_level`/`thinking_budgets` 分级推理。
范围经 `/speckit-clarify` 确认为"全部接入"：`packages/agents/react_agent.py`（本仓库目前唯一的
`packages/core` 消费方）、`packages/agents/builder.py`、`apps/api/runtime.py` 都要跟着升级到实际使
用这套新接口，不允许"核心建好但没人用"的交付状态。技术方案延续 `001-core-isolation-selftest` 确立
的 Protocol 注入模式——`packages/core` 只新增 `typing.Protocol`/`dataclass` 形状和注入点，不新增对
其他 `packages/*` 的 import；事件总线复用仓库已有的 `PhaseSignal`（泛化成携带更多事件种类的
`AgentEvent`）这一现成模式而不是另起一套；steering 轮询时机经核实其实已经在正确的调用位置上（每次
`execute_model_step` 调模型前），这次真正要删的只是"打断在飞的模型调用"这条 `asyncio.Event` 赛跑逻
辑和 `ModelInterrupted` 异常。

## Technical Context

**Language/Version**: Python 3.12+（`pyproject.toml` 的 `requires-python = ">=3.12"`，`.venv` 实际
跑在 Python 3.13.5），与 `001-core-isolation-selftest` 一致

**Primary Dependencies**: `packages/core` 当前已直接依赖的第三方库——`openai`、`anthropic`（两家模型
SDK）、`pydantic`、`python-dotenv`；本次不新增任何第三方依赖。`packages/tool/tool.py` 的 `Tool`
基类会新增一个 `execution_mode` 字段（供 FR-008 用），这是 `packages/tool` 自己的改动，不影响
`packages/core` 的依赖边界。

**Storage**: N/A（不涉及持久化数据结构变更；`apps/api/runtime.py` 的 `_LiveRun` 内存态结构会调整字
段，但不涉及 SQLite schema）

**Testing**: pytest + pytest-asyncio（`.venv/bin/pytest`）；沿用 `tests/core/test_agent_loop.py` 已
有的 `scripted_client`/`echo_tool_registry` 等真实对象风格测试替身，新增的 Protocol 结构性满足测试
延续 `tests/core/test_protocols.py` 的做法；真实模型自测（`tests/core/test_real_model_selftest.py`）
需要补一个"七种能力都被 `ReActAgent` 真机触发过"的场景（对应 SC-008），沿用同样的
`MODEL_API_KEY` skipif 模式。

**Target Platform**: 本仓库现有后端进程（`apps/api`，macOS/Linux），不涉及新部署目标

**Project Type**: 单仓库多 Python 包（`packages/*` + `apps/api`）。本次改动范围是
`packages/core`（新增能力，重构）+ `packages/tool`（`Tool` 新增一个字段）+ `packages/agents`（接入
新接口，删除打断/`finish` 工具两条旧机制）+ `apps/api/runtime.py`（接入事件总线取代旧回调、
`_LiveRun` 的 steer 队列改造）。

**Performance Goals**: 事件总线的监听器按注册顺序 `await` 执行——不要求并发吞吐，要求的是确定性顺
序（FR-001/SC-001），不是本次关注的性能指标；工具执行模式切到顺序执行时允许比并发慢（这是显式配置
的取舍，不是缺陷）。

**Constraints**: FR-004（`packages/core` 零 `packages/*` 依赖边界）必须在新增全部七项能力之后依然
成立，`scripts/check_core_boundary.py` 必须保持零违规（SC-004）；`beforeToolCall`/`afterToolCall`
钩子异常必须 fail-closed（Clarifications 会话已确认）；本次明确会让两个已有测试失去原有断言意义
（`test_steering_interrupts_an_in_flight_model_call_and_retries` 整体删除/重写；
`tests/agents/test_react_agent.py` 里依赖 `finish` 工具终止的多个测试改写为依赖 `finishTurn`
行为），这是经确认的设计性变更，不是回归。

**Scale/Scope**: `packages/core` 当前约 9 个源文件；本次预计新增 2-3 个文件
（`events.py`、`hooks.py` 或并入 `protocols.py`/`protocol.py`，具体切分留给 `/speckit-tasks`）、
修改 `agent.py`/`agent_loop.py`/`protocols.py`/`protocol.py`/`model.py`；`packages/agents/
react_agent.py` 预计是改动量最大的消费方（移除 `finish` 工具机制、接入事件订阅、接入新 hooks）；
`apps/api/runtime.py` 的 `_run_turn`/`_LiveRun`/`steer()` 需要跟着改造以订阅新事件总线、把 steer 队
列拆成 steering+follow-up 两个。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

依据 `.specify/memory/constitution.md` v1.0.0 的五条原则逐一检查：

- **I. TDD（不可协商）**：`/speckit-tasks` 产出的每个任务都会先写测试再实现；两处"经确认的行为替
  换"（steering 打断→轮询、`finish` 工具→`finishTurn`）要求先写新行为的失败测试，再删旧实现、再让
  新测试通过，不是先删代码再补测试。✅ 通过。
- **II. 代码规范一致性**：纯 Python 改动，遵循现有 ruff/black 风格；不涉及前端。✅ 通过。
- **III. 输入必须校验**：`thinking_level` 的七档值、`QueueMode` 的两种模式、`beforeToolCall`/
  `afterToolCall` 返回值的字段都是封闭的 `Literal`/`dataclass` 形状，构造时越界值由类型系统/显式
  校验拒绝；钩子异常按 fail-closed 处理本身就是"不信任外部输入（钩子实现）、拒绝静默放行"的体现。
  ✅ 通过。
- **IV. 简洁至上，拒绝过度工程**：事件总线复用仓库已有的 `PhaseSignal` 模式泛化，不另起一套事件框
  架；steering 轮询位置核实后发现现有调用点已经正确，只删不加；`run_tool_turn` 不需要任何专门改
  动——它内部调用的 `execute_model_step` 一旦支持这些 hook 点，`run_tool_turn` 自动获得同样的能力
  （hook 参数默认 `None`，不传就是现状行为），不需要为它重复设计一遍。✅ 通过（见下方
  Complexity Tracking 的说明性记录）。
- **V. 接口文档完整性**：七项能力每一项都会在 `contracts/` 下有对应的契约文档；`data-model.md` 列
  出全部新增类型的字段级说明。✅ 通过。

无违反项，不需要在 Complexity Tracking 表格里做"违规申诉"；下方表格仅作说明性记录。

**Post-Design Re-check（Phase 1 完成后复查）**：`data-model.md` 定稿的全部新增类型都能在
`contracts/` 里找到对应契约；`research.md` 的每条决策都标注了对应的 Functional Requirement；
`quickstart.md` 的验证场景覆盖全部 7 个 User Story 的 Acceptance Scenarios + SC-008 的真机验证。五
条原则依然全部通过，无新增违规。

## Project Structure

### Documentation (this feature)

```text
specs/002-pi-agent-core-alignment/
├── plan.md               # This file (/speckit-plan command output)
├── research.md           # Phase 0 output (/speckit-plan command)
├── data-model.md         # Phase 1 output (/speckit-plan command)
├── quickstart.md         # Phase 1 output (/speckit-plan command)
├── contracts/            # Phase 1 output (/speckit-plan command)
│   ├── event-bus.md
│   ├── queues-and-finish-turn.md
│   ├── tool-execution-hooks.md
│   └── request-and-message-hooks.md
└── tasks.md              # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
packages/core/
├── __init__.py            # 改：导出新增的公共类型（AgentEvent、EventKind、QueueMode、
│                           #     BeforeCallResult、AfterCallResult、TurnDecision、
│                           #     ThinkingLevel 等）
├── agent.py                # 改：PhaseSignal/AgentPhase 泛化为 AgentEvent/EventKind；
│                            #     Agent.subscribe()/_emit() 新增；arespond_with_callbacks
│                            #     的 on_start/on_finish/on_error 改走事件总线（保留方法本身，
│                            #     内部实现换血，签名层面尽量不破坏调用方）；新增
│                            #     transform_context 注入点
├── agent_loop.py            # 改：execute_model_step/run_tool_turn 新增 emit/before_tool_call/
│                            #     after_tool_call/finish_turn/prepare_request 等可选参数
│                            #     （默认 None，不传等于现状）；删除 interrupt 赛跑逻辑和
│                            #     ModelInterrupted；steering 轮询位置不变（已经是对的），
│                            #     只改接口形状；新增 follow-up 轮询点；工具批次按
│                            #     execution_mode 决定并发/顺序
├── protocols.py              # 改：SteerQueue 去掉 clear_interrupt/interrupt_event，改名为
│                             #     poll-only 形状（沿用 drain() 或重命名为 poll()，二选一
│                             #     留给 /speckit-tasks 定）；ToolInfo 新增 execution_mode
│                             #     字段；新增 FollowUpQueue（或复用同一个 Protocol，两个
│                             #     队列各自实例化）
├── protocol.py                 # 改：SpeakerRole 从封闭 Literal 放宽为 str（让应用专属角色
│                               #     能塞进同一个 ChatMessage 列表）；新增 BeforeCallResult/
│                               #     AfterCallResult/TurnDecision/AgentEvent/EventKind 等
│                               #     dataclass
├── model.py                     # 改：ModelClient 新增运行期可读写的 thinking_level 属性 +
│                                #     构造期 thinking_budgets 映射表，替换/包装现有的扁平
│                                #     reasoning_effort（按 Decision 7 的档位映射表转译成
│                                #     各后端已支持的参数）
├── cancellation.py / compaction.py / pricing.py / errors.py  # 不变
└── (新增 1 个小模块，具体文件名留给 /speckit-tasks，例如 hooks.py，收纳钩子相关的类型/
    默认行为，避免把 protocol.py 塞得过大)

packages/tool/
└── tool.py                # 改：Tool.__init__ 新增 execution_mode: Literal["sequential",
                            #     "parallel"] | None = None 字段

packages/memory/
└── working.py              # 改：build_messages() 过滤掉非标准 LLM 角色的消息（FR-013 的
                             #     "转换步骤"落地点之一）

packages/agents/
├── react_agent.py           # 改：移除 FINISH_TOOL_NAME/FINISH_TOOL_SCHEMA/_read_final_answer/
│                            #     finish_calls 拦截；移除 ModelInterrupted 重试循环；
│                            #     _ReActSteerQueue 改造成 poll-only 形状并新增一个
│                            #     follow-up 版本；接入 finish_turn/before_tool_call/
│                            #     after_tool_call/prepare_request/prepare_next_turn/
│                            #     transform_context 构造参数并在 arespond() 里传下去；
│                            #     ModelClient 构造时改用 thinking_level 替换 reasoning_effort
└── builder.py               # 改：透传新增的构造参数（具体哪些需要在 builder 层暴露，
                              #     哪些保持 ReActAgent 内部默认，留给 /speckit-tasks 判断）

apps/api/
└── runtime.py              # 改：_LiveRun 的 steer 单队列拆成 steering_queue +
                            #     followup_queue 两个 asyncio.Queue；steer() 方法不再
                            #     set() 一个 interrupt event；_run_turn 的 produce() 订阅
                            #     agent 的新事件总线取代 on_text_delta=/on_reasoning_delta=
                            #     等 kwargs（需要确认事件总线能否 1:1 覆盖现有 SSE 事件类型，
                            #     覆盖不了的差异点在 tasks.md 里逐条列出）

scripts/
└── check_core_boundary.py  # 不变（新增类型都在 packages/core 内部，不引入新导入）

tests/core/
├── test_agent_loop.py        # 改：新增事件总线断言、steering-no-interrupt 断言、follow-up
│                             #     轮询断言、工具执行模式/钩子断言、finishTurn 断言；删除
│                             #     `test_execute_model_step_drains_and_injects_steer_queue_
│                             #     messages` 等依赖旧 SteerQueue 形状的测试或改写
├── test_protocols.py          # 改：新增/调整 Protocol 结构性满足断言
└── test_real_model_selftest.py  # 改：补 SC-008 对应的真机场景

tests/agents/
└── test_react_agent.py        # 改：删除/重写依赖 finish 工具终止的测试；
                              #     `test_steering_interrupts_an_in_flight_model_call_and_
                              #     retries` 整体删除或改写为"steering 不打断"的正向测试

tests/apps/api/
└── test_api_routes.py 等       # 改：跟着 _LiveRun 字段变化调整涉及 steer 的测试
```

**Structure Decision**: 单仓库多包结构不变，完全落在既有目录布局内；不新增顶层目录。
`packages/core` 内部可能新增 1 个小模块（具体命名留给 `/speckit-tasks`），遵循"文件保持短小聚焦"的
既有约定，不把全部新类型都塞进 `protocol.py`/`protocols.py` 两个文件里。

## Complexity Tracking

> 无 Constitution 违规需要申诉；以下表格仅作说明性记录。

| 决策 | 为什么需要 | 更简单的替代方案被否决的原因 |
|------|-----------|-----------------------------|
| 事件总线复用泛化后的 `PhaseSignal`（而非引入独立的 pub/sub 框架或第三方库） | FR-001 要求的是"监听器按序 await"的确定性语义，`PhaseSignal.emit()`/`to_dict()` 这套模式已经在 `packages/core/agent.py` 里验证过，直接扩展它的 `kind` 枚举和携带的数据字段即可满足 FR-002 的全部事件种类 | 引入独立事件框架（如发布一个 EventEmitter 类）会新增不必要的抽象层，且与已有的 `PhaseSignal` 并存会造成两套相似但不同的事件机制，违反"拒绝过度工程" |
| steering/follow-up 用两个独立的小 Protocol 实例（而非一个"队列"Protocol 加一个 `is_followup: bool` 参数区分） | 两个队列在 FR-005/007 里语义独立（各自的 `QueueMode`、各自的轮询时机），调用方可能只需要其中一个（比如某个未来的新 agent 策略只要 follow-up 不要 steering），强行合并成一个带开关的 Protocol 会让"不需要那一半"的调用方也要应付这个参数 | 合并成一个参数化 Protocol 表面上更"统一"，但实际上会在每个消费方代码里散布 `if is_followup` 判断，可读性更差 |
