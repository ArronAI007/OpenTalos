# Phase 0 Research: packages/core 对齐 pi 的 agent-core 内核架构

本次调研基于对真实代码的阅读（`packages/core/{agent.py,agent_loop.py,protocols.py,protocol.py,
model.py,errors.py}`、`packages/agents/{react_agent.py,builder.py}`、`apps/api/runtime.py`、
`packages/tool/{registry.py,tool.py}`、`packages/memory/working.py`），不是对 spec.md 的转述。

## 决策 1：事件总线怎么实现，怎么和现有的 `PhaseCallback`/专用回调共存或取代

**决策**：不新引入独立的事件框架，把 `packages/core/agent.py` 现有的 `PhaseSignal`/`AgentPhase`
模式**泛化**成 `AgentEvent`/`EventKind`——`AgentEvent` 保留 `PhaseSignal` 的形状
（`kind`/`timestamp`/`agent_name`/`data: dict[str, Any]` + `emit()` classmethod + `to_dict()`），
只是把 `AgentPhase` 的 3 个成员（STARTED/FINISHED/FAILED）换成 FR-002 要求的 10 个成员：
`RUN_START`/`RUN_END`、`TURN_START`/`TURN_END`、`MESSAGE_START`/`MESSAGE_UPDATE`/`MESSAGE_END`、
`TOOL_EXECUTION_START`/`TOOL_EXECUTION_UPDATE`/`TOOL_EXECUTION_END`。`RUN_END` 的 `data` 带一个
`status: "completed"|"failed"|"cancelled"` 字段（外加失败时的 `error`/`error_type`），一次性覆盖掉
原来 `FAILED` 单独作为一个 phase 的信息量——不需要专门的第 11 个 kind。

`Agent` 新增 `subscribe(listener: Callable[[AgentEvent], Awaitable[None]]) -> Callable[[], None]`
（返回一个取消订阅的回调）和内部 `_emit(event: AgentEvent) -> None`（按注册顺序 `await` 每个监听
器；单个监听器异常不应该打断其余监听器或主流程——复用 `_notify()` 已经在用的"吞掉异常，不让回调故
障打断 Agent"策略，但不再有 `timeout` 这件事上的歧义：事件分发不设超时，因为 FR-003 要求"运行结束
不能早于全部监听器跑完"，加超时会和这条要求冲突）。

`arespond_with_callbacks` 的 `on_start`/`on_finish`/`on_error` 三个参数：**保留方法签名**（向后兼
容任何直接调这个方法但还没升级到订阅事件总线的调用方），但内部实现换成"构造一次性的订阅者，转发
到事件总线，运行结束后自动取消订阅"——即旧回调风格的调用方其实已经在用新总线，只是摸不到总线的全
部细节（比如摸不到 per-message/per-tool 的中间事件）。`agent_loop.py` 里的
`on_text_delta`/`on_reasoning_delta`/`on_tool_result`/`on_usage` 四个专门回调全部保留参数签名不变
（`execute_model_step`/`run_tool_turn` 本身不知道"Agent"概念、不能直接持有订阅列表），但新增一个
`emit: Callable[[AgentEvent], Awaitable[None]] | None = None` 参数——`ReActAgent.arespond()` 把
`self._emit` 绑定过去，在正确的时间点调用 `emit(...)` 产生 `MESSAGE_*`/`TOOL_EXECUTION_*` 事件；
`on_text_delta` 等四个回调则保持不变继续被直接调用（它们是流式增量的低层转发，不适合包进离散事件
里，这点和 pi 的 `message_update` 事件实际上也携带一份 "assistantMessageEvent" 增量是一致的做法
——"message_update" 事件的 `data` 字段里会带上这次增量，两套机制描述的是同一份数据，不是重复实
现）。

对应 FR-001/FR-002/FR-003；`ReActAgent`/`apps/api/runtime.py` 的实际接入见 Decision 8。

