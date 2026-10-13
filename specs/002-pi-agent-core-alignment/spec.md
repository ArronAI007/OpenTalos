# Feature Specification: packages/core 对齐 pi 的 agent-core 内核架构

**Feature Branch**: `002-pi-agent-core-alignment`

**Created**: 2026-10-13

**Status**: Draft

**Input**: User description: "仓库中的core目录完全要按照 https://github.com/earendil-works/pi/tree/main/packages/agent 的内核实现，只是pi的开发语言是TypeScript，我们是python"

## 参考实现核实记录（写 spec 前直接读的源码，不是转述）

已克隆 `earendil-works/pi` 仓库，直接读了 `packages/agent/src/{agent.ts, agent-loop.ts, types.ts}` 和
该包的 README。确认的关键架构事实：

- **事件总线**：`Agent.subscribe(listener)` 是一个发布/订阅接口，监听器按注册顺序被 `await`；事件种
  类远比"开始/结束/失败"丰富——`agent_start`/`agent_end`、`turn_start`/`turn_end`、
  `message_start`/`message_update`/`message_end`（对 system/user/assistant/toolResult **每一种**
  消息都发，不只是 assistant）、`tool_execution_start`/`tool_execution_update`/`tool_execution_end`。
- **Steering 和 Follow-up 是两个独立队列，且都是"轮询"语义，不是"打断"语义**：`getSteeringMessages`
  在**当前这一步的工具调用全部执行完之后**才被轮询、注入下一次请求，不会取消/打断正在进行中的模型
  调用或工具执行；`getFollowUpMessages` 只有在"没有更多工具调用、也没有排队的 steering 消息"时才会
  被轮询。两个队列各自有独立的 `QueueMode`（`"one-at-a-time"` 或 `"all"`）。
- **工具执行模式可配置**：全局默认 `"parallel"`（先顺序 preflight 完校验/审批，再并发真正执行），可
  整体切成 `"sequential"`；单个工具可以用 `executionMode` 覆盖全局设置，一个批次里只要有一个工具要
  求顺序执行，整批就退化成顺序执行。
- **`beforeToolCall`/`afterToolCall` 钩子**：前者能在参数校验后拦截（`block`）执行并自定义错误文案；
  后者能覆写已执行结果的部分字段（`content`/`details`/`isError`/`structuredContent`）。两者都能设置
  `terminate: true`——但只有当**这一批次里每一个被终结的工具结果都设了这个标记**时，循环才会提前结
  束；混合批次按正常流程继续。
- **`finishTurn` 钩子**：在一轮的 assistant 消息和全部工具结果都落定之后、`turn_end` 之前被调用，返
  回 `{action: "continue"}`/`{action: "end"}`/`undefined`（维持原调度）。`undefined` 保持现状逻辑
  （有工具调用就继续、没有就停）；error/aborted 的响应永远是硬性退出，不受这个钩子影响。
- **`prepareRequest`/`prepareNextTurn` 钩子**：前者在**每一次**模型请求（包括第一次）发起前被调用，
  可以替换本次请求用的 `context`/`model`/`thinkingLevel`，不轮询队列；后者在 `turn_end` 之后、下一
  轮开始前被调用，同样可以替换下一轮用的 context/model/thinkingLevel，或者追加消息。
- **状态模型**：`Agent.state` 暴露 `model`/`thinkingLevel`/`tools`/`messages`/`isStreaming`/
  `streamingMessage`/`pendingToolCalls`（只读 Set）/`errorMessage`；`tools`/`messages` 是
  getter/setter，赋值时拷贝顶层数组。
- **消息模型分层**：`AgentMessage`（应用层，可通过声明合并扩展自定义角色）与 LLM 实际认识的
  `Message`（`system`/`user`/`assistant`/`toolResult`）是两层；`convertToLlm()` 在每次调用模型前把
  前者转成后者（过滤掉 UI-only 消息）；`transformContext()` 在 `convertToLlm` 之前跑，用于裁剪历
  史/注入外部上下文。
- **分级推理（`thinkingLevel`/`thinkingBudgets`）**：`off|minimal|low|medium|high|xhigh|max` 七档，
  每档可以自定义 token 预算，运行期可通过 `agent.state.thinkingLevel` 动态切换。本仓库
  `packages/core/model.py` 目前只有一个扁平的 `reasoning_effort: str | None`（来自
  `MODEL_REASONING_EFFORT` 环境变量，值是 `low|high|max` 三档，给 kimi-k3 这类 always-on-thinking
  模型用），构造 `ModelClient` 时或单次调用的 `**kwargs` 里才能覆盖，不是 agent 运行期可随时读写的
  状态，也没有"每档对应多少 token 预算"这个概念。
