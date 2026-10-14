# Quickstart: 验证"packages/core 对齐 pi 的 agent-core 内核架构"

> 本文档的每条命令都已经在实现完成后真机跑过一遍确认通过（不是实现前的猜测）；文件/测试名若后续
> 重命名，请同步更新这里。

## 前置条件

```bash
cd /Users/arron/Desktop/ArronAI/OpenTalos
.venv/bin/pytest --version   # 确认用的是项目虚拟环境，不是系统/anaconda 的 python
```

真机场景（场景 8）额外需要 `.env` 里配置好 `MODEL_PROVIDER`/`MODEL_API_KEY`/`MODEL_NAME`；未配置时
对应测试会 `SKIPPED`，不影响其余场景。

## 场景 1：事件总线——完整的事件序列（User Story 1，Acceptance Scenario 1/2）

```bash
.venv/bin/pytest tests/agents/test_react_agent.py::test_react_agent_subscribers_see_plain_event_sequence_for_a_no_tool_call_run tests/agents/test_react_agent.py::test_react_agent_subscribers_see_full_event_sequence_for_a_tool_call_run -v
```

预期：订阅一次不涉及工具调用的运行，收到的事件序列以 `RUN_START` 开头、`RUN_END` 结尾，包含
`MESSAGE_START`/`MESSAGE_END`；触发工具调用的运行里，`TOOL_EXECUTION_START`/`TOOL_EXECUTION_END`
成对出现且携带可区分的 `tool_name`。

## 场景 2：事件总线——多监听器顺序 + emit 参数本身（User Story 1，Acceptance Scenario 3/4）

```bash
.venv/bin/pytest tests/core/test_agent.py -k "subscribe or run_end_listeners" -v
.venv/bin/pytest tests/core/test_agent_loop.py::test_execute_model_step_emits_assistant_message_events_without_tool_calls tests/core/test_agent_loop.py::test_execute_model_step_emits_tool_execution_and_message_events_for_a_tool_call tests/core/test_agent_loop.py::test_run_tool_turn_emits_turn_start_and_turn_end_per_step -v
```

预期：多个监听器按注册顺序依次被 `await`；单个监听器异常不打断其余监听器或主流程；`RUN_END` 对应
的监听器全部跑完之前运行不算空闲；`execute_model_step`/`run_tool_turn` 的 `emit` 参数产生正确的
`MESSAGE_*`/`TOOL_EXECUTION_*`/`TURN_*` 事件序列。

## 场景 3：Steering 轮询——不打断正在执行的工具调用/模型调用（User Story 2，Acceptance Scenario 1）

```bash
.venv/bin/pytest tests/agents/test_react_agent.py::test_steering_does_not_interrupt_an_in_flight_tool_call tests/core/test_agent_loop.py::test_execute_model_step_never_interrupts_a_slow_in_flight_model_call tests/core/test_agent_loop.py::test_minimal_drain_only_object_satisfies_the_steer_queue_protocol -v
```

预期：工具调用/模型调用正在执行期间排队一条 steering 消息，这次调用正常跑完（无任何取消/打断痕
迹），消息在下一次模型请求前被注入；`SteerQueue` Protocol 不再要求 `clear_interrupt`/
`interrupt_event`。

## 场景 4：Follow-up 轮询 + 两队列优先级（User Story 2，Acceptance Scenario 2/3）

```bash
.venv/bin/pytest tests/agents/test_react_agent.py::test_followup_injects_a_message_and_keeps_the_run_going tests/core/test_agent_loop.py::test_execute_model_step_polls_followup_only_when_no_tool_calls_remain tests/core/test_agent_loop.py::test_execute_model_step_does_not_poll_followup_when_tool_calls_are_pending tests/core/test_agent_loop.py::test_execute_model_step_prioritizes_steering_over_followup_when_both_have_messages -v
```

预期：没有更多工具调用时排队一条 follow-up 消息，运行多跑一轮；还有工具调用时不轮询 follow-up；
steering 和 follow-up 同时有消息时 steering 优先。

## 场景 5：工具执行模式 + before/afterToolCall 钩子（User Story 3）

```bash
.venv/bin/pytest tests/core/test_agent_loop.py -k "sequential_tool or batch_stays_concurrent or global_sequential_mode or before_tool_call or after_tool_call or batch_terminate" -v
.venv/bin/pytest tests/agents/test_react_agent.py::test_react_agent_exposes_tool_execution_mode_and_hooks tests/agents/test_react_agent.py::test_react_agent_defaults_to_parallel_execution_without_hooks -v
```

