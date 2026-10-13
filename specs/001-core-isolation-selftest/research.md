# Phase 0 Research: Agent Loop 核心边界隔离 + 真实模型自测

本阶段解决 Technical Context 里没有现成答案、需要调研/比较后拍板的几个技术决策。spec 阶段已经通过
三轮 `/speckit-clarify` 把范围决定清楚（见 spec.md 的 `## Clarifications`），这里只解决"怎么实现"
层面的问题。

## 决策 1：用什么机制让 `packages/core` 不再依赖 `context`/`tool`/`memory`/`observability`

**Decision**: 在 `packages/core/protocols.py` 新增一组 `typing.Protocol`（`HistoryStore`、
`ToolExecutor`+`ToolInfo`+`ToolCallResult`、`TraceRecorder`、`MetricsSink`、`TokenEstimator`、
`OutputTrimmerLike`、`SteerQueue`，共七类能力——按能力拆分，不合并成一个大接口；`ToolInfo`/
`ToolCallResult` 是 `ToolExecutor` 的附属数据类型，不单独计数），`Agent.__init__`/`agent_loop.py` 的函数签
名把原来的具体类型（`WorkingMemory`/`ToolRegistry`/`RunRecorder`/`OutputTrimmer`/`TokenBudget`）
换成对应的 Protocol；真正的实例由 `packages/agents`/`apps/api/runtime.py` 构造好之后注入。

**Rationale**: 这个模式在仓库里已经有先例——`packages/context/message.py` 的 `MessageLike`
Protocol 就是"让 `context` 包不需要依赖 `core.ChatMessage` 的具体类型，只要求结构匹配"，这次只是
把同一个思路反过来用在 `core` 身上。Python 的 `Protocol`（尤其标了 `@runtime_checkable` 的）不需要
被依赖方显式继承、不需要改 `WorkingMemory`/`ToolRegistry`/`RunRecorder`/`OutputTrimmer`/
`TokenBudget` 的任何代码（除了 `WorkingMemory` 需要补一个 `assemble()` 透传方法，见决策 6），迁移
成本只落在 `packages/core` 自己身上，符合"只改需要改的地方"的精准局部修改习惯。

**Alternatives considered**:
- **抽象基类（ABC）+ 显式继承**：会要求 `WorkingMemory`/`ToolRegistry` 等去 `import` core 定义的
  基类再继承它，这正好是把依赖方向反过来变成"其他包依赖 core 定义的基类"，虽然技术上不违反"core 不
  依赖别处"这条约束，但不必要地侵入了四个包的代码，Protocol 的结构化类型不需要这种侵入。
- **直接内联/复制一份精简实现到 core**：例如把 `TokenBudget`/`OutputTrimmer` 的核心逻辑抄一份到
  core 里。会造成同一份逻辑两处维护，违反 DRY；且 `OutputTrimmer` 涉及落盘逻辑、`TokenBudget` 依赖
  `tiktoken`，内联会让 core 间接引入新的第三方依赖面，增加而不是减少耦合。
- **保留依赖，只做一个 lint 规则例外豁免**：不满足 spec 的 FR-001（硬性要求 core 不得依赖），直接
  否决。

## 决策 2：边界检查用什么实现方式

**Decision**: 新增 `scripts/check_core_boundary.py`，用标准库 `ast` 模块解析 `packages/core/`
下每个 `.py` 文件的 `import`/`from ... import ...` 语句，提取被导入模块的顶层包名，只要不在允许集
合（`{"core"}` ∪ Python 标准库 ∪ `pyproject.toml` 声明的第三方依赖名）内就判定为违规，报告文件路径
与行号。同时提供一个 pytest 测试（`tests/test_check_core_boundary.py`）直接调用这个脚本的核心函数
断言"当前代码库跑出来是零违规"，让边界检查复用进常规测试套件里（而不是只能靠手动跑脚本才会被发
现）。

**Rationale**: 用 `ast` 解析导入语句（而不是正则匹配源码文本）能正确处理多行 `from x import (a, b)`
这类格式，且是标准库，不新增依赖。"不在允许集合内就是违规"（白名单逻辑）直接满足 FR-003 对"未来新
增功能包依然有效"的要求——不需要在增加一个新包时记得回来更新这份检查脚本。