- **底层/高层两套 API**：`agentLoop`/`agentLoopContinue` 是无状态的异步生成器（纯函数式的事件流）；
  `Agent` 类在其上包一层状态管理（transcript、两个队列、事件分发、生命周期）。

这是一套比本仓库 `packages/core` 现在拥有的能力丰富得多的架构（现状只有
`AgentPhase.STARTED/FINISHED/FAILED` 三段式回调 + `on_text_delta`/`on_reasoning_delta`/
`on_tool_result`/`on_usage` 几个专用回调 + 上一个功能（`001-core-isolation-selftest`）刚实现的、基
于"打断正在进行的模型调用"的单一 `SteerQueue`）。

## Clarifications

### Session 2026-10-13

- Q: 整体范围——这次 spec/plan/实现周期要覆盖到参考实现的哪个广度？ → A: 范围 C——不只是事件总线 +
  steering/follow-up 拆分 + 工具执行模式/钩子（原 User Story 1-3），连 `thinkingLevel`/
  `thinkingBudgets`、`prepareRequest`/`prepareNextTurn`、`AgentMessage` 与 LLM `Message` 分层（含
  Python 版的"声明合并"等价机制）也一并纳入本次范围，不推迟。
- Q: Steering 要不要放弃"打断正在进行的模型调用"这个刚上线的能力，换成 pi 式的纯"轮询"语义（FR-006）？
  → A: 换成 pi 式轮询语义，完全移除打断能力——`001-core-isolation-selftest` 里新增的
  `SteerQueue.interrupt_event`/`ModelInterrupted` 这条"取消在飞的模型调用"的路径本次整体移除，不是
  新增轮询语义后两者并存。对应的回归测试
  `test_steering_interrupts_an_in_flight_model_call_and_retries` 这次会被**删除或重写**，不是继续
  保持通过——这是一次刻意的、经确认的行为变更，不是意外回归。
- Q: 运行终止机制——要不要用 `finishTurn` 钩子替换掉 `ReActAgent` 现有的"模型调用内置 `finish` 工具"
  机制（FR-011）？ → A: 替换。`packages/agents/react_agent.py` 的 `FINISH_TOOL_NAME`/
  `FINISH_TOOL_SCHEMA`/`_read_final_answer` 这套机制本次会被移除，改成由 `finishTurn` 钩子判断一轮
  结束后是继续还是停；这同样是一次经确认的、对已上线 ReAct 行为的替换。
- Q: 除了 steering 轮询化和 finishTurn 替换 finish 工具这两处已经明确要改的行为之外，另外 5 个新能
  力（事件总线、工具执行模式+钩子、消息分层、prepareRequest/prepareNextTurn、thinkingLevel）是否也
  要求 `packages/agents/react_agent.py`（以及 `apps/api/runtime.py`/`packages/agents/builder.py`）
  实际接入使用？ → A: 全部接入。7 个 User Story 对应的能力都要求被 `react_agent.py`/`builder.py`/
  `runtime.py` 实际消费，不留"`packages/core` 里建好了但没有任何消费方使用"的能力。
- Q: `beforeToolCall`/`afterToolCall` 钩子自身抛出异常时，系统默认应该让工具调用继续执行
  （fail-open）还是当作被拦截处理（fail-closed）？ → A: fail-closed——钩子异常时把这次工具调用当
  作被拦截处理，报出明确标注"钩子自身出错"的错误结果，不静默放行，与宪法"输入必须校验"原则的保守
  精神保持一致。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 细粒度事件总线替代"开始/结束/失败"三段式 (Priority: P1)

维护者（人类或 AI 编码代理）需要能订阅一次运行里发生的每一件具体事情——每条消息的开始/流式更新/结
束、每次工具执行的开始/进度/结束、每个回合（turn）的开始/结束——而不是现在只有
`started`/`finished`/`failed` 三种粗粒度阶段信号，外加几个各管一摊的专用回调
（`on_text_delta`/`on_reasoning_delta`/`on_tool_result`/`on_usage`）东拼西凑才能看全。

**Why this priority**: 这是整套对齐工作的地基——后续 Steering/Follow-up 的轮询时机、`finishTurn` 的
调用时机、`prepareRequest`/`prepareNextTurn` 的生效点，都要挂在这套事件时序上描述和验证；不先把事
件粒度对齐，后面的故事没有统一的时间参照系。

**Independent Test**: 订阅一次只调用模型、不涉及工具调用的简单运行，断言收到的事件序列恰好是
`run_start → turn_start → message_start(user) → message_end(user) → message_start(assistant) →
message_update(assistant)* → message_end(assistant) → turn_end → run_end`，可以独立验证，不需要
先完成其他 Story。

**Acceptance Scenarios**:

1. **Given** 一次不涉及任何工具调用的纯文本问答，**When** 订阅事件流完整跑完这次运行，**Then** 能
   看到每一条消息（不只是 assistant）各自的开始/结束事件，以及这次运行自身的开始/结束事件。
