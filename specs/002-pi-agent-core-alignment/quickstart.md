# Quickstart: 验证"packages/core 对齐 pi 的 agent-core 内核架构"

## 前置条件

```bash
cd /Users/arron/Desktop/ArronAI/OpenTalos
.venv/bin/pytest --version   # 确认用的是项目虚拟环境，不是系统/anaconda 的 python
```

真机场景（场景 8）额外需要 `.env` 里配置好 `MODEL_PROVIDER`/`MODEL_API_KEY`/`MODEL_NAME`；未配置时
对应测试会 `SKIPPED`，不影响其余场景。

## 场景 1：事件总线——纯文本问答的事件序列（User Story 1，Acceptance Scenario 1）

```bash
.venv/bin/pytest tests/core/test_agent_loop.py -k event_bus -v
```

预期：订阅一次不涉及工具调用的运行，收到的事件序列恰好是 `RUN_START → TURN_START →
MESSAGE_START(user) → MESSAGE_END(user) → MESSAGE_START(assistant) → MESSAGE_UPDATE(assistant)* →
MESSAGE_END(assistant) → TURN_END → RUN_END`。

## 场景 2：事件总线——工具执行事件 + 多监听器顺序（User Story 1，Acceptance Scenario 2/3/4）

```bash
.venv/bin/pytest tests/core/test_agent_loop.py -k "tool_execution_event or listener_order or run_end_is_last" -v
```

预期：`TOOL_EXECUTION_START`/`TOOL_EXECUTION_END` 成对出现并携带可区分的 `call_id`；两个监听器按
注册顺序依次被 `await`；`RUN_END` 是最后一个事件且其监听器跑完前运行不算空闲。

## 场景 3：Steering 轮询——不打断正在执行的工具调用（User Story 2，Acceptance Scenario 1）

```bash
.venv/bin/pytest tests/core/test_agent_loop.py -k steering_does_not_interrupt -v
```

预期：工具调用正在执行期间排队一条 steering 消息，这次工具调用正常跑完（无
`ModelInterrupted`/`CancelledError`），消息在下一次模型请求前被注入。

## 场景 4：Follow-up 轮询（User Story 2，Acceptance Scenario 2/3/4）

```bash
.venv/bin/pytest tests/core/test_agent_loop.py -k follow_up -v
```

预期：没有更多工具调用时排队一条 follow-up 消息，运行多跑一轮；steering 和 follow-up 同时有消息
时 steering 优先；`QueueMode` 为 `ONE_AT_A_TIME`/`ALL` 时单次轮询吐出的消息数量符合预期。

## 场景 5：工具执行模式 + before/afterToolCall 钩子（User Story 3）

```bash
.venv/bin/pytest tests/core/test_agent_loop.py -k "execution_mode or before_tool_call or after_tool_call or batch_terminate" -v
```

预期：一个工具标记 `execution_mode="sequential"` 时整批顺序执行、其余未标记的调用默认仍并发；
`before_tool_call` 拦截/`after_tool_call` 覆写按预期生效；两者自身抛异常时按 fail-closed 处理；
批次 `terminate` 聚合规则（全部标记才提前结束）成立。

## 场景 6：`finishTurn` 替代 `finish` 工具（User Story 4）

```bash
.venv/bin/pytest tests/agents/test_react_agent.py -k finish_turn -v
```

预期：`finish_turn` 返回 `"end"`/`"continue"`/`None` 三种情况下的调度行为符合契约；一次完整的
ReAct 对话（经过若干次工具调用后给出最终回复）在新终止机制下仍能在语义等价的时间点结束。

## 场景 7：消息分层 + 请求级钩子 + 分级推理（User Story 5/6/7）

```bash
.venv/bin/pytest tests/core/test_agent_loop.py -k "transform_context or convert_to_llm or prepare_request or prepare_next_turn or thinking_level" -v
```

预期：应用专属角色的消息进历史但不进模型请求；`transform_context` 生效且异常时能降级；
`prepare_request`/`prepare_next_turn` 按时机正确生效且优先级符合"后调用覆写先调用"；
`thinking_level` 运行期切换立即对下一次请求生效，`"off"` 时不携带任何推理强度字段。

## 场景 8：真机验证——七项能力都被 `ReActAgent` 实际触发（SC-008）

```bash
.venv/bin/pytest tests/core/test_real_model_selftest.py -k pi_alignment -v
```

预期：无 `MODEL_API_KEY` 时 `SKIPPED`；配置凭据时真实跑一轮会触发工具调用的对话，断言事件总线产生
了真实事件、steering/follow-up 轮询点被真实调用过（哪怕队列为空）、`finish_turn` 判定了真实的终
止、消息分层/`prepare_request`/`thinking_level` 均在真实请求路径上生效。

## 场景 9：既有测试套件保持通过（回归，不是新场景）

```bash
.venv/bin/pytest -q
```

预期：除了 Assumptions 里明确列出的两处"经确认的行为替换"相关测试（`test_steering_interrupts_an_
in_flight_model_call_and_retries` 已删除/重写；若干依赖 `finish` 工具终止的测试已改写为依赖
`finish_turn`）之外，其余全量测试保持通过。

## 场景 10：`packages/core` 零依赖边界仍然成立（SC-004）

```bash
.venv/bin/python scripts/check_core_boundary.py
```

预期：退出码 0，零违规——本次新增的全部能力都没有让 `packages/core` 新增对任何其他 `packages/*`
目录的直接导入。

## 场景 11：`apps/api/runtime.py` 侧向确认——事件总线驱动 SSE 流不回归

```bash
.venv/bin/pytest tests/apps/api/test_api_routes.py -k stream -v
```

预期：现有的流式聊天接口（增量文本、工具结果、用量上报等 SSE 事件类型）在 `_run_turn` 改为订阅事
件总线之后，前端可观察到的事件内容/顺序保持等价（允许事件名称/格式按 `research.md` 决策 9 的映射
表转换，但不丢失任何现有信息）。