**备选方案**：引入一个独立的 `EventBus` 类（不基于 `PhaseSignal`）。被否决——会和已有的
`PhaseSignal` 并存造成两套相似但不同的通知机制，违反宪法原则 IV。

## 决策 2：Steering 轮询的调用位置要不要搬家

**决策**：**不搬家**。核实 `agent_loop.execute_model_step()` 现有代码发现，`steer.drain()` 已经是
在"这次模型调用之前"被调用（235-276 行），而 `execute_model_step` 本身是在外层循环
（`run_tool_turn`/`ReActAgent.arespond()`）里按"一步=一轮"被重复调用的——也就是说，第 N 步调用时
机 drain 的消息，天然就是"第 N-1 步的工具调用全部跑完之后"排进去的消息；第 1 步调用时机则对应"整
个运行刚开始、还没有任何工具调用"，这正好匹配 pi 的 `getSteeringMessages` 在 loop 开始时也轮询一
次的语义。所以这次真正要改的只有两件事：
1. 删除 `clear_interrupt()`/把 `interrupt` 换成 `steer.interrupt_event` 这两行，以及 `_call_model`
   里整段"和 `interrupt.wait()` 赛跑、谁先到谁赢"的逻辑和 `ModelInterrupted` 异常类——这是唯一真
   正要删的东西（FR-006）。
2. `SteerQueue` Protocol 从"排队+打断"收窄成纯"排队"：只留 `drain() -> list[str]`（或重命名为
   `poll()`，两个名字语义等价，`/speckit-tasks` 阶段统一命名风格时再定），去掉
   `clear_interrupt()`/`interrupt_event` 两个成员。

**Follow-up 队列的轮询点是新增的**：在 `execute_model_step`/外层循环判定"这一步没有
`requested_tools`、本来要停了"的那个分支里，停之前先 poll 一次 follow-up 队列；非空则把消息注入并
继续下一步，而不是直接返回（FR-007）。Steering 和 follow-up 都有消息时，steering 优先——这天然成
立，因为 steering 在每一步开头就已经被 poll 并注入过了，follow-up 只在"确定要停"的那一刻才会被问
到。

对应 FR-005/FR-006/FR-007；`_ReActSteerQueue` 适配器（`react_agent.py`）需要相应瘦身并新增一个
follow-up 版本，`apps/api/runtime.py` 的 `_LiveRun.steer_event` 字段连同"`steer()` 方法里
`run.steer_event.set()` 这行"一起删除，`_LiveRun` 新增 `followup: asyncio.Queue[str]`。

**备选方案**：把 drain 调用点从 `execute_model_step` 内部挪到外层循环顶部，让轮询时机"看起来"更
显式地匹配 pi 的文字描述。被否决——两种写法在行为上完全等价（`execute_model_step` 本来就是每步调
一次），挪动只会增加一次无意义的函数签名改动和回归测试面，不改变任何可观察行为，不符合"精准局部修
改"的要求。

## 決策 3：工具执行模式（并发/顺序）怎么落地

**决策**：`execute_model_step` 现在用 `asyncio.gather(*(run_one(invocation) for invocation in
completion.requested_tools))` 无条件并发执行一批工具调用（337 行）。新增一个全局默认
`tool_execution_mode: Literal["sequential", "parallel"] = "parallel"` 参数（在 `Agent`/
`ReActAgent` 构造时可配置，一路透传到 `execute_model_step`）。每次拿到 `completion.requested_tools`
后，用注入的 `ToolExecutor.get(name)`（已经在 `resolve_tool_call` 里被调用一次，这里额外查一次拿
`ToolInfo.execution_mode`）检查这一批里有没有任何一个工具的 `execution_mode == "sequential"`；只要
有一个，整批退化成 `for invocation in ...: await run_one(invocation)` 顺序执行；否则保持现状的
`asyncio.gather`。`ToolInfo`（`packages/core/protocols.py`）新增
`execution_mode: Literal["sequential", "parallel"] | None = None` 字段（`None` 表示该工具不覆盖全
局默认）；`packages/tool/tool.py` 的 `Tool.__init__` 新增同名构造参数，这是 `packages/tool` 自己的
改动，不影响 `packages/core` 的依赖边界（`packages/core` 仍然只认 `ToolInfo` 这个 Protocol 形状）。