预期：一个工具标记 `execution_mode="sequential"`（或全局 `tool_execution_mode="sequential"`）时整
批顺序执行、否则默认仍并发；`before_tool_call` 拦截/`after_tool_call` 覆写按预期生效；两者自身抛
异常时按 fail-closed 处理；批次 `terminate` 聚合规则（全部标记才提前结束）成立。

## 场景 6：`finishTurn` 替代 `finish` 工具（User Story 4）

```bash
.venv/bin/pytest tests/core/test_agent_loop.py -k finish_turn -v
.venv/bin/pytest tests/agents/test_react_agent.py -k "finish_turn or default_termination" -v
```

预期：`finish_turn` 返回 `"end"`/`"continue"`/`None` 三种情况下的调度行为符合契约（含"错误响应
时完全不被调用"）；一次完整的 ReAct 对话（经过若干次工具调用后给出最终回复）在新终止机制下仍能在
语义等价的时间点结束（SC-005）。

## 场景 7：消息分层 + 请求级钩子 + 分级推理（User Story 5/6/7）

```bash
.venv/bin/pytest tests/core/test_protocol.py::test_chat_message_accepts_an_app_specific_role tests/memory/test_working.py::test_seed_messages_filters_out_app_specific_roles -v
.venv/bin/pytest tests/core/test_agent.py -k transform_context -v
.venv/bin/pytest tests/core/test_agent_loop.py -k "prepare_request or prepare_next_turn" -v
.venv/bin/pytest tests/core/test_model.py -k "thinking_level or claude_backend" -v
```

预期：应用专属角色的消息进历史但不进模型请求；`transform_context` 生效且异常时能降级为原始历史；
`prepare_request` 每次请求都生效且只影响那一次，`prepare_next_turn` 的覆写持续到下一次被覆写为
止；`thinking_level` 运行期切换立即对下一次请求生效，`"off"` 时不携带任何推理强度字段，Anthropic
后端走原生 `thinking`/`budget_tokens`、OpenAI 兼容后端降维映射到三档 `reasoning_effort`。

## 场景 8：真机验证——核心能力在 `ReActAgent` 上真实跑通（SC-008）

```bash
.venv/bin/pytest tests/core/test_real_model_selftest.py -v
```

预期：无 `MODEL_API_KEY` 时相关测试 `SKIPPED`；配置凭据时真实跑一轮纯文本往返 + 一轮会触发工具调
用的对话，断言 core 正确识别并转发了工具调用意图，且（新增的 pi-alignment 场景）事件总线产生了真
实的 `RUN_START`/`TOOL_EXECUTION_*`/`RUN_END` 事件。

## 场景 9：既有测试套件保持通过（回归，不是新场景）

```bash
.venv/bin/pytest tests/ -q
```

预期：除了 spec.md Assumptions 里明确列出的两处"经确认的行为替换"相关测试（
`test_steering_interrupts_an_in_flight_model_call_and_retries` 已删除，替换为
`test_steering_does_not_interrupt_an_in_flight_tool_call`/
`test_steering_does_not_interrupt_generation_and_keeps_the_partial_reply`；
`test_finish_tool_is_offered_even_without_a_tool_registry` 已删除，若干依赖 `finish` 工具终止的
测试已改写为依赖纯文本回复终止）之外，其余全量测试保持通过，且净新增约 50 个测试
（732 passed 基线 → 781 passed）。

## 场景 10：`packages/core` 零依赖边界仍然成立（SC-004）

```bash
.venv/bin/python scripts/check_core_boundary.py
```

预期：退出码 0，零违规——本次新增的全部能力都没有让 `packages/core` 新增对任何其他 `packages/*`
目录的直接导入。

## 场景 11：`apps/api/runtime.py` 侧向确认——事件总线驱动 SSE 流不回归

```bash
.venv/bin/pytest tests/apps/api/test_runtime.py -k "stream or steer" -v
```

预期：现有的流式聊天接口（增量文本、工具结果、用量上报等 SSE 事件类型）在 `_run_turn` 改为订阅事
件总线（`stream=True` + `agent.subscribe(handle_event)`）之后，前端可观察到的事件内容/顺序保持等
价；steering 相关测试（已改写为"不打断"的正向断言）同样通过。