**Alternatives considered**:
- **引入第三方工具 `import-linter`**：功能更完整（支持分层架构规则），但要新增一个 dev 依赖、一份
  独立的 ini/toml 配置文件，对"只检查一个包不许依赖任何别的包"这么单一的规则来说是不成比例的重量
  级方案；本仓库现有风格是优先用标准库写小工具（例如 `skill/skill_tags.py` 的手写 JSON 存储），这
  里延续同样的取舍。
- **正则匹配源码文本找 `^(from|import)` 开头的行**：对多行导入、`as` 别名等情况容易出假阴性/假阳
  性，`ast` 直接拿到结构化的导入信息更可靠。
- **只在 CI 配置里跑一次性检查脚本，不接入 pytest**：不满足"检查过程本身要可重复、可独立验证"
  （User Story 2 的 Independent Test），而且仓库里所有其他校验都是通过 `pytest tests/` 一条命令
  触达，单独开一条 CI-only 路径会增加维护面。

## 决策 3：真实模型自测怎么判断"有没有配置凭据"、怎么呈现超时/限流

**Decision**: 复用 `packages/core/model.py` 已有的 `ModelClient()` 默认构造逻辑（从 `.env` 的
`MODEL_API_KEY` 等变量读取配置）；测试用
`@pytest.mark.skipif(not os.environ.get("MODEL_API_KEY"), reason="未配置 MODEL_API_KEY，跳过真实
模型自测")` 跳过。测试内部给真实调用包一层 `asyncio.wait_for(..., timeout=60)`（对应 SC-003 的 60
秒预算），超时时测试结果标注为"外部服务不可用"（用单独的 `pytest.skip()` 而不是 `assert False` 失
败，避免把供应商侧的瞬时不稳定计成"代码有 bug"）。

**Rationale**: 这个 skip 风格和仓库里 `tests/memory/test_embedding.py` 对 `EMBED_API_KEY` 未配置
时的处理方式完全一致，维护者已经熟悉这个约定，不需要学一套新模式。把"超时"也归类成 skip（而不是
fail）直接对应 spec 里 Edge Case 的决议："不与 agent loop 逻辑有 bug 混淆"。

**Alternatives considered**:
- **超时/限流时让测试失败（而非 skip）**：会导致网络抖动直接污染测试套件的红绿状态，维护者没法一
  眼区分"真的改坏了"还是"这次网络不好"，违反 spec 的 Edge Case 决议。
- **重试机制（失败后自动重试几次）**：增加了测试的复杂度和运行时间，而且重试本身也可能掩盖真实的
  间歇性协议问题；spec 没有要求重试，属于会被 YAGNI 原则否决的额外复杂度。

## 决策 4：`metrics.inc`/`metrics.observe` 这类模块级单例调用怎么解耦

**Decision**: `agent_loop.py` 里现在直接调用的模块级 `observability.metrics` 单例，改成通过
`MetricsSink` Protocol（`inc(name, *, labels=None, value=1)`、`observe(name, value, *,
labels=None)`）注入；core 内部提供一个无操作的默认实现（`NullMetricsSink`，两个方法都是空实现），
调用方不传时静默跳过，传入真实的 `observability.metrics` 单例时行为和现在完全一样。

**Rationale**: 现在的调用点（`execute_model_step`/`resolve_tool_call`）不会在意具体往哪里报指标，
只是单纯"发生了这件事"——这正是 Protocol + 默认空实现的典型适用场景，调用方（`packages/agents`/
`apps/api/runtime.py`）可以继续用真实的 `observability.metrics`，不需要重新设计指标体系本身。

**Alternatives considered**:
- **完全删除 core 里的指标调用，把指标埋点整个搬到调用方**：调用方要重新实现一遍"在工具调用成功/
  失败时各记一次"这类逻辑，等于把本该在循环内部一次性做对的事情，复制到每一个使用 `agent_loop` 的
  地方；注入 `MetricsSink` 能保留"埋点逻辑写一次"的好处。

## 决策 5：steering/follow-up 的"排队"那一半现在不在 core，怎么下沉

**背景（`/speckit-analyze` 发现的缺口）**：`agent_loop.py` 的 `_call_model` 已经接受
`interrupt: asyncio.Event` 并在打断时抛 `ModelInterrupted`——"打断"这一半本来就在 core。但"排
队"那一半（把 `asyncio.Queue[str]` 里积压的纠偏消息掏空、追加成 user 消息）现在是
`packages/agents/react_agent.py` 的 `ReActAgent.arespond()` 自己手写的 `inject_steer()` 闭包在
做，`agent_loop.run_tool_turn`/`execute_model_step` 完全不知道这件事——这不满足 FR-002 对"core 必
须自己拥有 steering/follow-up 排队与打断机制"的要求。