对应 FR-008；`ReActAgent` 默认沿用 `"parallel"`（和现状行为完全一致，满足 User Story 3 "不改变任
何已有测试断言的默认行为"的要求），只是现在这个值变成可配置的了。

## 决策 4：`beforeToolCall`/`afterToolCall` 钩子怎么接入，异常怎么 fail-closed

**决策**：新增两个可选参数 `before_tool_call`/`after_tool_call`，签名：

```python
BeforeCallResult = dataclass(block: bool = False, reason: str | None = None, terminate: bool = False)
AfterCallResult = dataclass(
    content: str | None = None,
    details: Any = None,
    is_error: bool | None = None,
    terminate: bool = False,
)
before_tool_call: Callable[[ToolInvocation], Awaitable[BeforeCallResult]] | None
after_tool_call: Callable[[ToolInvocation, ToolCallResult], Awaitable[AfterCallResult]] | None
```

两者都挂在 `resolve_tool_call()`（`agent_loop.py`）里，包一层 `try/except`：钩子正常返回就按返回值
处理（`before_tool_call` 的 `block=True` 等价于现在"审批被拒绝"那条路径，复用
`_DENIED_MESSAGE`-类似的"明确标注原因"的错误结果；`after_tool_call` 的非 `None` 字段按字段覆写已
执行结果，`None` 字段保留原值）；钩子抛异常则**不重新抛出**，直接当作
`BeforeCallResult(block=True, reason=f"hook error: {exc}")`
处理——这是 Clarifications 会话确认的 fail-closed 默认值，和"审批通道异常/未配置就拒绝"的既有风格
（`resolve_tool_call` 里 `approve is not None and await approve(invocation)`，`None` 时已经是拒绝）
保持一致，不是新引入的保守哲学。

`terminate` 聚合（FR-010）：`execute_model_step` 收集这一批每个调用最终是否标记了
`terminate=True`（来自 before 拦截时的值，或 after 覆写后的值），只有当批次非空且**全部**调用都标
记了 `terminate` 时，才在这一步结束后触发"提前结束运行"；这个检查发生在 `finishTurn` 钩子被调用之
前——工具级别的 terminate 是更强的信号，一旦触发就不再征询 `finishTurn` 的意见（避免两个终止信号
的优先级含糊不清）。

对应 FR-009/FR-010/FR-012。

## 决策 5：`finishTurn` 怎么替换 `finish` 工具

**决策**：新增 `finish_turn: Callable[[TurnContext], Awaitable[TurnDecision | None]] | None`，
`TurnContext` 携带这一轮的 `completion`（含 `text`/`requested_tools`）、这一步的编号、工具结果列
表；`TurnDecision` 是 `Literal["continue", "end"]`（省掉 pi 里 `undefined` 这个"第三态"——Python 直
接用 `None` 表示"不表态"，不需要额外包一层）。调用时机：外层循环（`run_tool_turn`/
`ReActAgent.arespond()`）里，`execute_model_step` 返回之后、决定"继续下一步还是停"之前。

