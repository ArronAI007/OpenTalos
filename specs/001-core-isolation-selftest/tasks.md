---

description: "Task list for feature implementation"
---

# Tasks: Agent Loop 核心边界隔离 + 真实模型自测

**Input**: Design documents from `/specs/001-core-isolation-selftest/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md（全部已就绪）

**Tests**: 本功能明确要求测试（constitution 的 TDD 原则 + spec 的 FR-003/FR-004/FR-005 本身就是"要
有可重复运行的检查/自测"），下列测试任务全部保留，且必须先写、先确认失败，再实现。

**Organization**: 按 spec.md 的三条 User Story（P1/P2/P3）分组，可以按优先级顺序交付，也可以独立验
证每一条。

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可以并行执行（不同文件、互相没有依赖）
- **[Story]**：对应 spec.md 里的 US1/US2/US3
- 每条任务都给出确切文件路径

## Path Conventions

单仓库多 Python 包结构（`packages/*` + `apps/*` + `tests/*`），与 plan.md 的 Project Structure 一
致，不是模板里的 `src/`/`backend/`/`frontend/` 示例布局。

---

## Phase 1: Setup

**Purpose**：在动手改代码前先确认一个干净的测试基线。

- [X] T001 运行 `.venv/bin/pytest tests/ -v`，记录当前通过的测试总数，作为本次重构前的基线（预期：
      全部通过，与此前 session 里确认过的 710 passed / 4 skipped 一致；如果基线本身不是全绿，先停
      下来排查，不要带着已知失败继续往下做）—— **实际基线：714 passed / 4 skipped**（仓库里后续又
      加了 4 个测试，710 这个数字已经过期，不是回归）

---

## Phase 2: Foundational

本功能三条 User Story 彼此独立（边界隔离重构 / 边界检查脚本 / 真实模型自测分别影响不同文件），没有
一项是"必须先做、否则任何一条 User Story 都无法开始"的共享阻塞前置工作，因此本阶段无任务，直接进入
各 User Story 阶段。

---

## Phase 3: User Story 1 - Core 不被功能模块反向牵连 (Priority: P1) 🎯 MVP

**Goal**：`packages/core` 不再直接 `import` `context`/`tool`/`memory`/`observability`，改为通过
`packages/core/protocols.py` 定义的七类 Protocol 接收调用方注入的实例；`packages/agents`/
`apps/api/runtime.py` 作为调用方负责构造并注入真实实现。这其中包括把 steering/follow-up 的"排队"
逻辑（现在手写在 `ReActAgent.arespond()` 里）正式下沉进 `agent_loop.py`（`/speckit-analyze` 发现
的缺口，见 research.md 决策 5）。

**Independent Test**：按 spec.md 的 Acceptance Scenario，逐个检查 `packages/core` 下每个源文件的导
入语句，确认不出现对任何其他 `packages/*` 目录的引用（本阶段末尾的 T014 就是这个验证）。

### Tests for User Story 1 ⚠️

> **先写这些测试，并确认它们按预期失败，再开始下面的 Implementation**

- [X] T002 [P] [US1] 在 `tests/core/test_protocols.py` 新增结构性一致性测试：断言
      `memory.WorkingMemory`、`tool.registry.ToolRegistry`（+`tool.tool.Tool`/`tool.outcome.
      ToolOutcome`）、`observability.RunRecorder`、`context.TokenBudget`、`context.OutputTrimmer`
      分别满足 `data-model.md` 里对应的 `HistoryStore`/`ToolExecutor`+`ToolInfo`+`ToolCallResult`/
      `TraceRecorder`/`TokenEstimator`/`OutputTrimmerLike` Protocol 形状（用
      `isinstance(obj, SomeProtocol)`，Protocol 需要标 `@runtime_checkable`，或直接用
      `hasattr`/方法签名断言）；再用一个测试本地定义的最小假对象（手写 `drain`/`clear_interrupt`/
      `interrupt_event`）断言它满足 `SteerQueue` 形状——这一步先不对真实的 `_LiveRun` 断言（那个要
      等 T012 把方法加上去之后，在 T013 的回归里才能一起验证）。预期：导入 `core.protocols` 时报
      `ModuleNotFoundError`，测试失败。
- [X] T003 [P] [US1] 重写 `tests/core/test_agent.py`：把现在构造 `Agent`（或其测试子类）时传的
      `trace_dir`/依赖内部自建 `WorkingMemory`/`TokenBudget` 的用法，改成显式传入
      `history: HistoryStore`、`trace_recorder_factory: Callable[[], TraceRecorder] | None`、
      `metrics: MetricsSink`、`token_estimator: TokenEstimator`、
      `output_trimmer: OutputTrimmerLike | None` 这几个新构造参数（用测试本地定义的假对象，不依赖
      真实的 `memory`/`observability`/`context` 包）。预期：针对 `Agent.__init__` 当前签名报
      `TypeError`（未知关键字参数），测试失败。
- [X] T004 [P] [US1] 重写 `tests/core/test_agent_loop.py`：把现在直接 `from tool.registry import
      ToolRegistry`/`from observability import RunRecorder` 构造测试替身的地方，改成测试本地定义
      的、满足 `ToolExecutor`/`TraceRecorder`/`MetricsSink` Protocol 形状的假对象；新增一个专门针对
      `SteerQueue` 的用例：构造一个假 `SteerQueue`（`drain()` 第一次返回 `["纠偏消息"]`、之后返回
      `[]`），调用 `execute_model_step(..., steer=fake_steer)`，断言返回前 `messages` 列表里确实
      多了一条 `{"role": "user", "content": "纠偏消息"}`，且 `clear_interrupt()` 被调用过一次。预
      期：由于 `agent_loop.py` 当前的参数类型标注、内部 `metrics.inc`/`observe` 调用、以及
      `steer` 参数都还没加，这些断言会失败（`steer` 相关的用例会直接报 `TypeError`：未知关键字参
      数）。
- [X] T005 [US1] 跑 `.venv/bin/pytest tests/core/test_protocols.py tests/core/test_agent.py
      tests/core/test_agent_loop.py -v`，确认上面三个文件按预期原因失败（而不是因为拼写错误等无
      关原因报错）（depends on: T002, T003, T004）

### Implementation for User Story 1

- [X] T006 [P] [US1] 创建 `packages/core/protocols.py`：按 `data-model.md` 定义
      `HistoryStore`、`ToolExecutor`、`ToolInfo`、`ToolCallResult`、`TraceRecorder`、
      `MetricsSink`（含一个空实现 `NullMetricsSink`）、`TokenEstimator`、`OutputTrimmerLike`、
      `SteerQueue`（`drain() -> list[str]`、`clear_interrupt() -> None`、
      `interrupt_event: asyncio.Event` 属性）共七类 Protocol/数据类型，全部标 `@runtime_checkable`
      （能被 `isinstance` 检查，供 T002 的测试使用）
- [X] T007 [P] [US1] 在 `packages/memory/working.py` 的 `WorkingMemory` 新增方法
      `assemble(self, user_query: str, *, transcript: list, system_instructions: str | None = None,
      extra_slices: list | None = None) -> str`，内部转发给 `self.assembler.assemble(user_query,
      transcript=transcript, system_instructions=system_instructions, extra_slices=extra_slices)`
      （对应 research.md 决策 5；是这次唯一需要改动 `packages/core` 之外文件的实现任务，纯新增、不
      改变任何现有方法的行为）
- [X] T008 [US1] 重写 `packages/core/agent.py`：删除 `from context import AssemblyConfig,
      ContextSlice, OutputTrimmer, TokenBudget`、`from observability import RunRecorder`、
      `from memory import WorkingMemory` 这三行导入；`Agent.__init__` 的参数列表把
      `context_config`/`min_retain_turns`/`trace_dir`/`trace_metadata`/`output_trimmer` 换成
      `history: HistoryStore`、`trace_recorder_factory: Callable[[], TraceRecorder] | None = None`、
      `trace_metadata: dict | None = None`（保留，仍然要传给 recorder 的 `session_start` 事件）、
      `metrics: MetricsSink = NullMetricsSink()`、`token_estimator: TokenEstimator`、
      `output_trimmer: OutputTrimmerLike | None = None`；`self._short_term = WorkingMemory(...)`
      改成 `self._short_term = history`；`self._tokens = TokenBudget()` 改成
      `self._tokens = token_estimator`；`begin_trace()` 里 `self.recorder =
      RunRecorder(output_dir=self._trace_dir)` 改成 `self.recorder =
      self._trace_recorder_factory()`（工厂为 `None` 时整体 no-op，和原来"`trace_dir` 为 `None`
      时 no-op"的语义等价）；`build_context()` 改成调用 `self._short_term.assemble(...)`
      （依赖 T006, T007）
- [X] T009 [US1] 重写 `packages/core/agent_loop.py`：删除 `from context import OutputTrimmer`、
      `from observability import RunRecorder, metrics`、`from tool.registry import ToolRegistry`
      这三行导入；`resolve_tool_call`/`execute_model_step`/`run_tool_turn` 里的
      `tool_registry: ToolRegistry | None` 类型标注改成 `tool_registry: ToolExecutor | None`，
      `recorder: RunRecorder | None` 改成 `recorder: TraceRecorder | None`，
      `trimmer: OutputTrimmer | None` 改成 `trimmer: OutputTrimmerLike | None`；三个函数新增
      `metrics: MetricsSink = NullMetricsSink()` 参数，把函数体里原来直接调用模块级
      `metrics.inc(...)`/`metrics.observe(...)` 的地方改成调用这个参数；`execute_model_step` 新增
      `steer: SteerQueue | None = None` 参数——在调用 `_call_model` 之前，若 `steer` 不为空：对
      `steer.drain()` 返回的每条消息追加一条 `{"role": "user", "content": ...}` 到 `messages`，调
      用 `steer.clear_interrupt()`，并把传给 `_call_model` 的 `interrupt` 参数换成
      `steer.interrupt_event`；`run_tool_turn` 同步新增 `steer` 参数并透传给
      `execute_model_step`（依赖 T006）
- [X] T010 [US1] 跑 `.venv/bin/pytest tests/core/test_protocols.py tests/core/test_agent.py
      tests/core/test_agent_loop.py -v`，确认全部通过（depends on: T008, T009）
- [X] T011 [US1] 更新 `packages/agents/react_agent.py` 和 `packages/agents/builder.py`：在构造
      `Agent`/`ReActAgent` 的地方，改成显式构造并传入真实的 `memory.WorkingMemory` 实例（作为
      `history`）、`lambda: observability.RunRecorder(output_dir=trace_dir)`（作为
      `trace_recorder_factory`，`trace_dir` 为空时整个 lambda 不传/传 `None`）、
      `observability.metrics` 单例（作为 `metrics`）、`context.TokenBudget()` 实例（作为
      `token_estimator`）、原有的 `output_trimmer` 参数直接透传（作为 `output_trimmer`）；
      `tool_registry` 参数和调用方式保持不变；**删除** `ReActAgent.arespond()` 里自己手写的
      `inject_steer()` 闭包和每步开头调用它的那行代码，改成把调用方传入的 `drain_steer`/
      `steer_event`（从 `` **kwargs `` 里弹出的那两个）包成一个满足 `SteerQueue` 形状的小适配器对
      象（或者如果调用方直接传的就是一个现成的 `SteerQueue` 实现，原样透传），交给
      `execute_model_step(..., steer=steer)`（depends on: T008, T009）
- [X] T012 [US1] **核实结果：`apps/api/runtime.py` 不需要任何代码改动。** 原计划设想
      `_LiveRun` 新增 `drain`/`clear_interrupt`/`interrupt_event` 并让 runtime.py 直接传
      `steer=run`，但 T011 实现时发现：排队消息还必须被记进 Agent 自己的 transcript（`self.
      record_message(...)`），而 `_LiveRun` 不持有、也不该持有 Agent 实例——所以无论 `SteerQueue`
      的底层队列来自哪里，"记入历史"这一层适配终归要留在 `packages/agents` 里。于是
      `_ReActSteerQueue` 适配器直接建在 `react_agent.py` 内部，包住 `arespond()` 本来就接收的
      `drain_steer=`/`steer_event=` 这两个原始参数；`ReActAgent.arespond()` 对外的 kwargs 契约完
      全没变，`apps/api/runtime.py:577-578` 的
      `drain_steer=lambda: _drain_queue(run.steer), steer_event=run.steer_event` 原样可用。已用
      `.venv/bin/pytest tests/apps/api/ -v`（258 passed）确认零回归。`_LiveRun`/`_drain_queue`
      均未改动。（depends on: T011）
- [X] T013 [US1] 跑 `.venv/bin/pytest tests/agents/ tests/apps/api/ -v`，确认全部通过、无回归
      （depends on: T012）—— 实际：277 passed
- [X] T014 [US1] 手动确认边界：运行 `grep -rnE "^from (context|tool|memory|observability)|^import
      (context|tool|memory|observability)" packages/core/*.py`，确认没有任何匹配结果（这一步在
      US2 的自动化脚本落地前，先用最朴素的方式独立确认这条 User Story 本身已经达标）
      （depends on: T008, T009）—— 实际：0 处匹配
- [X] T015 [US1] 跑 `.venv/bin/pytest tests/ -v`，确认全量测试通过数不低于 T001 记录的基线，无回归
      （depends on: T013, T014）—— 实际：725 passed / 4 skipped（基线 714，净增 11 个本次新增测试，
      0 回归）

**Checkpoint**：User Story 1 到这里已经可以独立交付——`packages/core` 不再依赖其他 `packages/*`
目录，且所有既有行为保持不变。

---

## Phase 4: User Story 2 - 边界约束可以被自动、重复地验证 (Priority: P2)

**Goal**：新增一个独立的边界检查脚本，能检测 `packages/core` 对其他 `packages/*` 目录的导入，并给
出清晰的文件/行号定位。

**Independent Test**：直接运行 `scripts/check_core_boundary.py`，得到明确的通过/不通过结论；人为
注入一行违规导入后再跑一次，结论必须翻转。这条 User Story 不依赖 User Story 1 是否已经完成——即使
`packages/core` 当下还有违规导入，这个检查工具本身也应该能正确报告出来。

### Tests for User Story 2 ⚠️

> **先写这些测试，并确认它们按预期失败，再开始下面的 Implementation**

- [X] T016 [P] [US2] 创建 `tests/test_check_core_boundary.py`：第一个测试用例调用
      `check_core_boundary.find_boundary_violations(Path("packages/core"))`，断言返回类型是
      `list[Violation]` 且（在 User Story 1 已完成的前提下）结果为空列表。预期：报
      `ModuleNotFoundError`，测试失败。
- [X] T017 [P] [US2] 在同一个测试文件里新增第二个用例：用 `tmp_path` 构造一个临时的假
      "`packages/core`" 目录，其中一个 `.py` 文件里写一行 `from tool.registry import
      ToolRegistry`，断言 `find_boundary_violations` 返回恰好一个 `Violation`，且其 `file`/
      `line`/`imported_package` 字段分别对应那个临时文件路径、对应行号、`"tool"`。预期：同样因为
      模块不存在而失败。

### Implementation for User Story 2

- [X] T018 [US2] 创建 `scripts/check_core_boundary.py`：定义 `Violation`（`file: Path`,
      `line: int`, `imported_package: str`）和 `find_boundary_violations(package_dir: Path) ->
      list[Violation]`——用标准库 `ast` 解析 `package_dir` 下每个 `.py` 文件的
      `ast.Import`/`ast.ImportFrom` 节点，提取顶层包名，凡是不等于 `"core"`、不在
      `sys.stdlib_module_names`、也不在 `pyproject.toml` `[project].dependencies` 列出的第三方包
      名集合里的，记一条 `Violation`；再实现一个 CLI 入口（`argparse`，`--package` 默认
      `packages/core`，校验路径存在且是目录，不存在就退出码 `2` 并打印 `ERROR: ...`），按
      `contracts/boundary-check-cli.md` 的退出码表（0=干净，1=发现违规，输出每条违规一行）打印结
      果（depends on: T016, T017 已写好、确认先失败）
- [X] T019 [US2] 跑 `.venv/bin/pytest tests/test_check_core_boundary.py -v`，确认全部通过
      （depends on: T018）
- [X] T020 [US2] 运行 `.venv/bin/python scripts/check_core_boundary.py`，确认（在 User Story 1 已
      完成的前提下）退出码为 `0`、输出 `OK: packages/core 未依赖任何其他 packages/* 目录`
      （depends on: T018, 以及 User Story 1 的 T015 已完成）

**Checkpoint**：User Story 1 和 2 现在都能独立验证通过。

---

## Phase 5: User Story 3 - Agent Loop 能跑通一次真实的大模型调用 (Priority: P3)

**Goal**：新增一条会真实调用大模型的自测，覆盖纯文本往返 + 工具调用意图识别两条路径，纳入常规
pytest 套件，未配置凭据时自动跳过。

**Independent Test**：在已配置真实凭据的环境下单独运行这条测试得到明确通过结论；去掉凭据后单独运
行得到清晰的跳过提示。不需要先完成 User Story 1/2（但由于这条测试要 `import core.agent_loop` 里
T009 已经改完的函数签名，实际执行顺序上放在 User Story 1 之后更自然——这一点在下方 Dependencies 里
如实记录，不假装它和 US1 毫无关系）。

### Tests for User Story 3 ⚠️

- [X] T021 [US3] 创建 `tests/core/test_real_model_selftest.py`：
      - 定义一个满足 `ToolExecutor`/`ToolInfo`/`ToolCallResult` Protocol 的最小假对象（只认一个固
        定的工具名，比如 `"get_current_time"`，`acall` 直接返回一个成功的假结果，不依赖真实
        `tool` 包）；
      - 用 `@pytest.mark.skipif(not os.environ.get("MODEL_API_KEY"), reason="未配置
        MODEL_API_KEY，跳过真实模型自测")` 标记整个测试；
      - 测试 1：用真实构造的 `core.model.ModelClient()` 和不带工具 schema 的消息列表调用
        `core.agent_loop.run_tool_turn(model_client, messages, tool_registry=None, max_iterations=1)`，
        包一层 `asyncio.wait_for(..., timeout=60)`，超时时 `pytest.skip("大模型服务超时/不可用")`
        而不是断言失败；正常返回时断言结果是非空字符串；
      - 测试 2：用同样的 `ModelClient()`、一个要求模型必须调用 `"get_current_time"` 工具的提示词 +
        对应的 function-calling schema + 上面的假 `ToolExecutor`，调用
        `core.agent_loop.run_tool_turn(...)`（同样包 60 秒超时→skip），断言假工具确实被调用了一次
        （验证 core 正确识别并转发了模型的工具调用意图），而不对模型的最终文本内容做强断言（模型
        输出本身不是确定性的）
- [X] T022 [US3] 跑 `.venv/bin/pytest tests/core/test_real_model_selftest.py -v`（确保当前 shell
      没有设置 `MODEL_API_KEY`），确认两个测试都显示 `SKIPPED`，且跳过原因文案清晰可读
      （depends on: T021）
- [X] T023 [US3] 在已配置好 `.env` 里 `MODEL_PROVIDER`/`MODEL_API_KEY`/`MODEL_NAME` 的前提下，跑
      `.venv/bin/pytest tests/core/test_real_model_selftest.py -v -s`，确认两个测试都
      `PASSED`，且在 60 秒预算内完成，`-s` 输出里能看到真实的模型回复内容（depends on: T021；如果
      当前开发环境确实没有可用凭据，这一步记录为"环境限制，留给有凭据的环境执行"，不算任务失败）
      —— 实际：本机 `.env` 已配置真实凭据（kimi-k3），两个测试均 PASSED，13.36s 完成（预算 60s）；
      纯文本往返真实回复 `'pong'`；工具调用往返真实识别并转发了 `get_current_time` 调用，模型基于
      假结果回复 `'The current time is 2026-01-01 00:00:00.'`

**Checkpoint**：三条 User Story 全部可以独立验证通过。

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T024 [P] 跑一遍完整回归：`.venv/bin/python scripts/check_core_boundary.py` +
      `.venv/bin/pytest tests/ -v`，确认边界检查退出码 `0`、全量测试通过数不低于 T001 的基线
      —— 实际：边界检查退出码 0；732 passed / 4 skipped（基线 714，净增 18，0 回归）
- [X] T025 按 `quickstart.md` 列出的 7 个验证场景逐条手动过一遍，确认每一条的实际结果都和文档里写
      的预期一致（场景 6 如果当前环境没有真实凭据，按 T023 的方式记录为环境限制）
      —— 实际：7 个场景全部按文档预期通过；本机 `.env` 已有真实凭据，场景 5/6 都验证了（无凭据
      降级 skip + 有凭据真实通过两条路径）
- [X] T026 [P] 按本仓库既有习惯更新项目 memory（`project_opentalos_python_rebuild.md` 追加这次
      core 边界隔离重构的记录 + `MEMORY.md` 索引行），记录这次改动涉及的文件范围和真机验证结果

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**：无依赖，立即开始
- **Foundational (Phase 2)**：本功能无此阶段内容（见上方说明）
- **User Story 1 (Phase 3)**：依赖 Setup 完成；是其余两条 User Story 在"实际顺序"上的自然前提（见
  下）
- **User Story 2 (Phase 4)**：依赖 Setup 完成；**不**依赖 User Story 1——检查脚本本身在
  `packages/core` 还有违规导入时也应该正确工作（T020 这一步是为了演示"重构完之后确实是绿的"，可以
  延后到 US1 完成后再跑，但 T016-T019 随时可以独立进行）
- **User Story 3 (Phase 5)**：依赖 Setup 完成；**逻辑上**不依赖 US1/US2，但它调用的是
  `core.agent_loop.run_tool_turn` 这个在 US1 里被改过签名的函数——如果团队是单人/单 agent 顺序执
  行，自然会先做完 US1 再做 US3；如果是多人并行，US3 的测试可以先针对"US1 完成前"的旧签名写（用
  `ToolRegistry` 真实类型而不是 Protocol），US1 落地后再把类型标注换成 Protocol，不会增加额外返工
- **Polish (Phase 6)**：依赖所需的 User Story 全部完成

### Within Each User Story

- 先写测试、确认失败，再实现，再确认通过（TDD 红-绿），对应 constitution 原则 I
- 每完成一个 checkpoint 就提交一次 commit（本仓库既定习惯：直接提交到 main，不开 feature branch）

### Parallel Opportunities

- T002/T003/T004（US1 的三个测试文件）可以并行写
- T006/T007（protocols.py 新增 + working.py 新增方法）可以并行做，互不影响
- T016/T017（US2 的两个测试用例，同一个新文件但逻辑独立）可以并行写
- US1、US2、US3 三条 User Story 的 Implementation 部分，如果是多人协作，US2 可以和 US1 完全并行推
  进（互不依赖文件）；US3 的测试编写也可以提前并行开始（见上方依赖说明）

---

## Parallel Example: User Story 1

```bash
# 并行写三个测试文件（T002/T003/T004）：
Task: "在 tests/core/test_protocols.py 新增结构性一致性测试"
Task: "重写 tests/core/test_agent.py 改用注入式构造"
Task: "重写 tests/core/test_agent_loop.py 的测试替身"

# 确认都按预期失败后，并行实现两个互不依赖的新增文件（T006/T007）：
Task: "创建 packages/core/protocols.py"
Task: "在 packages/memory/working.py 新增 assemble() 方法"
```

---

## Implementation Strategy

### MVP First（User Story 1 单独交付）

1. 完成 Phase 1：Setup（确认基线）
2. 完成 Phase 3：User Story 1（核心边界隔离重构）
3. **停下来验证**：T014/T015 独立确认 User Story 1 达标
4. 这一步本身就是完整可用的成果——即使 US2/US3 还没做，`packages/core` 已经满足"不依赖其他目录"
   这条最核心的约束

### Incremental Delivery

1. Setup → User Story 1（MVP，边界隔离本体）→ 独立验证 → 可以先提交/评审
2. 加 User Story 2（边界检查自动化，防止未来再次违反）→ 独立验证 → 提交
3. 加 User Story 3（真实模型自测，证明重构没破坏端到端行为）→ 独立验证 → 提交
4. Polish（Phase 6）收尾

### 单 Agent 顺序执行策略（本仓库既定协作模式）

本仓库这次计划预期由单个 agent（或一个人）按 T001→T026 顺序连续执行，不是多人并行分工，因此严格的
"并行团队"编排不是重点；上面的 Parallel Opportunities 仅供同一个 agent 在单个任务内部批量处理同类
文件时参考（比如一次性写完三个测试文件），不代表需要拆成多个 agent 同时跑。