2. **Given** 一次触发了工具调用的运行，**When** 订阅事件流，**Then** 能看到工具执行自己的开始/结
   束事件，且事件携带的信息足以区分"是哪一次工具调用"（调用 id、工具名、参数、结果、是否出错、耗
   时）。
3. **Given** 多个监听器订阅了同一次运行，**When** 运行产生一个事件，**Then** 所有监听器按注册顺序
   依次被等待执行完，不是并发触发、也不是只通知第一个。
4. **Given** 一次运行已经发出了"运行结束"事件，**When** 该事件对应的监听器还没执行完，**Then** 这
   次运行不能被视为"已经空闲/可以发起下一次运行"，必须等所有监听器跑完。
5. **Given** `packages/agents/react_agent.py` 是本仓库目前唯一的 `packages/core` 消费方，**When**
   本次功能交付，**Then** `ReActAgent` 必须实际订阅并使用这套新事件总线（而不是仅仅在
   `packages/core` 内部实现、没有任何调用方真正用上）；现有的 `PhaseCallback`/
   `on_text_delta`/`on_reasoning_delta`/`on_tool_result`/`on_usage` 这几个专用回调要么被这套事件
   总线取代，要么改造成基于事件总线订阅实现的薄封装，不能继续维护两套平行的、互不相关的通知机制。

---

### User Story 2 - Steering 与 Follow-up 拆成两条独立队列，完全改成"轮询"而非"打断" (Priority: P2)