`ReActAgent` 的终止判定直接删除 `FINISH_TOOL_NAME`/`FINISH_TOOL_SCHEMA`/`_read_final_answer`/
`finish_calls` 拦截这一整套；默认情况下（`ReActAgent` 不传 `finish_turn` 或 `finish_turn` 返回
`None`）退回到现有的"有工具调用就继续、没有就停"的调度（这正是现在 `if not
completion.requested_tools: answer = completion.text; break` 已经在做的事——取消 `finish` 工具之
后，模型自己在没有更多工具要调时直接回复纯文本，就等价于现在 `finish_calls` 分支做的事）。
`finish_turn` 返回 `"end"` 时无条件停止，哪怕这一步还有 `requested_tools` 也不再继续（断言 4）；返
回 `"continue"` 时哪怕这一步没有工具调用、没有排队消息，也要再发起恰好一次模型请求而不是直接停
（断言 2）——这意味着外层循环的"继续"判断要从"隐式地看 `requested_tools`/队列是否非空"改写成"显
式地看一个 `should_continue: bool` 变量"，由"是否有 `requested_tools`"、"`finish_turn` 的返回
值"、"follow-up 轮询结果"共同决定，`finish_turn` 的显式返回值优先级最高。

`DEFAULT_SYSTEM_PROMPT`（`react_agent.py`）里"调用内置 `finish` 工具"的措辞需要同步删除；
`builder.py` 的 `_append_suffix()` 注释提到的"保住 ReAct 的 finish 工具约定这条默认提示词"这句话也
过期了，一并修正。

对应 FR-011；`error`/`aborted` 响应的硬性退出不需要额外代码——`OutputLimitError`/
`EmptyModelResponse` 已经在 `execute_model_step` 内部直接 `raise`，根本不会走到"决定是否继续"这一
步，`finish_turn` 天然没有机会覆盖它们。

## 决策 6：消息分层——`AgentMessage` vs LLM `Message`

**决策**：核实 `packages/core/protocol.py` 发现 `ChatMessage.role: SpeakerRole` 当前是一个封闭的
`Literal["user", "assistant", "system", "tool", "summary"]`（Pydantic 字段），任何不在这个集合里的
角色字符串会在构造时直接被拒绝。要让"应用专属消息"能塞进同一个历史列表，`SpeakerRole` 需要从
`Literal` 放宽成 `str`（Python 没有 TS 的声明合并，这是最小的、符合 spec Assumptions 所述"鸭子类
型/最小形状协议"精神的改法；`ChatMessage` 本身已经满足"至少有 `role`/`timestamp`"这个最小形状）。

`packages/memory/working.py` 的 `build_messages()` 已经是事实上的 `convert_to_llm`
实现——核实发现它已经对 `tool`/`summary` 两种特殊角色做了专门转换，其余角色走
`else: messages.append({"role": message.role, "content": message.content})` 直接透传。这个
`else` 分支就是真正要改的地方：新增一个显式的"已知 LLM 角色"集合
`_LLM_ROLES = frozenset({"user", "assistant", "system"})`（`tool`/`summary` 已经被前两个分支处理
过，不会落到这个 `else`），只有角色在这个集合里才透传，否则直接跳过（不追加到 `messages`）——这就
是 FR-013 要求的"过滤掉应用专属消息"。

`transform_context`（FR-014）新增为 `Agent`/`ReActAgent` 的一个可选构造参数
`transform_context: Callable[[list[ChatMessage]], Awaitable[list[ChatMessage]]] | None`，在
`arespond()` 里拿到 `history_snapshot()` 之后、调用 `build_messages()` 之前执行；异常处理复用决策
4 的 fail-closed 风格——这里更合适的降级是"吞掉异常、使用原始未转换的历史继续"（因为这是一个纯读
取型的预处理步骤，不像工具调用那样有副作用风险，强行 fail-closed 在这里等价于让一次 transient 的
转换器 bug 直接搞垮整个对话，不成比例），记一条 trace 事件但不中断运行。

对应 FR-013/FR-014；`ReActAgent` 默认不传 `transform_context`（现状行为不变，满足 Acceptance
Scenario 4 "即便现状下暂时还没有真正的应用专属消息类型要插入，也要实际用上这套分层机制"——"用上"
指的是"构造参数存在、`build_messages()` 的过滤逻辑永远在生效"，不是指必须真的构造一条应用专属消
息）。

## 决策 7：`prepare_request`/`prepare_next_turn` 怎么接入，和 `finish_turn` 的优先级怎么定

