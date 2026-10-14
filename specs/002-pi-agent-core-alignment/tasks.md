---

description: "Task list for feature implementation"
---

# Tasks: packages/core 对齐 pi 的 agent-core 内核架构

**Input**: Design documents from `/specs/002-pi-agent-core-alignment/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md（全部已就绪）

**Tests**: 本功能明确要求测试（constitution 的 TDD 原则，不可协商），下列测试任务全部保留，且必须
先写、先确认失败，再实现。

**Organization**: 按 spec.md 的 7 条 User Story（P1-P7）分组。注意：与 `001-core-isolation-selftest`
不同，这 7 条 User Story 在实现层面高度耦合（都改 `packages/core/agent_loop.py`/`agent.py`），"独
立可测"指的是每条 Story 完成后都能单独跑通自己的验证场景，不代表实现顺序可以任意打乱——建议严格
按 P1→P7 顺序执行。

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可以并行执行（不同文件、互相没有依赖）
- **[Story]**：对应 spec.md 里的 US1-US7
- 每条任务都给出确切文件路径

## Path Conventions

单仓库多 Python 包结构（`packages/*` + `apps/*` + `tests/*`），与 plan.md 的 Project Structure 一
致。

---

## Phase 1: Setup

**Purpose**：在动手改代码前先确认一个干净的测试基线。

- [X] T001 运行 `.venv/bin/pytest tests/ -v`，记录当前通过的测试总数作为本次重构前的基线（预期与
      `001-core-isolation-selftest` 收尾时记录的 732 passed / 4 skipped 一致；如果不是全绿，先停下
      来排查，不要带着已知失败继续往下做）—— **实际：732 passed / 4 skipped，与基线一致**
- [X] T002 运行 `.venv/bin/python scripts/check_core_boundary.py`，确认退出码为 `0`（本次改动过程
      中必须始终保持这个结果，见 SC-004）—— **实际：退出码 0**

---

## Phase 2: Foundational

本功能没有"必须先做、否则任何一条 User Story 都无法开始"的共享阻塞前置工作——虽然 spec.md 把事件总
线（US1）定性为"地基"，但这指的是**描述时序的参照系**，不是代码层面的编译期依赖；US2-US7 各自新增
的参数/类型可以独立编写。因此本阶段无任务，直接进入各 User Story 阶段；但出于"地基"这个定性，建议
严格按 P1→P7 顺序执行（见 Dependencies & Execution Order）。

---

## Phase 3: User Story 1 - 细粒度事件总线替代"开始/结束/失败"三段式 (Priority: P1) 🎯 MVP

**Goal**：`Agent` 新增 `subscribe()`/`_emit()`，`packages/core` 的运行时序以 `AgentEvent`/
`EventKind`（10 种）描述；`ReActAgent`/`apps/api/runtime.py` 实际订阅这套总线取代现有的
`PhaseCallback`/`on_text_delta`/`on_reasoning_delta`/`on_tool_result`/`on_usage` 机制。

**Independent Test**：订阅一次纯文本问答运行，断言事件序列恰好是 `contracts/event-bus.md` 验证要点
1 描述的那一串；订阅一次工具调用运行，断言 `TOOL_EXECUTION_*` 事件成对出现。

### Tests for User Story 1 ⚠️

> **先写这些测试，并确认它们按预期失败，再开始下面的 Implementation**

- [X] T003 [P] [US1] 在 `tests/core/test_agent.py` 新增：`Agent.subscribe(listener)` 注册的多个监
      听器按注册顺序被依次 `await`（用一个共享列表记录各自开始/结束时间戳断言不交错）；单个监听
      器抛异常不打断其余监听器或 `arespond_with_callbacks` 主流程；`RUN_END` 事件对应的监听器全部
      跑完之前，`arespond_with_callbacks` 不应该返回（用一个在监听器里 `await asyncio.sleep(0.05)`
      的测试验证返回时机晚于这个 sleep）。预期：`AttributeError`（`subscribe` 不存在），测试失败。
- [X] T004 [P] [US1] 在 `tests/core/test_agent_loop.py` 新增：`execute_model_step(..., emit=...)`
      对纯文本问答（无工具调用）产生的事件序列恰好是 `contracts/event-bus.md` 验证要点 1 描述的
      `RUN_START/TURN_START` 之外那部分（`MESSAGE_START(user) → MESSAGE_END(user) →
      MESSAGE_START(assistant) → MESSAGE_UPDATE(assistant)* → MESSAGE_END(assistant)`，
      `RUN_START`/`TURN_START`/`TURN_END`/`RUN_END` 由外层 `Agent`/`run_tool_turn` 负责，不在
      `execute_model_step` 这一层）；对触发工具调用的运行，`TOOL_EXECUTION_START`/
      `TOOL_EXECUTION_END` 成对出现且携带可区分的 `call_id`/`tool_name`。预期：`TypeError`（未知
      关键字参数 `emit`），测试失败。
- [X] T005 [US1] 跑 `.venv/bin/pytest tests/core/test_agent.py tests/core/test_agent_loop.py -v`，
      确认按预期原因失败（depends on: T003, T004）

### Implementation for User Story 1 (core)

- [X] T006 [US1] 在 `packages/core/protocol.py` 新增 `EventKind` 枚举（`RUN_START`/`RUN_END`/
      `TURN_START`/`TURN_END`/`MESSAGE_START`/`MESSAGE_UPDATE`/`MESSAGE_END`/
      `TOOL_EXECUTION_START`/`TOOL_EXECUTION_UPDATE`/`TOOL_EXECUTION_END` 共 10 个成员，值用
      `data-model.md` 里的小写字符串）和 `AgentEvent` dataclass（`kind: EventKind`、
      `timestamp: float`、`agent_name: str`、`data: dict[str, Any]`，`emit()` classmethod + 
      `to_dict()`，直接参照 `packages/core/agent.py` 现有 `PhaseSignal` 的写法泛化）
- [X] T007 [US1] 重写 `packages/core/agent.py`：删除 `AgentPhase`/`PhaseSignal`，新增
      `Agent.subscribe(listener: Callable[[AgentEvent], Awaitable[None]]) -> Callable[[], None]`
      （返回取消订阅函数）和 `Agent._emit(event: AgentEvent) -> None`（按注册顺序依次 `await`，单
      个监听器异常吞掉不传播，不设超时）；`arespond_with_callbacks` 签名保持不变，内部改成临时订
      阅一个转发器——收到 `RUN_START` 转调 `on_start`、收到 `RUN_END` 按 `data["status"]` 转调
      `on_finish`（`completed`）或 `on_error`（`failed`），方法返回前取消订阅；`begin_trace()`/
      `arespond_with_callbacks` 本身负责在 `arespond()` 前后 `_emit` 一次 `RUN_START`/`RUN_END`
      （`RUN_END` 的 `data` 含 `status`/`result`/`error`/`error_type`，按 `contracts/
      event-bus.md`）（depends on: T006）
- [X] T008 [US1] 重写 `packages/core/agent_loop.py`：`execute_model_step`/`run_tool_turn` 新增
      `emit: Callable[[AgentEvent], Awaitable[None]] | None = None` 参数（默认 `None` 不改变现
      状）；在追加 user 消息后 `emit(MESSAGE_START/MESSAGE_END, role="user")`；调模型得到流式增量
      时（`on_text_delta`/`on_reasoning_delta` 被调用的同一处）额外 `emit(MESSAGE_UPDATE,
      role="assistant", delta=..., delta_kind="text"|"reasoning")`；assistant 消息追加完成后
      `emit(MESSAGE_START/MESSAGE_END, role="assistant")`（无流式增量时 `MESSAGE_START`/
      `MESSAGE_END` 紧挨着发，`data["content"]` 带完整文本）；每次工具调用执行前后分别
      `emit(TOOL_EXECUTION_START)`/`emit(TOOL_EXECUTION_END)`（`run_one` 内部包一层）；
      `run_tool_turn` 的外层循环负责 `emit(TURN_START)`/`emit(TURN_END)`（depends on: T006）
- [X] T009 [US1] 跑 `.venv/bin/pytest tests/core/test_agent.py tests/core/test_agent_loop.py -v`，
      确认全部通过（depends on: T007, T008）

### Tests for User Story 1 (ReActAgent 接入，FR-019) ⚠️

- [X] T010 [US1] 在 `tests/agents/test_react_agent.py` 新增：构造一个 `ReActAgent`，
      `agent.subscribe(listener)` 后跑一次会触发工具调用的 `arespond()`，断言收到的事件序列里能
      看到 `RUN_START`→…→`RUN_END`、且 `TOOL_EXECUTION_*` 事件的 `tool_name` 和实际调用的工具对
      应得上；再跑一次不触发工具调用的 `arespond()`，断言事件序列符合 `contracts/event-bus.md` 验
      证要点 1。预期：由于 `ReActAgent` 还没有把 `emit` 传给 `execute_model_step`，事件序列缺失
      `TOOL_EXECUTION_*`/中间 `MESSAGE_*` 事件，测试失败。

### Implementation (ReActAgent 接入)

- [X] T011 [US1] 修改 `packages/agents/react_agent.py`：`arespond()` 里每次调用
      `execute_model_step(...)` 都传入 `emit=self._emit`；`run_tool_turn` 风格的 `TURN_START`/
      `TURN_END` 对应到 `ReActAgent` 自己的 `for step in range(...)` 循环里手动 `emit`（因为
      `ReActAgent.arespond()` 没有复用 `run_tool_turn`，是自己实现的循环）（depends on: T008,
      T010）
- [X] T012 [US1] 跑 `.venv/bin/pytest tests/agents/test_react_agent.py -v`，确认全部通过
      （depends on: T011）

### Tests for User Story 1 (apps/api 接入) ⚠️

- [X] T013 [US1] 调整 `tests/apps/api/test_api_routes.py`（或其他覆盖流式聊天的测试文件）里依赖
      `on_text_delta=`/`on_reasoning_delta=` kwargs 直接验证 SSE 输出的用例，改成验证"`_run_turn`
      通过 `agent.subscribe()` 驱动后，SSE 输出的 `delta`/`reasoning`/工具结果/用量事件内容不变"。
      预期：在 T014 完成前，`runtime.py` 还是旧实现，这组新断言应该仍然通过（因为外部可观察行为不
      变是要求）——这一条任务的"先失败"体现在：先验证新断言能描述清楚现状，再在 T014 替换实现后
      确认同一组断言仍然通过（回归，不是红灯测试），避免重写出一个行为不等价的新实现而未被发现。

### Implementation (apps/api 接入)

- [X] T014 [US1] **实现时的修正（两处）**：(1) `RUN_START`/`RUN_END` 只在 `arespond_with_callbacks()`
      内部发出（`arespond()` 是每个子类自己实现的抽象方法，基类无法在那一层统一包一层生命周期事
      件）；原计划"改成调用裸 `agent.arespond(...)`"会导致完全收不到 `RUN_START`/`RUN_END`，已在
      T010 的测试里发现并改为继续调用 `arespond_with_callbacks()`。(2) 仅仅删除
      `on_text_delta=`/`on_reasoning_delta=` 而不给替代信号，会让 `execute_model_step` 失去"该不该
      走流式"的依据（这两个回调本来身兼"要不要流式"和"流式增量去哪"两个职责）——新增一个独立的
      `stream: bool = False` 参数（`execute_model_step`/`run_tool_turn`/`ReActAgent.arespond()` 都
      新增，默认不影响现状），专门表达"走流式、增量只经事件总线下发"，与原始 `on_text_delta` 是否
      存在解耦。实际改动：`packages/core/agent_loop.py` 新增 `stream` 参数（`want_stream = stream
      or on_text_delta is not None or on_reasoning_delta is not None`）；
      `packages/agents/react_agent.py` 的 `arespond()` 新增 `kwargs.pop("stream", False)` 并透
      传。修改 `apps/api/runtime.py`：`_run_turn()` 的 `produce()` 不再传
      `on_text_delta=`/`on_reasoning_delta=` 给 `agent.arespond_with_callbacks(...)`，改传
      `stream=True`，并先 `unsubscribe = agent.subscribe(handle_event)`
      （`steer_event=`/`on_steer_interrupt=`/`drain_steer=` 等 steering 相关 kwargs 本次不动，留
      给 US2）；`handle_event(event: AgentEvent)` 按 `event.kind` 换算：`MESSAGE_UPDATE` 且
      `delta_kind=="text"` → `emit({"type": "delta", "text": event.data["delta"]})`；
      `delta_kind=="reasoning"` → `emit({"type": "reasoning", "text": ...})`（`tool_call`/
      `tool_result` 本来就由 `EventToolRegistry.sink` 独立处理，不在这条路径上，不需要改动）；
      `finally` 里调用 `unsubscribe()`（depends on: T011, T013）
- [X] T015 [US1] 跑 `.venv/bin/pytest tests/apps/api/ -v`，确认全部通过、无回归（depends on: T014）
- [X] T016 [US1] 跑 `.venv/bin/pytest tests/core/ tests/agents/ tests/apps/api/ -v`，确认本故事范
      围内全部测试通过、无回归（depends on: T009, T012, T015）

**Checkpoint**：事件总线已经上线并被 `ReActAgent`/`apps/api/runtime.py` 实际使用。

---

## Phase 4: User Story 2 - Steering 与 Follow-up 拆成两条独立队列，完全改成"轮询"而非"打断" (Priority: P2)

**Goal**：删除"打断在飞的模型调用"这条路径（`ModelInterrupted`/`interrupt_event`/
`clear_interrupt`），`SteerQueue` 收窄为纯轮询；新增独立的 follow-up 轮询队列。

**Independent Test**：工具调用执行期间排队一条 steering 消息，断言工具调用正常跑完、无任何中断异
常；没有更多工具调用时排队一条 follow-up 消息，断言运行多跑一轮。

### Tests for User Story 2 ⚠️

- [X] T017 [P] [US2] 在 `tests/core/test_agent_loop.py` 新增：工具调用执行期间（用一个会在真正返回
      前等待一个 `asyncio.Event` 的假工具）排队一条 steering 消息，断言这次工具调用没有被取消（事
      件/断言都确认执行到底），消息在下一次 `execute_model_step` 调用前出现在 `messages` 里，且全
      程没有抛出 `ModelInterrupted`；额外断言 `SteerQueue` Protocol 不再要求
      `clear_interrupt`/`interrupt_event`（用一个只实现 `drain()` 的最小假对象即可通过
      `isinstance` 检查）。预期：当前 `_call_model` 仍然会对 `steer.interrupt_event` 发起赛跑逻
      辑，断言"全程没有打断"会因为现有实现尝试访问这个属性而失败/或行为不符预期。
- [X] T018 [P] [US2] 在 `tests/core/test_agent_loop.py` 新增：没有更多工具调用时排队一条 follow-up
      消息，断言 `execute_model_step`/`run_tool_turn` 不直接停止，而是把消息注入并多跑一轮；steering
      和 follow-up 都有消息时，断言 steering 先被注入（通过观察 `messages` 里两条消息的相对顺序）。
      预期：`TypeError`（`execute_model_step`/`run_tool_turn` 还没有 `followup` 参数），测试失败。
- [X] T019 [US2] 跑 `.venv/bin/pytest tests/core/test_agent_loop.py -v`，确认 T017/T018 按预期原因
      失败（depends on: T017, T018）

### Implementation for User Story 2

- [X] T020 [US2] 修改 `packages/core/protocols.py`：`SteerQueue` Protocol 删除
      `clear_interrupt()`/`interrupt_event` 两个成员，只保留 `drain() -> list[str]`
- [X] T021 [US2] 修改 `packages/core/agent_loop.py`：删除 `ModelInterrupted` 异常类；
      `_call_model` 删除"和 `interrupt.wait()` 赛跑"那一整段，简化成普通 `await call`（删除
      `interrupt: asyncio.Event | None` 参数）；`execute_model_step` 删除
      `steer.clear_interrupt()`/`interrupt = steer.interrupt_event` 这两行（`steer.drain()` 本身
      的调用位置不变，见 research.md 决策 2）；新增 `followup: SteerQueue | None = None` 参数——在
      判定"这一步没有 `requested_tools`、本来要返回"之前，先 `followup.drain()`（非空则追加消息并
      让这一步"继续"而不是返回，具体由外层 `run_tool_turn` 的循环承接：`execute_model_step` 把"是
      否还要继续"的信号通过返回值或一个新的布尔标记传出去）；`run_tool_turn` 同步新增 `followup`
      参数并透传（depends on: T020）
- [X] T022 [US2] 跑 `.venv/bin/pytest tests/core/test_agent_loop.py -v`，确认全部通过（depends on:
      T021）

### Tests for User Story 2 (ReActAgent 接入) ⚠️

- [X] T023 [US2] 在 `tests/agents/test_react_agent.py`：删除
      `test_steering_interrupts_an_in_flight_model_call_and_retries`（断言的行为本身被废弃，不是
      改名重写）；新增一个正向测试，断言 `ReActAgent` 跑一个工具调用时排队 steering 消息不会打断
      它；新增一个 follow-up 测试，断言没有更多工具调用时排队 follow-up 消息会让 `ReActAgent` 多跑
      一轮。预期：follow-up 相关断言因为 `ReActAgent.arespond()` 还没有 `follow-up` 入参而失败
      （`_ReActSteerQueue` 的 `drain_steer=`/`steer_event=` kwargs 还没有 follow-up 版本）。

### Implementation (ReActAgent 接入)

- [X] T024 [US2] 修改 `packages/agents/react_agent.py`：`_ReActSteerQueue` 删除
      `clear_interrupt()`/`interrupt_event`；删除 `arespond()` 里 `while True: try: ... except
      ModelInterrupted: continue` 的重试循环（`execute_model_step` 现在不会再抛这个异常）；新增一
      个 follow-up 版本的队列适配器（结构和 `_ReActSteerQueue` 相同，包住新增的
      `drain_followup: Callable[[], list[str]] | None` kwarg），`arespond()` 的 `**kwargs` 新增
      弹出 `drain_followup`，构造 `followup = _ReActSteerQueue(...)`（或共享同一个适配器类，传入
      不同的 drain 回调）并传给每次 `execute_model_step(..., followup=followup)`（depends on:
      T021, T023）
- [X] T025 [US2] 跑 `.venv/bin/pytest tests/agents/test_react_agent.py -v`，确认全部通过（depends
      on: T024）

### Implementation (apps/api 接入)

- [X] T026 [US2] 修改 `apps/api/runtime.py`：`_LiveRun` 删除 `steer_event: asyncio.Event` 字段，
      `steer: asyncio.Queue[str]` 重命名为 `steering: asyncio.Queue[str]`，新增
      `followup: asyncio.Queue[str] = field(default_factory=asyncio.Queue)`；`steer()` 方法删除
      `run.steer_event.set()` 这行，写入目标从 `run.steer` 改成 `run.steering`；`_run_turn()` 的
      `produce()` 里 `drain_steer=lambda: _drain_queue(run.steer)` 改成
      `drain_steer=lambda: _drain_queue(run.steering)`，新增
      `drain_followup=lambda: _drain_queue(run.followup)`，删除
      `steer_event=run.steer_event`/`on_steer_interrupt=...` 两个 kwargs（打断通知机制随打断能力
      一起移除）（depends on: T024）
- [X] T027 [US2] 跑 `.venv/bin/pytest tests/apps/api/ -v`，确认全部通过、无回归（因字段改名而需要
      调整的测试一并修正）（depends on: T026）
- [X] T028 [US2] 跑 `.venv/bin/pytest tests/core/ tests/agents/ tests/apps/api/ -v`，确认本故事范
      围内全部测试通过、无回归（depends on: T022, T025, T027）

**Checkpoint**：Steering/Follow-up 均为纯轮询语义，打断能力已彻底移除。

---

## Phase 5: User Story 3 - 工具执行模式可配置 + before/afterToolCall 钩子 (Priority: P3)

**Goal**：工具批次可配置并发/顺序执行；新增执行前后钩子，异常 fail-closed。

**Independent Test**：一批 3 个工具里 1 个标记 `execution_mode="sequential"`，断言整批顺序执行；
`before_tool_call`/`after_tool_call` 的拦截/覆写/异常处理分别生效。

### Tests for User Story 3 ⚠️

- [X] T029 [P] [US3] 在 `tests/core/test_agent_loop.py` 新增：一批 3 个工具调用，其中 1 个（经假
      `ToolExecutor.get()` 返回 `ToolInfo(execution_mode="sequential", ...)`）要求顺序执行，断言
      整批顺序执行（用共享列表记录各工具开始/结束时间戳，断言不重叠）；另起一批没有任何工具标记
      `execution_mode` 的调用，断言仍然并发执行（现状不变）。预期：`ToolInfo` 还没有
      `execution_mode` 字段，构造测试替身即报 `TypeError`，测试失败。
- [X] T030 [P] [US3] 在 `tests/core/test_agent_loop.py` 新增：`before_tool_call` 返回
      `BeforeCallResult(block=True, reason="...")` 时工具函数本身完全不被调用，模型收到的内容含
      `reason`；`after_tool_call` 返回 `AfterCallResult(details=...)` 只覆写 `details`，
      `content`/`is_error` 保持原值；`before_tool_call`/`after_tool_call` 内部抛异常时被当作
      `block=True`/`is_error=True` 处理，不向上传播；一批里只有部分调用标记 `terminate=True` 时运
      行不提前结束，全部标记时提前结束。预期：`execute_model_step` 还没有这两个参数，
      `TypeError`，测试失败。
- [X] T031 [US3] 跑 `.venv/bin/pytest tests/core/test_agent_loop.py -v`，确认按预期原因失败
      （depends on: T029, T030）

### Implementation for User Story 3

- [X] T032 [US3] 修改 `packages/core/protocols.py`：`ToolInfo` 新增
      `execution_mode: Literal["sequential", "parallel"] | None = None` 字段；修改
      `packages/core/protocol.py`：新增 `BeforeCallResult`（`block: bool = False`,
      `reason: str | None = None`, `terminate: bool = False`）和 `AfterCallResult`
      （`content: str | None = None`, `details: Any = None`, `is_error: bool | None = None`,
      `terminate: bool = False`）两个 dataclass
- [X] T033 [US3] 修改 `packages/tool/tool.py`：`Tool.__init__` 新增
      `execution_mode: Literal["sequential", "parallel"] | None = None` 构造参数并存成同名实例属
      性（depends on: T032）
- [X] T034 [US3] 修改 `packages/core/agent_loop.py`：`execute_model_step` 新增
      `tool_execution_mode: Literal["sequential", "parallel"] = "parallel"`、
      `before_tool_call`/`after_tool_call` 三个参数；`resolve_tool_call` 包一层：执行前调用
      `before_tool_call`（异常时按 fail-closed 转成 `BeforeCallResult(block=True, reason=...)`），
      `block=True` 时不调用 `tool_registry.acall`，直接返回标注 `reason` 的错误结果；执行后调用
      `after_tool_call`（异常时按 fail-closed 转成 `AfterCallResult(is_error=True, content=...)`）
      按非 `None` 字段覆写结果；收集这一批每个调用最终的 `terminate` 标记，`run_one`/批次执行逻辑
      按"这一批里是否有任何工具 `execution_mode=="sequential"`"决定用 `asyncio.gather` 还是顺序
      `for` 循环；批次结束后，当且仅当非空且全部标记 `terminate=True` 时，把"提前结束"信号传给外
      层循环（depends on: T032, T033）
- [X] T035 [US3] 跑 `.venv/bin/pytest tests/core/test_agent_loop.py -v`，确认全部通过（depends on:
      T034）

### Tests for User Story 3 (ReActAgent 接入) ⚠️

- [X] T036 [US3] 在 `tests/agents/test_react_agent.py` 新增：构造 `ReActAgent` 时传入
      `tool_execution_mode="sequential"`，断言一批多工具调用确实顺序执行；传入
      `before_tool_call`/`after_tool_call` 构造参数，断言它们在真实的 `arespond()` 调用里生效；不
      传时断言现状行为（并发执行）不变。预期：`ReActAgent.__init__` 还没有这些构造参数，
      `TypeError`，测试失败。

### Implementation (ReActAgent 接入)

- [X] T037 [US3] 修改 `packages/agents/react_agent.py`：`ReActAgent.__init__` 新增
      `tool_execution_mode: Literal["sequential", "parallel"] = "parallel"`、
      `before_tool_call`/`after_tool_call` 构造参数，存成实例属性并在 `arespond()` 每次调用
      `execute_model_step(...)` 时透传（depends on: T034, T036）
- [X] T038 [US3] 跑 `.venv/bin/pytest tests/agents/test_react_agent.py -v`，确认全部通过（depends
      on: T037）
- [X] T039 [US3] 跑 `.venv/bin/pytest tests/core/ tests/agents/ -v`，确认本故事范围内全部测试通
      过、无回归（depends on: T035, T038）

**Checkpoint**：工具执行模式与前后钩子已上线，现状默认行为（全并发、无钩子）保持不变。

---

## Phase 6: User Story 4 - `finishTurn` 钩子替代 ReAct 的内置 `finish` 工具 (Priority: P4)

**Goal**：新增 `finish_turn` 钩子判定一轮结束后继续/结束/维持原调度；`ReActAgent` 删除 `finish` 工
具机制，改用这套钩子。

**Independent Test**：`finish_turn` 返回 `"end"` 时运行立即停止（哪怕还有工具调用）；返回
`"continue"` 时哪怕没有工具调用/排队消息也确保再跑一轮；一次完整 ReAct 对话在新机制下仍能正确结
束。

### Tests for User Story 4 ⚠️

- [X] T040 [P] [US4] 在 `tests/core/test_agent_loop.py` 新增：`finish_turn` 返回 `"end"` 时断言
      `run_tool_turn`/外层循环在这一轮之后立即停止，不再发起下一次模型调用（哪怕
      `completion.requested_tools` 非空）；返回 `"continue"` 且这一轮没有工具调用/排队消息时，断
      言确实又发起了恰好一次模型调用；返回 `None` 时断言维持现有调度（有工具调用就继续、没有就
      停）；一轮因 `OutputLimitError`/`EmptyModelResponse` 结束时断言 `finish_turn` 完全没有被调
      用。预期：`run_tool_turn` 还没有 `finish_turn` 参数，`TypeError`，测试失败。
- [X] T041 [US4] 跑 `.venv/bin/pytest tests/core/test_agent_loop.py -v`，确认按预期原因失败
      （depends on: T040）

### Implementation for User Story 4

- [X] T042 [US4] 在 `packages/core/protocol.py` 新增 `TurnDecision = Literal["continue", "end"] |
      None` 类型别名和 `TurnContext` dataclass（`step: int`, `completion: ToolCompletion`,
      `tool_results: list[dict[str, str]]`）
- [X] T043 [US4] 修改 `packages/core/agent_loop.py`：`run_tool_turn` 新增
      `finish_turn: Callable[[TurnContext], Awaitable[TurnDecision]] | None = None` 参数——每一步
      `execute_model_step` 返回之后（在原有的"`requested_tools` 为空就 `return`"判断之前）调用
      `finish_turn`（`None` 时跳过）；返回 `"end"` 立即 `return`；返回 `"continue"` 强制再跑一步
      （即使 `requested_tools` 为空且 follow-up 为空）；返回 `None` 维持原判断（depends on: T042）
- [X] T044 [US4] 跑 `.venv/bin/pytest tests/core/test_agent_loop.py -v`，确认全部通过（depends on:
      T043）

### Tests for User Story 4 (ReActAgent 接入) ⚠️

- [X] T045 [US4] 在 `tests/agents/test_react_agent.py`：删除
      `test_finish_tool_is_offered_even_without_a_tool_registry`（`finish` 工具本身被移除，这条测
      试断言的前提不再成立）；重写 `test_arespond_uses_a_tool_then_finishes`/
      `test_arespond_falls_back_to_the_step_limit_message`/
      `test_arespond_asks_for_approval_and_continues_when_denied` 等依赖模型显式调用 `finish` 工
      具的用例，改成依赖"模型不再请求工具时直接产出最终答案"（现状代码已有的默认路径）；新增一个
      测试，构造 `ReActAgent` 并传入自定义 `finish_turn` 钩子，断言它能在工具调用仍然非空的情况下
      强制提前结束运行。预期：这些重写后的用例在 `react_agent.py` 删除 `finish` 工具机制之前，因
      为 `scripted_client` 的脚本化响应不再触发 `finish` 调用而无法通过（或自定义 `finish_turn`
      参数本身不存在而报 `TypeError`）。

### Implementation (ReActAgent 接入)

- [X] T046 [US4] 修改 `packages/agents/react_agent.py`：删除 `FINISH_TOOL_NAME`/
      `FINISH_TOOL_SCHEMA`/`_read_final_answer`/`_tool_schemas()` 里拼 `FINISH_TOOL_SCHEMA` 那部
      分/`_handle()` 里对 `FINISH_TOOL_NAME` 的特判/`arespond()` 里 `finish_calls` 拦截整段；
      `arespond()` 的循环改成：没有 `requested_tools` 时直接 `answer = completion.text; break`（现
      有分支已经这样做，只是现在这是唯一的"正常结束"路径）；新增 `finish_turn` 构造参数并透传给
      每次 `execute_model_step(...)` 调用；`DEFAULT_SYSTEM_PROMPT` 删除"调用 `finish` 工具"的措
      辞，改成单纯描述"推理+工具调用交替，给出最终回复"（depends on: T043, T045）
- [X] T047 [US4] 修改 `packages/agents/builder.py`：`_append_suffix()` 上方的注释"追加（而不是替
      换）是为了保住 ReAct 的 finish 工具约定这条默认提示词"已过期，改成准确描述当前
      `DEFAULT_SYSTEM_PROMPT` 的用途（depends on: T046）
- [X] T048 [US4] 跑 `.venv/bin/pytest tests/agents/test_react_agent.py -v`，确认全部通过（depends
      on: T046, T047）
- [X] T049 [US4] 跑 `.venv/bin/pytest tests/core/ tests/agents/ -v`，确认本故事范围内全部测试通
      过、无回归（depends on: T044, T048）

**Checkpoint**：`finish` 工具机制已彻底移除，`finishTurn` 钩子承担全部终止判定职责。

---

## Phase 7: User Story 5 - 消息模型分层：`AgentMessage` 与 LLM `Message` 分开 (Priority: P5)

**Goal**：`ChatMessage.role` 放宽为开放字符串；`build_messages()` 过滤掉非标准 LLM 角色；新增
`transform_context` 钩子。

**Independent Test**：插入一条自定义角色消息，断言它出现在历史快照里但不出现在实际发给模型的消息
列表里；`transform_context` 生效且异常时能降级。

### Tests for User Story 5 ⚠️

- [X] T050 [P] [US5] 在 `tests/core/test_protocol.py`（不存在则新建）新增：`ChatMessage(role=
      "notification", content="...")` 能正常构造，不再因为 `role` 不在封闭 `Literal` 里而被
      Pydantic 拒绝。预期：当前 `SpeakerRole` 是封闭 `Literal`，构造报 `ValidationError`，测试失
      败。
- [X] T051 [P] [US5] 在 `tests/memory/test_working.py`（或现有覆盖 `build_messages` 的测试文件）
      新增：历史里混入一条 `role="notification"` 的消息，`build_messages()` 返回的列表里不包含
      它；`role="tool"`/`role="summary"` 两种既有特殊角色的转换行为不受影响。预期：现有 `else` 分
      支会把这条消息原样透传进返回列表，断言"不包含它"失败。
- [X] T052 [US5] 跑 `.venv/bin/pytest tests/core/test_protocol.py tests/memory/test_working.py
      -v`，确认按预期原因失败（depends on: T050, T051）

### Implementation for User Story 5

- [X] T053 [US5] 修改 `packages/core/protocol.py`：`SpeakerRole` 从
      `Literal["user", "assistant", "system", "tool", "summary"]` 改为 `str`
- [X] T054 [US5] 修改 `packages/memory/working.py`：`build_messages()` 新增模块级常量
      `_LLM_ROLES = frozenset({"user", "assistant", "system"})`；现有 `else` 分支（处理
      `tool`/`summary` 之外的角色）改成"`message.role in _LLM_ROLES` 才追加，否则跳过"（depends
      on: T053）
- [X] T055 [US5] 跑 `.venv/bin/pytest tests/core/test_protocol.py tests/memory/test_working.py
      -v`，确认全部通过（depends on: T054）

### Tests for User Story 5 (transform_context + ReActAgent 接入) ⚠️

- [X] T056 [P] [US5] 在 `tests/core/test_agent.py` 新增：提供 `transform_context` 回调（返回一份
      裁剪/改写过的历史），断言 `Agent`/`ReActAgent` 生成的最终 `messages` 基于这个返回值而不是原
      始历史；`transform_context` 内部抛异常时，断言运行不崩溃、改用原始历史继续。预期：
      `Agent.__init__`/`build_messages`-调用路径 还没有这个钩子，`TypeError`/断言失败。

### Implementation (transform_context + ReActAgent 接入)

- [X] T057 [US5] 修改 `packages/core/agent.py`：`Agent.__init__` 新增
      `transform_context: Callable[[list[ChatMessage]], Awaitable[list[ChatMessage]]] | None =
      None` 构造参数；新增一个方法（如 `apply_transform_context`）在拿到 `history_snapshot()` 之
      后、调用 `build_messages()` 之前调用它，异常时吞掉（记一条 trace 事件，若有 recorder）、改
      用原始历史（depends on: T054, T056）
- [X] T058 [US5] 跑 `.venv/bin/pytest tests/core/test_agent.py -v`，确认全部通过（depends on:
      T057）
- [X] T059 [US5] 修改 `packages/agents/react_agent.py`：`ReActAgent.__init__` 透传
      `transform_context` 构造参数给 `super().__init__()`；`arespond()` 里 `build_messages()` 调
      用前改用 T057 新增的方法（depends on: T057）
- [X] T060 [US5] 跑 `.venv/bin/pytest tests/core/ tests/agents/ -v`，确认本故事范围内全部测试通
      过、无回归（depends on: T058, T059）

**Checkpoint**：应用专属消息角色能安全混入历史而不泄漏给模型，`transform_context` 钩子可用。

---

## Phase 8: User Story 6 - 请求级前置钩子：`prepare_request`/`prepare_next_turn` (Priority: P6)

**Goal**：新增两个请求级钩子，可动态替换上下文/模型/推理等级；优先级按调用时机的先后顺序自然成
立。

**Independent Test**：`prepare_request` 在第二次请求把 `model` 换成另一个实例，断言第二次请求用新
模型、第一次不受影响。

### Tests for User Story 6 ⚠️

- [X] T061 [P] [US6] 在 `tests/core/test_agent_loop.py` 新增：`prepare_request` 在第二次
      `execute_model_step` 调用时把 `model` 换成一个不同的 mock `ModelClient`，断言第二次请求确实
      用新模型（通过断言这个 mock 被调用过）、第一次请求用的还是原模型；`prepare_request` 在第一
      次调用（即最早一次请求）也会被调用一次。预期：`TypeError`（未知关键字参数），测试失败。
- [X] T062 [P] [US6] 在 `tests/core/test_agent_loop.py` 新增：`prepare_next_turn` 在一轮结束、确
      定要继续时被调用一次，其返回的 `context` 覆盖下一轮使用的历史；两个钩子都未提供时维持现状行
      为（模型/上下文不变）。预期：`TypeError`，测试失败。
- [X] T063 [US6] 跑 `.venv/bin/pytest tests/core/test_agent_loop.py -v`，确认按预期原因失败
      （depends on: T061, T062）

### Implementation for User Story 6

- [X] T064 [US6] 在 `packages/core/protocol.py` 新增 `RequestOverrides` dataclass
      （`context: list[ChatMessage] | None = None`, `model: ModelClient | None = None`,
      `thinking_level: ThinkingLevel | None = None`）和 `RequestContext` dataclass（`step: int`,
      `messages: list[dict[str, Any]]`）
- [X] T065 [US6] 修改 `packages/core/agent_loop.py`：`execute_model_step` 新增
      `prepare_request: Callable[[RequestContext], Awaitable[RequestOverrides | None]] | None =
      None` 参数，在调用 `_call_model` 之前调用（每次都调），非 `None` 字段覆写这次请求要用的
      `messages`/`model_client`/推理等级；`run_tool_turn` 新增
      `prepare_next_turn: Callable[[], Awaitable[RequestOverrides | None]] | None = None` 参数，
      在"确定继续下一步"之后、下一次 `execute_model_step` 调用之前调用一次，覆写下一轮默认使用的
      值（depends on: T064）
- [X] T066 [US6] 跑 `.venv/bin/pytest tests/core/test_agent_loop.py -v`，确认全部通过（depends on:
      T065）

### Implementation (ReActAgent 接入)

- [X] T067 [US6] 修改 `packages/agents/react_agent.py`：`ReActAgent.__init__` 新增
      `prepare_request`/`prepare_next_turn` 构造参数并在 `arespond()` 里透传给对应调用（depends
      on: T065）
- [X] T068 [US6] 跑 `.venv/bin/pytest tests/core/ tests/agents/ -v`，确认本故事范围内全部测试通
      过、无回归（depends on: T066, T067）

**Checkpoint**：请求级前置钩子可用，默认不提供时行为与现状完全一致。

---

## Phase 9: User Story 7 - 分级推理预算：`thinking_level`/`thinking_budgets` (Priority: P7)

**Goal**：`ModelClient.thinking_level` 成为运行期可读写的七档属性，按后端分别转译为已支持的参数。

**Independent Test**：设置 `thinking_level="high"`，断言请求携带对应参数；运行期改成 `"off"`，断言
下一次请求不再携带。

### Tests for User Story 7 ⚠️

- [ ] T069 [P] [US7] 在 `tests/core/test_model.py`（或现有覆盖 `ModelClient` 的测试文件）新增：
      OpenAI 兼容后端下，`thinking_level` 为 `"off"` 时请求不携带 `reasoning_effort`；
      `"minimal"`/`"low"` → 请求携带 `reasoning_effort="low"`；`"medium"`/`"high"` →
      `"high"`；`"xhigh"`/`"max"` → `"max"`；运行期从 `"low"` 改成 `"off"` 后下一次请求不再携带。
      预期：`ModelClient` 还没有 `thinking_level` 属性，`AttributeError`，测试失败。
- [ ] T070 [P] [US7] 同一个测试文件新增：Anthropic 后端下，`thinking_level` 非 `"off"` 时请求携带
      `thinking={"type": "enabled", "budget_tokens": ...}`，这个数值来自构造时传入的
      `thinking_budgets` 映射表（自定义值能覆盖默认值）；`"off"` 时不携带 `thinking` 参数。预期：
      同上，测试失败。
- [ ] T071 [US7] 跑 `.venv/bin/pytest tests/core/test_model.py -v`，确认按预期原因失败（depends
      on: T069, T070）

### Implementation for User Story 7

- [ ] T072 [US7] 在 `packages/core/protocol.py` 新增 `ThinkingLevel = Literal["off", "minimal",
      "low", "medium", "high", "xhigh", "max"]` 类型别名和一个内置默认预算表常量（如
      `DEFAULT_THINKING_BUDGETS: dict[ThinkingLevel, int]`，覆盖除 `"off"` 外的六档）
- [ ] T073 [US7] 修改 `packages/core/model.py`：`ModelClient` 新增 `thinking_level: ThinkingLevel`
      运行期可读写实例属性（默认 `"off"`，若构造时提供了 `reasoning_effort` 则折算出一个等价初
      值）、`thinking_budgets: dict[ThinkingLevel, int] | None = None` 构造参数（未提供时用 T072
      的默认表）；`_build_call_kwargs` 新增按后端类型（`isinstance(self._backend,
      OpenAICompatibleBackend)` vs `ClaudeBackend`）转译 `thinking_level` 的逻辑，按
      `contracts/request-and-message-hooks.md` 的映射表（depends on: T072）
- [ ] T074 [US7] 跑 `.venv/bin/pytest tests/core/test_model.py -v`，确认全部通过（depends on:
      T073）

### Implementation (ReActAgent 接入)

- [ ] T075 [US7] 修改 `packages/agents/react_agent.py`：构造 `ModelClient` 的地方不再传
      `reasoning_effort`，改为构造后设置 `model_client.thinking_level = ...`（默认
      `"off"`，与现状"未配置环境变量"的默认行为一致）（depends on: T073）
- [ ] T076 [US7] 跑 `.venv/bin/pytest tests/core/ tests/agents/ -v`，确认本故事范围内全部测试通
      过、无回归（depends on: T074, T075）

**Checkpoint**：七档分级推理可用，`"off"` 时行为与现状默认完全等价。

---

## Phase 10: Polish & Cross-Cutting Concerns

- [ ] T077 [P] 跑 `.venv/bin/pytest tests/ -v`，确认全量测试通过数不低于 T001 记录的基线（扣除本次
      明确删除/重写的用例：`test_steering_interrupts_an_in_flight_model_call_and_retries`、
      `test_finish_tool_is_offered_even_without_a_tool_registry`，其余不得有回归）
- [ ] T078 [P] 跑 `.venv/bin/python scripts/check_core_boundary.py`，确认退出码仍为 `0`（SC-004）
- [ ] T079 按 `quickstart.md` 列出的 11 个验证场景逐条手动过一遍（场景 8 的真机验证在无凭据环境下
      记录为 `SKIPPED`，有凭据环境下记录真实通过结果），确认每一条实际结果都和文档预期一致
- [ ] T080 [P] 补一条 `tests/core/test_real_model_selftest.py` 的真机场景（SC-008）：有凭据时跑一
      次会触发工具调用的真实对话，断言事件总线产生了真实事件、`finish_turn` 判定了真实的终止；无
      凭据时 `SKIPPED`
- [ ] T081 [P] 按本仓库既有习惯更新项目 memory（`project_opentalos_python_rebuild.md` 追加这次
      pi-agent-core 对齐的记录 + `MEMORY.md` 索引行），记录涉及的文件范围、两处确认的行为替换、真
      机验证结果

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**：无依赖，立即开始
- **Foundational (Phase 2)**：本功能无此阶段内容（见上方说明）
- **User Story 1 (Phase 3)**：依赖 Setup 完成；是其余 6 条 User Story 在"时序描述"上的地基，建议
  最先完成
- **User Story 2 (Phase 4)**：依赖 Setup 完成；**不**编译期依赖 US1（`SteerQueue`/`followup` 改动
  完全独立于事件总线），但建议在 US1 之后做，保持 `agent_loop.py` 改动的提交粒度清晰
- **User Story 3 (Phase 5)**：依赖 Setup 完成；同样不编译期依赖 US1/US2，建议顺序做
- **User Story 4 (Phase 6)**：`TurnContext` 读取的是 `execute_model_step` 返回的 `completion`，不
  依赖 US1-US3 的具体实现，但由于都改 `agent_loop.py`/`react_agent.py` 同一批文件，顺序执行能避免
  合并冲突
- **User Story 5 (Phase 7)**：`transform_context` 独立于前四条；`SpeakerRole` 放宽本身没有依赖
- **User Story 6 (Phase 8)**：`prepare_request`/`prepare_next_turn` 的优先级规则（决策 7）依赖
  `finish_turn`（US4）已经存在以确立"先 `finish_turn` 后 `prepare_next_turn`"这条时序关系的实际代
  码位置，建议在 US4 之后做
- **User Story 7 (Phase 9)**：`thinking_level` 可以被 `RequestOverrides`（US6）引用，建议在 US6 之
  后做，但本身不强制依赖
- **Polish (Phase 10)**：依赖全部 7 条 User Story 完成

### Within Each User Story

- 先写测试、确认失败，再实现，再确认通过（TDD 红-绿），对应 constitution 原则 I
- 每完成一个 checkpoint 就提交一次 commit（本仓库既定习惯：直接提交到 main，不开 feature branch）

### Parallel Opportunities

- 同一故事内标 `[P]` 的测试任务（如 T003/T004、T017/T018、T029/T030、T050/T051、T061/T062、
  T069/T070）可以并行写，因为落在不同文件或断言互相独立
- Polish 阶段的 T077/T078/T080/T081 互不依赖，可以并行执行

---

## Parallel Example: User Story 1

```bash
# 并行写两个测试文件（T003/T004）：
Task: "在 tests/core/test_agent.py 新增 subscribe()/_emit() 的顺序与错误隔离测试"
Task: "在 tests/core/test_agent_loop.py 新增 emit 参数的事件序列测试"
```

---

## Implementation Strategy

### MVP First（User Story 1 单独交付）

1. 完成 Phase 1：Setup
2. 完成 Phase 3：User Story 1（事件总线 + `ReActAgent`/`apps/api` 实际接入）
3. **停下来验证**：T016 独立确认 User Story 1 达标——即使 US2-US7 还没做，维护者已经能通过订阅事
   件总线看清一次运行的完整时序，这本身就是可用的增量价值

### Incremental Delivery

1. Setup → User Story 1（MVP，事件总线）→ 独立验证 → 提交
2. 加 User Story 2（steering/follow-up 轮询化，移除打断）→ 独立验证 → 提交——**这一步会改变已上
   线的用户可感知行为**，提交信息需要明确标注这是预期的行为变更
3. 加 User Story 3（工具执行模式/钩子）→ 独立验证 → 提交
4. 加 User Story 4（`finishTurn` 替代 `finish` 工具）→ 独立验证 → 提交——**这一步同样是预期的行为
   替换**
5. 加 User Story 5（消息分层）→ 独立验证 → 提交
6. 加 User Story 6（请求级钩子）→ 独立验证 → 提交
7. 加 User Story 7（分级推理）→ 独立验证 → 提交
8. Polish（Phase 10）收尾

### 单 Agent 顺序执行策略（本仓库既定协作模式）

本仓库这次计划预期由单个 agent 按 T001→T081 顺序连续执行，不是多人并行分工；上面的 Parallel
Opportunities 仅供同一个 agent 在单个任务内部批量处理同类文件时参考，不代表需要拆成多个 agent 同
时跑。