维护者需要把"运行中途插入一条消息"这件事，按参考实现拆成两种语义不同的能力：**steering**（在当前
这一步的工具调用全部跑完之后插入，绝不打断任何正在进行的模型调用或工具执行）和 **follow-up**（只
有在"没有更多工具调用、也没有排队的 steering 消息"时才插入，用于"运行本来要停了，但还有事情要追
加"的场景）。这是一次经确认的行为变更：现有的"打断正在飞的模型调用"能力（`SteerQueue.
interrupt_event`/`ModelInterrupted`）本次整体移除。

**Why this priority**: 这是本次范围里**唯一会改变已上线、已有真机验证的用户可感知行为**的部分——
之前"发一条纠偏消息能立刻打断模型重新思考"的体验，之后会变成"等这一步的工具调用跑完才生效"。放在
事件总线之后、优先级第二，确保改动前有清晰的事件时序可以验证这个变化的边界。

**Independent Test**: 构造一次会触发工具调用的运行，在工具调用执行期间排队一条 steering 消息，断
言：(a) 正在执行的工具调用没有被取消、跑到正常结束；(b) 排队的消息在下一次模型请求前被注入，且这
次运行全程没有产生任何"模型调用被取消/中途打断"的事件或异常。再构造一次没有更多工具调用的运行，排
队一条 follow-up 消息，断言它被注入且运行又多跑了一轮。

**Acceptance Scenarios**:

1. **Given** 模型请求了一次工具调用且工具正在执行，**When** 此时排队一条 steering 消息，**Then**
   正在执行的工具调用不受影响、正常跑完，steering 消息在这一步的工具结果都落定之后才被注入进下一
   次模型请求；**且**不存在任何机制能取消一次正在进行中的模型调用。
2. **Given** 一轮运行已经没有待处理的工具调用、也没有排队的 steering 消息，**When** 此时排队一条
   follow-up 消息，**Then** 这条消息被注入，运行继续多跑一轮，而不是直接结束。
3. **Given** steering 队列和 follow-up 队列里同时都有排队消息，**When** 到达"轮询两个队列"的时间
   点，**Then** steering 优先于 follow-up 被注入（follow-up 只在"没有 steering 消息"时才轮到）。
4. **Given** 某个队列的模式设置为 `"one-at-a-time"`，**When** 队列里有 3 条排队消息，**Then** 单
   次轮询只取出并注入最早的 1 条，其余 2 条留到下一次轮询时机；设置为 `"all"` 时一次性全部取出。

---

### User Story 3 - 工具执行模式可配置 + before/afterToolCall 钩子 (Priority: P3)

维护者需要能把工具调用从默认的并发执行整体切换成顺序执行，也需要能给单个工具单独标记"这个工具必须
顺序执行"；同时需要在工具真正执行前后插入检查点——执行前能拦截/拒绝某次调用并自定义给模型看的错误
文案，执行后能覆写结果的部分字段（不需要整个替换）。

**Why this priority**: 这是对现有行为的增量扩展（现状是"永远并发执行、没有执行前后钩子"），不改变
任何已有测试断言的默认行为，风险和复杂度都低于 Story 2。

**Independent Test**: 构造一次批量工具调用（3 个工具），其中 1 个标记为必须顺序执行，断言整批退化
成顺序执行；另起一次没有任何工具标记顺序执行的批量调用，断言仍然是并发执行（不影响现状默认行为）。
`beforeToolCall`/`afterToolCall` 分别单独测试其拦截/覆写效果。

**Acceptance Scenarios**:

1. **Given** 全局工具执行模式是默认值，**When** 一批里的某一个工具自己声明了"必须顺序执行"，
   **Then** 这一整批工具调用都退化成顺序执行，不只是那一个工具。
2. **Given** `beforeToolCall` 对某次调用返回"拦截"，**When** 这次工具调用本该被执行，**Then** 它
   不会真正执行，模型收到的是一条明确标注"被拦截"原因的错误结果。
3. **Given** `beforeToolCall`/`afterToolCall` 钩子自身执行时抛出异常（不是正常返回值），**When**
   这次工具调用本该被处理，**Then** 系统按 fail-closed 处理：这次调用被当作拦截，模型收到一条明
   确标注"钩子自身出错"的错误结果，异常不会向上传播打断整轮运行。
4. **Given** `afterToolCall` 对某次执行结果返回了部分字段覆写（比如只覆写 `details`），**When** 这
   次工具调用执行完毕，**Then** 最终呈现给模型的结果里被覆写的字段生效，其余字段保持工具原始执行
   结果不变。
5. **Given** 一个批次里有多个工具调用，其中一部分通过各自的钩子/执行结果标记了"建议提前结束"，
   **Then** 只有当这一批次里**每一个**被终结的调用都标记了"建议提前结束"时，运行才会提前结束；只
   要有一个没标记，运行按正常流程继续。
6. **Given** `ReActAgent` 现有的工具调用全部走并发执行、没有执行前后钩子，**When** 本次功能交付，
   **Then** `ReActAgent` 必须实际使用可配置的工具执行模式和 `beforeToolCall`/`afterToolCall` 钩子
   （哪怕默认配置下行为等价于现状），而不是只在 `packages/core` 里实现、`ReActAgent` 从不调用。

---

### User Story 4 - `finishTurn` 钩子替代 ReAct 的内置 `finish` 工具 (Priority: P4)

维护者需要一个统一的、运行结束判定钩子——在一轮的 assistant 消息和全部工具结果都落定之后，由钩子决
定"继续/结束/维持原调度"，而不是像现在这样靠 `ReActAgent` 专门造一个内置 `finish` 工具、让模型显式
调用它来结束运行。

**Why this priority**: 这是一次经确认的、对已上线 ReAct 终止逻辑的替换，风险高于前三条，且依赖事件
总线（Story 1）已经就位才能清楚描述"一轮结束"这个时间点，所以排在后面。

**Independent Test**: 构造一次运行，`finishTurn` 在某一轮返回 `{action: "end"}`，断言运行在那一轮
的 `turn_end` 之后立即结束，不再轮询任何队列、不再发起下一次模型请求；另构造一次 `finishTurn` 返回
`{action: "continue"}` 但这一轮确实没有任何工具调用/排队消息的场景，断言运行确实又多跑了恰好一轮
纯上下文请求。

**Acceptance Scenarios**:

1. **Given** 模型在某一轮之后不再有工具调用，**When** `finishTurn` 对这一轮返回 `{action: "end"}`，
   **Then** 运行在 `turn_end` 之后立刻结束，不轮询 steering/follow-up 队列、不准备下一次请求。
2. **Given** 同样没有工具调用的一轮，**When** `finishTurn` 返回 `{action: "continue"}`，**Then**
   运行确保再发起恰好一次模型请求；如果工具结果/steering/follow-up 已经自然触发了下一次请求，就不
   再额外多发一次。
3. **Given** `finishTurn` 返回 `undefined`（不表态），**Then** 维持现有调度逻辑（有工具调用就继
   续、没有就停）。
4. **Given** 一轮的响应是因为出错或被取消而结束（`error`/`aborted`），**When** 这一轮结束，
   **Then** `finishTurn` 的返回值被忽略，运行始终硬性退出，不受钩子影响。
5. **Given** 本次范围里 `ReActAgent` 已经改用 `finishTurn` 判定终止，**When** 跑一次完整的 ReAct 对
   话（模型经过若干次工具调用后给出最终回复），**Then** 运行能正确在恰当的一轮之后结束，得到的最
   终回复内容和改动前语义等价（即使触发终止的具体机制已经从"模型调用 `finish` 工具"换成了
   `finishTurn` 的判定）。

---

### User Story 5 - 消息模型分层：`AgentMessage` 与 LLM `Message` 分开 (Priority: P5)

维护者需要能往对话历史里插入应用专属的、模型完全看不到的消息类型（例如纯 UI 提示/系统通知），而不
破坏模型实际收到的、必须是标准 `system`/`user`/`assistant`/`tool` 角色的消息格式；也需要能在"转换
成模型能看懂的格式"之前，先对历史做一次独立的处理（裁剪、注入外部上下文）。

**Why this priority**: 这是一个新增的扩展点，不改变任何现有调用方的行为（现有的 `ChatMessage` 继
续是默认情况下唯一用到的消息类型），风险低，但不是本次最紧迫的能力，所以排在中间偏后。Python 没有
TypeScript 的"声明合并"，所以用等价于"注册/鸭子类型"的机制表达同样的扩展能力：任何对象只要满足最
小的消息形状（至少有 `role`/`timestamp`），都可以被放进历史列表；`convert_to_llm()` 负责识别并转
换/过滤。

**Independent Test**: 往历史里插入一条自定义角色的消息（例如 `"notification"`），运行一次对话，断
言：(a) 这条自定义消息确实出现在 `history_snapshot()` 里；(b) 实际发给模型的消息列表里完全不包含
它（被 `convert_to_llm` 过滤掉了）。再独立测一次 `transform_context`：注入一段外部上下文后，断言
它出现在发给模型的消息里。

**Acceptance Scenarios**:

1. **Given** 历史里插入了一条自定义角色（非 system/user/assistant/tool）的消息，**When** 发起下一
   次模型请求，**Then** 这条消息不出现在实际发给模型的消息列表里，但仍然保留在 agent 自己的历史快
   照里。
2. **Given** 调用方提供了一个 `transform_context` 回调，**When** 发起模型请求之前，**Then** 这个
   回调先于"转换成 LLM 消息格式"执行，其返回值（而不是原始历史）被用来生成最终发给模型的消息列
   表。
3. **Given** `convert_to_llm`/`transform_context` 内部抛出异常，**Then** 不能让整轮运行崩溃或卡
   死——必须有清晰的降级路径（具体降级成什么样留给 `/speckit-plan`，这里只约束"调用方提供的转换/
   裁剪逻辑出错，不能让核心循环失控"）。
4. **Given** `ReActAgent` 现有历史表示里只有一种消息类型，**When** 本次功能交付，**Then**
   `ReActAgent` 必须实际用上这套分层机制（即便现状下暂时还没有真正的应用专属消息类型要插入），而
   不是只在 `packages/core` 里实现、`ReActAgent` 从不调用。

---

### User Story 6 - 请求级前置钩子：`prepare_request`/`prepare_next_turn` (Priority: P6)

维护者需要能在**每一次**向模型发起请求之前（包括第一次），动态替换这次请求实际要用的上下文/模型/
推理等级；也需要能在一轮结束、下一轮开始之前做同样的替换——而不是像现在这样，`model_client`/
`context_config` 只能在 Agent 构造时固定一次，运行期间没有任何钩子能介入每一次具体的请求。

**Why this priority**: 这是给需要"运行期动态换模型/动态重建上下文"场景的调用方准备的能力，目前仓
库里没有任何实际调用方有这个需求，纯粹是为了对齐参考实现，所以放在靠后的位置。

**Independent Test**: 提供一个 `prepare_request` 回调，让它在第二次模型请求时把 `model` 换成另一个
（mock）模型实例，断言第二次请求确实用的是替换后的模型，第一次请求不受影响、用的是原始模型。

**Acceptance Scenarios**:

1. **Given** 提供了 `prepare_request` 回调，**When** 每一次模型请求（包括第一次）发起之前，
   **Then** 这个回调都会被调用一次，其返回值里提供的 `context`/`model`/`thinking_level`（如果有）
   会替换掉这次请求原本要用的值，且只影响这一次及之后的请求，不回溯影响已经发出的请求。
2. **Given** 提供了 `prepare_next_turn` 回调，**When** 一轮结束、运行判定要继续时，**Then** 这个
   回调在下一轮开始之前被调用一次，其返回值可以替换下一轮用的 context/model/thinking_level，或者
   追加需要先插入历史的消息。
3. **Given** 两个回调都没有提供，**Then** 维持现有行为（模型/上下文从 Agent 构造时的值不变地延续
   到每一次请求）。
4. **Given** `ReActAgent`/`apps/api/runtime.py` 目前没有任何运行期替换模型/上下文的场景，**When**
   本次功能交付，**Then** 这两个钩子点必须在 `ReActAgent` 的调用路径里实际可用（例如暴露为构造参
   数并在每次请求/每轮前真正被调用一次），而不是只在 `packages/core` 里实现、没有调用方接入。

---

### User Story 7 - 分级推理预算：`thinking_level`/`thinking_budgets` (Priority: P7)

维护者需要一套比现在更完整的推理强度控制——`off`/`minimal`/`low`/`medium`/`high`/`xhigh`/`max` 七
档可选，每一档可以自定义对应的 token 预算，且这个等级是 agent 运行期可读写的状态（不是构造时固定
死的一个字符串）。

**Why this priority**: 现状已经有一个简化版本能用（`MODEL_REASONING_EFFORT` 环境变量 +
`reasoning_effort` 构造参数/调用参数，支持 `low|high|max` 三档），这条故事是在已有基础上做增量扩
展，不是从零到一，紧迫程度最低。

**Independent Test**: 构造一个 agent，设置 `thinking_level = "high"`，断言实际发往模型的请求带着
"high" 档对应的推理强度/token 预算参数；运行期把 `thinking_level` 改成 `"off"` 后再发一次请求，断
言这次请求不再携带推理强度参数，行为等价于现在完全不设置 `MODEL_REASONING_EFFORT` 的默认情况。

**Acceptance Scenarios**:

1. **Given** 某个等级设置了自定义 token 预算，**When** 用这个等级发起请求，**Then** 实际传给模型
   调用层的预算值是这个自定义值，而不是某个写死的默认值。
2. **Given** 运行期把 `thinking_level` 从一个值改成另一个值，**When** 改变之后再发起下一次请求，
   **Then** 新请求使用新等级，之前已经发出的请求不受影响。
3. **Given** `thinking_level` 设为 `"off"`，**Then** 行为必须和现状"完全不设置
   `MODEL_REASONING_EFFORT`、不传 `reasoning_effort`"等价，不能意外给不支持推理强度参数的模型/供
   应商发送这个字段。
4. **Given** `packages/core/model.py` 现有的扁平 `reasoning_effort` 由 `ReActAgent` 构造
   `ModelClient` 时使用，**When** 本次功能交付，**Then** `ReActAgent` 必须改用这套新的七档
   `thinking_level`/`thinking_budgets` 机制替换现有 `reasoning_effort` 用法，而不是让新机制只存在
   于 `packages/core` 里、`ReActAgent` 继续用旧的扁平参数。

### Edge Cases

- 一个工具执行时间很长、迟迟不返回，期间 steering 队列和 follow-up 队列都有消息排队——两者都必须
  等这次工具执行真正结束才被轮询，不能因为队列里有消息就提前打断正在执行的工具（对应 Story 2 已经
  确认移除"打断"能力这个前提）。
- `beforeToolCall`/`afterToolCall` 本身抛出异常（而不是正常返回"拦截"/"放行"或字段覆写）——必须按
  fail-closed 处理：把这次工具调用当作被拦截，报出明确标注"钩子自身出错"的错误结果给模型，不静默
  放行、也不能让异常直接向上传播打断整轮运行。
- 两个队列（steering/follow-up）都设置成 `"all"` 模式，且排队的消息数量很大——批量注入不应该让单
  次模型请求的消息列表无限增长而不受已有的 token 预算/压缩机制约束。
- `finishTurn`/`prepare_request`/`prepare_next_turn` 三个钩子都提供了，且在同一轮里都试图替换
  `context`/`model`——需要有明确、可预测的优先级/生效顺序，不能是"谁后调用谁生效"这种不确定行为。
- 一条自定义角色的消息被错误地传给了 `transform_context`/`convert_to_llm` 之外的、不知道怎么处理
  它的既有代码路径（比如 trace 记录、历史压缩）——这些路径不能因为遇到不认识的消息角色就报错崩
  溃，至少要能优雅地把它当成不透明数据处理或跳过。
- `thinking_level` 设置成了当前模型/供应商根本不支持的档位（比如对一个不支持推理强度的模型设
  `"max"`）——不能让请求本身失败，需要有清晰的降级/忽略策略。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须提供一个事件订阅机制，监听器按注册顺序被依次等待执行完，而不是现在的几个专
  用回调（`on_start`/`on_finish`/`on_error`/`on_text_delta`/`on_reasoning_delta`/
  `on_tool_result`/`on_usage`）各管一摊。
- **FR-002**: 事件种类至少要覆盖：运行开始/结束、回合（turn）开始/结束、消息开始/更新/结束（对
  system/user/assistant/tool 结果**每一种**消息都要发，不只是 assistant）、工具执行开始/进度更
  新/结束。
- **FR-003**: "运行结束"事件必须是这次运行发出的最后一个事件；且这次运行在该事件对应的全部监听器
  执行完之前，不能被视为"已经空闲、可以安全发起下一次运行"。
- **FR-004**: `packages/core` 不得因为本次功能新增任何对其他 `packages/*` 目录的直接导入——延续
  `001-core-isolation-selftest` 已经确立的边界（`scripts/check_core_boundary.py` 检查必须继续通
  过）；任何新的协作方需求都必须通过新增/扩展 `typing.Protocol` 或注入回调由调用方提供。
- **FR-005**: Steering 和 follow-up 必须拆成两个独立的排队机制，各自可以单独设置 `"one-at-a-time"`
  或 `"all"` 两种模式。
- **FR-006**: Steering 消息必须且只能在"当前这一步的工具调用全部执行完之后"被轮询并注入下一次请
  求；系统不得提供任何能取消/打断正在进行中的模型调用或工具执行的机制——`001-core-isolation-
  selftest` 里基于 `asyncio.Event`/`ModelInterrupted` 的打断路径本次整体移除。
- **FR-007**: Follow-up 消息只能在"当前没有待处理的工具调用、且 steering 队列里也没有排队消息"时
  才被轮询并注入；两者都有排队消息时，steering 优先于 follow-up。
- **FR-008**: 工具执行模式（并发/顺序）必须可以整体配置，也必须可以针对单个工具单独覆盖；一个批
  次里只要有一个工具要求顺序执行，整批就退化成顺序执行。
- **FR-009**: 系统必须提供执行前（可拦截/拒绝）、执行后（可覆写部分结果字段）两个钩子点，语义对齐
  参考实现的 `beforeToolCall`/`afterToolCall`（局部覆写而非整体替换、未提供的字段保留原值）；这两
  个钩子自身执行时抛出异常必须按 fail-closed 处理——这次工具调用被当作拦截，报出明确标注"钩子自
  身出错"的错误结果，异常不得向上传播打断整轮运行、也不得被当成"放行"处理。
- **FR-010**: 一个工具调用批次只有在**每一个**被终结的调用都标记"建议提前结束"时，运行才会提前结
  束；只要批次里有一个没有标记，运行按正常流程继续到下一轮。
- **FR-011**: 系统必须提供一个"一轮结束后判定继续/结束/维持原调度"的钩子（`finishTurn` 等价物）；
  `packages/agents/react_agent.py` 现有的"模型调用内置 `finish` 工具来结束运行"机制必须被这个钩
  子取代，不再保留内置 `finish` 工具这条终止路径。
- **FR-012**: 工具执行过程中抛出的异常必须被捕获并报告为该次工具调用的错误结果（`isError` 标记），
  不能原样向上传播打断整轮运行，也不能被静默吞掉变成一条看不出是失败的正常结果。
- **FR-013**: 系统必须支持把"应用专属、模型看不到"的消息类型和标准 LLM 消息（system/user/
  assistant/tool）放进同一份历史列表；必须提供一个在每次模型请求前执行的转换步骤，把历史列表转成
  只包含标准 LLM 消息的、真正发给模型的请求体，过滤掉应用专属消息。
- **FR-014**: 系统必须提供一个可选的、在"转换成 LLM 消息格式"之前执行的历史预处理步骤（用于裁
  剪/注入外部上下文），默认情况下（未提供时）历史原样传递给转换步骤。
- **FR-015**: 系统必须提供一个在每一次模型请求发起之前（包括第一次）都会被调用的钩子，允许替换这
  次及之后请求要用的上下文/模型/推理等级。
- **FR-016**: 系统必须提供一个在一轮结束、确认要继续时、下一轮正式开始之前被调用的钩子，允许替换
  下一轮要用的上下文/模型/推理等级，或者追加需要先插入历史的消息。
- **FR-017**: 系统必须支持至少 `off`/`minimal`/`low`/`medium`/`high`/`xhigh`/`max` 七档可配置的推
  理等级，每档可以关联一个自定义 token 预算；该等级必须是运行期可读写的状态，而不是只能在构造时固
  定一次。
- **FR-018**: 推理等级为 `off`（或未配置任何自定义预算）时，实际发给模型的请求不得携带推理强
  度/预算相关字段，行为必须和当前"完全不设置 `MODEL_REASONING_EFFORT`"的默认状态等价。
- **FR-019**: 本次范围内的全部能力（FR-001 到 FR-018 覆盖的事件总线、steering/follow-up 轮询、工
  具执行模式与钩子、`finishTurn`、消息分层、`prepareRequest`/`prepareNextTurn`、
  `thinking_level`/`thinking_budgets`）都必须被 `packages/agents/react_agent.py` 实际接入消费，并
  相应更新 `apps/api/runtime.py`/`packages/agents/builder.py` 里依赖旧接口的部分，使其能够正常构
  造/驱动新接口——不接受"`packages/core` 内部实现完整、但现有唯一消费方完全没有用上"的交付状态。

### Key Entities

- **事件（Event）**：这次运行里发生的一件具体事情的不可变快照——运行/回合/消息/工具执行各自的生
  命周期阶段，加上该阶段必需的上下文（消息内容、工具调用 id/名称/参数/结果/是否出错/耗时等）。
- **排队消息（Queued Message）**：steering 或 follow-up 队列里等待被轮询注入的一条消息，带有队列
  各自的排队模式（一次只取最早一条 / 一次性全部取出）。
- **工具调用前置结果（Before-Call Result）**：执行前钩子的返回值——是否拦截、拦截时给模型看的错误
  文案、是否建议提前结束本批次。
- **工具调用后置结果（After-Call Result）**：执行后钩子的返回值——对已执行结果的局部字段覆写（内
  容/详情/结构化内容/是否出错/是否建议提前结束），未提供的字段保留原值。
- **回合终止决定（Turn Decision）**：`finishTurn` 钩子的返回值——继续/结束/维持原调度三选一。
- **应用专属消息（App-Specific Message）**：不属于标准 LLM 角色（system/user/assistant/tool）、只
  存在于 agent 自己历史里、会被转换步骤过滤掉的消息。
- **推理等级与预算（Thinking Level / Budget）**：七档可选的推理强度，每档关联一个可自定义的 token
  预算，运行期可读写。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 维护者能只凭事件订阅就区分出"是哪一条消息""是哪一次工具调用"正在发生什么阶段，不需
  要再去读多个专用回调各自的触发条件才能拼出完整的运行时序。
- **SC-002**: 工具调用正在执行期间排队一条 steering 消息，这次工具调用不会被取消或产生"执行到一半
  被打断"的痕迹——它会正常跑完，steering 消息在它跑完之后才生效；整套系统里不存在任何路径能中途取
  消一次正在进行的模型调用。
- **SC-003**: 把其中一个工具标记为必须顺序执行后，同一批次里其余未标记的工具调用仍然保持并发执
  行，不会被牵连拖慢。
- **SC-004**: 本次功能上线后，`scripts/check_core_boundary.py` 对 `packages/core` 的检查结果仍然
  是零违规。
- **SC-005**: 一次完整的 ReAct 对话（经过若干次工具调用后给出最终回复）在终止机制从"`finish` 工
  具"换成"`finishTurn` 钩子"之后，仍然能在语义等价的时间点正确结束，不会出现"该停的时候没停"或
  "没结束却提前停了"。
- **SC-006**: 往历史里插入一条应用专属消息后，维护者能在 agent 自己的历史快照里看到它，但在实际发
  给模型的请求体里完全看不到它。
- **SC-007**: 运行期把推理等级从一档改成另一档（或改成 `off`），下一次模型请求立刻按新等级生效，
  不需要重新构造整个 agent。
- **SC-008**: 一次完整的真机 `ReActAgent` 对话运行结束后，能够证实本次范围内的每一项新能力都被
  `ReActAgent` 实际触发过至少一次（而不是只能在 `packages/core` 的单元测试里观察到），即事件总
  线产生了真实事件、steering/follow-up 轮询被真实调用过、工具执行钩子被真实调用过、`finishTurn`
  判定了真实的运行终止、消息分层/`prepareRequest`/`prepareNextTurn`/`thinking_level` 均在真实请求
  路径上生效。

## Assumptions

- "完全按照 pi 的内核实现"理解为：对齐其**架构设计**（事件模型、steering/follow-up 语义、工具执
  行模式与钩子、终止判定方式、消息模型分层、请求前置钩子、分级推理）而不是逐行照搬 TypeScript 代
  码或标识符命名——Python 一侧会用 `typing.Protocol`/`dataclass`/`asyncio` 等惯用写法表达同样的语
  义，变量/类型命名遵循本仓库既有风格，不强行复刻 `camelCase`/TS 专属命名。TypeScript 的"声明合
  并"（为 `AgentMessage` 新增自定义角色）在 Python 侧用鸭子类型/最小形状协议等价表达，不引入 TS 独
  有的类型系统机制。
- 参考实现里的"低层生成器 API（`agentLoop`/`agentLoopContinue`）+ 高层状态化 `Agent` 类"两层划
  分，本仓库已经有对应物（`agent_loop.py` 的纯函数 + `core.agent.Agent` 基类），这次对齐默认延续
  现有的两层划分，不要求另外新增一套平行的无状态生成器入口。
- 本次范围明确包含两处对**已上线、已有测试覆盖**行为的替换，且已经过用户确认，不是误判的回归：
  (a) steering 从"可以打断在飞的模型调用"变成"只能在工具调用跑完后轮询注入"，
  `test_steering_interrupts_an_in_flight_model_call_and_retries` 这条测试会被删除或重写；
  (b) `ReActAgent` 的终止判定从"模型调用内置 `finish` 工具"换成"`finishTurn` 钩子"，
  `FINISH_TOOL_NAME`/`FINISH_TOOL_SCHEMA`/`_read_final_answer` 这套机制会被移除。
- `packages/core/model.py` 现有的 `reasoning_effort: str | None`（`low|high|max` 三档，来自
  `MODEL_REASONING_EFFORT` 环境变量或构造/调用参数）是 Story 7 的现状基础，不是从零实现；Story 7
  要做的是在这个基础上扩展成七档可选、每档可自定义 token 预算、且运行期可读写的状态。