**决策**：两个新增可选参数：
`prepare_request: Callable[[RequestContext], Awaitable[RequestOverrides | None]] | None` 在
`execute_model_step` 发起 `_call_model` 之前调用（每一步都调，包括第一步）；
`prepare_next_turn: Callable[[], Awaitable[RequestOverrides | None]] | None` 在外层循环"确定要继续
下一步"之后、下一次 `execute_model_step` 调用之前调用一次。`RequestOverrides` 是一个字段全部可选
的 dataclass（`context`/`model`/`thinking_level`），未提供的字段保留原值，和决策 4 的
`AfterCallResult` 同一种"局部覆写"模式。

优先级（解决 Edge Case 里"三个钩子都想替换 context/model 时顺序不确定"的问题）：**按调用时机的先
后顺序，后调用的覆写先调用的**——`finish_turn` 先于 `prepare_next_turn`（在同一个"回合结束"的时间
点上，前者决定要不要有下一轮，后者准备下一轮的内容），`prepare_next_turn` 先于下一轮的
`prepare_request`（`prepare_next_turn` 准备的是"下一轮默认用什么"，`prepare_request` 是这一轮每次
具体请求前的最后一道关卡）。这不是一个任意选择——它是这三个钩子在时间线上天然的调用顺序决定的，不
需要额外的优先级配置项（符合宪法原则 IV：不为假设中的灵活性预留配置）。

对应 FR-015/FR-016。

## 决策 8：`thinking_level`/`thinking_budgets` 怎么和现有的 `reasoning_effort` 共存/替换

**决策**：核实 `packages/core/model.py` 发现 `reasoning_effort` 当前只在
`OpenAICompatibleBackend`/`FakeModelBackend` 路径生效（作为 `_build_call_kwargs` 里的一个透传
`kwargs` 字段，最终进了 OpenAI 兼容 API 的请求体），`ClaudeBackend` 完全没有使用它——Anthropic 的原
生"扩展思考"用的是完全不同的 `thinking: {type: "enabled", budget_tokens: N}` 参数，现状代码里这条
路径是空的。

`ModelClient` 新增 `thinking_level: ThinkingLevel = "off"` 作为**运行期可读写的实例属性**（不是构
造后不可变的值），`ThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh",
"max"]`；`thinking_budgets: dict[ThinkingLevel, int] | None` 作为构造参数，未提供时用一组仓库内置
默认值（例如 minimal=1024/low=2048/medium=4096/high=8192/xhigh=16384/max=32768，具体数值留给
`/speckit-tasks` 定，这里只定性质）。

按后端分别转译（`_build_call_kwargs` 新增这一步，替换原来直接透传 `reasoning_effort` 的逻辑）：
- **OpenAI 兼容后端**：`off` → 不发送任何推理强度字段（和现状"未配置 `MODEL_REASONING_EFFORT`"完
  全等价，满足 FR-018）；其余六档降维映射到现有后端只认的三个字面量
  （`low|high|max`）——`minimal`/`low` → `"low"`，`medium`/`high` → `"high"`，`xhigh`/`max` →
  `"max"`——保证绝不会给供应商发送一个它不认识、可能导致 400 的新字符串（呼应 Edge Case"不支持的
  档位不能让请求失败"）。
- **Anthropic 后端**：`off` → 不启用 `thinking` 参数；其余六档 → `thinking: {type: "enabled",
  budget_tokens: thinking_budgets[level]}`——这是现状代码完全没有走通的新路径，`thinking_budgets`
  表在这里是真正按字面意义使用的"每档对应多少 token 预算"。

`ReActAgent` 构造 `ModelClient` 时不再传 `reasoning_effort`（该参数在 `ModelClient.__init__` 里保
留但标记为向后兼容的旧入口，内部统一折算成 `thinking_level` 的等价档位——不删除这个构造参数本身，
因为删除会是一次破坏性的公共签名变更，而 FR-017/018 只要求"新机制运行期可读写"，没有要求"旧参数
必须消失"），改为在构造时/运行期设置 `thinking_level`（哪一档作为 `ReActAgent` 的默认值留给
`/speckit-tasks`，建议 `"off"`，和现状"未配置环境变量"的默认行为一致）。