**Decision**: 新增 `SteerQueue` Protocol（`drain() -> list[str]`、`clear_interrupt() -> None`、
`interrupt_event: asyncio.Event` 属性），`execute_model_step` 新增 `steer: SteerQueue | None =
None` 参数，在调用 `_call_model` 之前先 `drain()` 并把结果追加进 `messages`、清掉打断标记、把
`steer.interrupt_event` 作为这次调用的 `interrupt`。`ReActAgent.arespond()` 删除自己手写的循环内
`inject_steer()`/`steer_event.clear()` 调用，改为把这两件事统一委托给传入 `execute_model_step` 的
`steer` 对象。

**实现时的修正**：最初设想让 `_LiveRun` 直接新增三个方法结构性满足 `SteerQueue`，由
`apps/api/runtime.py` 传 `steer=run`。实际写 `react_agent.py` 时发现：`drain()` 掏出的消息除了要
追加进这一次请求的 `messages`，还必须被记进 Agent 自己的 transcript（`self.record_message(...)`，
对应既有测试 `test_steering_injects_a_user_message_at_the_next_step` 的断言），而这个记录动作只有
Agent 实例能做——`_LiveRun` 不持有、也不该持有 Agent 引用。于是改为在 `react_agent.py` 内部定义一
个 `_ReActSteerQueue` 适配器类，包住 `arespond()` 本来就接收的 `drain_steer`/`steer_event` 两个原
始参数（它的 `drain()` 转发给原始 `drain_steer()` 的同时顺手调用 `record_message`）。`_LiveRun`/
`apps/api/runtime.py` 因此完全不需要改动，`ReActAgent.arespond()` 对外的 kwargs 契约也完全不变
——这是比最初设计更小的改动面，而且同样满足 FR-002。

**Rationale**: `run_tool_turn`/`execute_model_step` 的模块docstring本来就说自己是"四种 agents/*.py
具体策略共用的引擎部分"——排队这件事对任何一种 agent 策略都是通用需求，不应该让每种策略（目前是
`ReActAgent`，以后可能有别的）各自重新实现一遍。下沉进 core 之后，`packages/agents` 不再需要手写
这段循环逻辑，减少了重复代码，也修掉了 FR-002 的这个缺口。

**Alternatives considered**:
- **维持现状，弱化 FR-002 的措辞**：技术上最省事，但这是对用户在 `/speckit-clarify` 里已经明确做
  出的"core 必须拥有排队机制"这个决定的推翻，不是更简单的实现方式，而是回避需求，予以否决。
- **把整个 `inject_steer()` 逻辑原样复制进 core，而不是走 Protocol 注入**：`apps/api/runtime.py`
  的 `_LiveRun` 持有真实的 `asyncio.Queue`/`asyncio.Event`，如果 core 要直接操作它们就必须
  `import asyncio` 构造自己的队列类型，和调用方的队列状态变成两份——Protocol 注入能让 `_LiveRun`
  继续是唯一的真实状态持有者，core 只是在恰当的时机调用它。

## 决策 6：`Agent.build_context()` 摸 `WorkingMemory.assembler` 内部属性的问题怎么解

**Decision**: 给 `packages/memory/working.py` 的 `WorkingMemory` 新增一个
`assemble(user_query, *, transcript, system_instructions=None, extra_slices=None) -> str` 方法，
内部透传给 `self.assembler.assemble(...)`。`Agent.build_context()` 改成调用注入的 `HistoryStore`
的 `assemble(...)` 方法，不再直接访问 `.assembler` 这个内部属性（那个属性的类型 `ContextAssembler`
来自 `context` 包，core 不应该在类型层面感知它）。

**Rationale**: 这是 `packages/core/protocols.py` 之外唯一需要改动 `packages/core` 之外文件的地方
之一（另一处是决策 5 里 `apps/api/runtime.py` 的 `_LiveRun` 新增方法），改动是纯新增的薄透传方法，
不改变 `WorkingMemory` 任何现有行为，向后兼容。

**Alternatives considered**:
- **把 `assembler` 属性本身的类型也定义成一个 core 侧 Protocol**：可行，但 `ContextAssembler.
  assemble()` 的参数形状本身就是 `HistoryStore.assemble()` 需要暴露的形状，没必要再多一层间接——
  直接让 `HistoryStore` Protocol 本身包含 `assemble()` 方法更直接，少一层概念。