对应 FR-017/FR-018；`SC-007`（运行期切换立即生效）通过"`thinking_level` 是实例属性、
`_build_call_kwargs` 每次调用都现读这个属性"自然满足，不需要额外的"生效"机制。

## 决策 9：`ReActAgent`/`apps/api/runtime.py` 怎么接入事件总线（FR-019 的具体落地）

**决策**：`ReActAgent` 继承自 `Agent`，`subscribe()`/`_emit()` 直接继承拿到，不需要重复实现。
`apps/api/runtime.py` 的 `_run_turn()` 现在用一组 kwargs
（`on_text_delta=`/`on_reasoning_delta=`/`drain_steer=`/`steer_event=`/`on_steer_interrupt=`/
`on_usage=`）驱动 `agent.arespond_with_callbacks(...)`；这次改造后，`_run_turn()` 改为先
`unsubscribe = agent.subscribe(handle_event)` 再调用 `agent.arespond(...)`（注意：不再是
`arespond_with_callbacks`，因为 run_start/run_end 现在也走同一个事件总线，`arespond_with_callbacks`
这层包装对新架构而言是多余的一层，`_run_turn` 直接订阅 + 调 `arespond` 更直接），`handle_event`
内部按 `event.kind` 分发：`MESSAGE_UPDATE`（assistant）→ 换算成现有的 `{"type": "delta", "text":
...}` SSE 事件；`TOOL_EXECUTION_END` → 换算成现有的工具结果事件；`RUN_END` 的 `status=="failed"`
→ 换算成现有的 error 事件。`steer_event`/`on_steer_interrupt` 两个 kwargs 随打断机制一起删除；
`_LiveRun` 的 `steer: asyncio.Queue[str]` 拆成 `steering: asyncio.Queue[str]` +
`followup: asyncio.Queue[str]` 两个队列，`steer()` 方法（供前端"运行中插入消息"调用）新增一个参数
或拆成两个方法区分写入哪个队列——现状前端只有一种"插入消息"交互，默认全部写入 `steering` 队列（和
现状语义最接近：用户主动发消息打断，就是要尽快被看到，steering 比 follow-up 更快生效），
`followup` 队列在本次范围内可以没有真实前端触发入口（FR-019 要求的是"钩子点在调用路径上可用"，不
要求"现状必须有一个具体场景真的用到 follow-up"）。

对应 FR-019/SC-008；这是风险最高、改动面最大的一项集成工作，`/speckit-tasks` 阶段需要把它拆成足
够小的任务粒度（建议：先让 `ReActAgent` 侧事件总线跑通并有单元测试，再单独做 `apps/api/runtime.py`
的事件转换层，最后做真机验证），避免一个任务里同时改两层导致出问题时无法定位是哪一层的锅。

## 决策 10：`run_tool_turn` 需不需要专门改动

**决策**：不需要。`run_tool_turn` 内部直接调用 `execute_model_step`（循环），本次新增的全部参数
（`emit`/`before_tool_call`/`after_tool_call`/`finish_turn`/`prepare_request`/
`prepare_next_turn`）在 `execute_model_step`/`run_tool_turn` 两层都设计成可选、默认 `None`——
`run_tool_turn` 的现有调用方（`tests/core/test_real_model_selftest.py`、`tests/core/
test_agent_loop.py` 自身）不需要改任何一行就能继续通过；它也自动"获得"这些新能力（如果未来有调用
方想用），不需要为它重复设计一遍钩子穿透逻辑。

对应宪法原则 IV（YAGNI）——这是一个明确的"不做什么"决策，记录下来避免后续任务误以为这是遗漏。
