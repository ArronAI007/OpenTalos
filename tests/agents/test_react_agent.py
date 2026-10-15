import asyncio

import pytest

from core.cancellation import CancellationToken
from core.protocol import AfterCallResult, AgentEvent, BeforeCallResult, EventKind, ToolCompletion, ToolInvocation
from core.errors import EmptyModelResponse, OperationCancelled, OutputLimitError
from ai.model import ModelClient
from tool.outcome import ToolOutcome
from tool.registry import ToolRegistry
from tool.tool import Tool, ToolParameter
from agents.react_agent import STEP_LIMIT_MESSAGE, ReActAgent


async def test_arespond_returns_text_when_the_model_calls_no_tools(scripted_client):
    client = scripted_client(tool_completions=[ToolCompletion(text="direct answer", requested_tools=[], model_id="mock")])
    agent = ReActAgent(name="bot", model_client=client)

    answer = await agent.arespond("what's 2+2")

    assert answer == "direct answer"


async def test_arespond_uses_a_tool_then_finishes(scripted_client, echo_tool_registry):
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')],
                model_id="mock",
            ),
            # 没有更多工具调用的纯文本回复即视为最终答案——finish 工具已移除，这是唯一的正常结束
            # 路径（见 US4：finishTurn 替代 finish 工具）。
            ToolCompletion(text="hi echoed", requested_tools=[], model_id="mock"),
        ]
    )
    agent = ReActAgent(name="bot", model_client=client, tool_registry=echo_tool_registry, max_steps=5)

    answer = await agent.arespond("echo hi then finish")

    assert answer == "hi echoed"


async def test_arespond_falls_back_to_the_step_limit_message(scripted_client, echo_tool_registry):
    looping_call = ToolCompletion(
        text=None,
        requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')],
        model_id="mock",
    )
    client = scripted_client(tool_completions=[looping_call, looping_call])
    agent = ReActAgent(name="bot", model_client=client, tool_registry=echo_tool_registry, max_steps=2)

    answer = await agent.arespond("loop forever")

    assert answer == STEP_LIMIT_MESSAGE


async def test_arespond_streams_text_when_on_text_delta_is_given():
    client = ModelClient(provider="mock")

    async def fake_astream_with_tools(messages, tools, tool_choice="auto", on_text_delta=None, **kwargs):
        if on_text_delta is not None:
            await on_text_delta("42")
        return ToolCompletion(text="42", requested_tools=[], model_id="mock")

    client.astream_with_tools = fake_astream_with_tools
    agent = ReActAgent(name="bot", model_client=client)

    seen: list[str] = []

    async def collect(chunk: str) -> None:
        seen.append(chunk)

    answer = await agent.arespond("what is the answer", on_text_delta=collect)

    assert answer == "42"
    assert seen == ["42"]


async def test_arespond_raises_on_output_limit(scripted_client):
    client = scripted_client(
        tool_completions=[ToolCompletion(text="truncated", requested_tools=[], model_id="mock", finish_reason="length")]
    )
    agent = ReActAgent(name="bot", model_client=client)

    with pytest.raises(OutputLimitError, match="output limit"):
        await agent.arespond("write a very long essay")


async def test_arespond_raises_on_empty_model_response(scripted_client):
    client = scripted_client(tool_completions=[ToolCompletion(text="", requested_tools=[], model_id="mock")])
    agent = ReActAgent(name="bot", model_client=client)

    with pytest.raises(EmptyModelResponse):
        await agent.arespond("say nothing")


async def test_arespond_raises_when_already_cancelled():
    client = ModelClient(provider="mock")
    token = CancellationToken()
    token.cancel()
    agent = ReActAgent(name="bot", model_client=client)

    with pytest.raises(OperationCancelled):
        await agent.arespond("what is the answer", cancellation=token)


async def test_arespond_runs_a_batch_of_tool_calls_concurrently(echo_tool_registry):
    started_order: list[str] = []
    finished_order: list[str] = []

    class _SlowTool(Tool):
        def __init__(self) -> None:
            super().__init__(name="slow", description="Sleeps for a variable amount of time.")

        def parameters(self) -> list[ToolParameter]:
            return [ToolParameter(name="name", type="string", description="Which invocation this is")]

        async def acall(self, arguments):
            name = arguments["name"]
            started_order.append(name)
            await asyncio.sleep(0.05 if name == "first" else 0.01)
            finished_order.append(name)
            return ToolOutcome.ok(name)

    echo_tool_registry.register(_SlowTool())

    client = ModelClient(provider="mock")
    calls = {"count": 0}

    async def fake_acomplete_with_tools(messages, tools, tool_choice="auto", **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return ToolCompletion(
                text=None,
                requested_tools=[
                    ToolInvocation(call_id="c1", tool_name="slow", arguments_json='{"name": "first"}'),
                    ToolInvocation(call_id="c2", tool_name="slow", arguments_json='{"name": "second"}'),
                ],
                model_id="mock",
            )
        return ToolCompletion(text="done", requested_tools=[], model_id="mock")

    client.acomplete_with_tools = fake_acomplete_with_tools
    agent = ReActAgent(name="bot", model_client=client, tool_registry=echo_tool_registry, max_steps=5)

    answer = await agent.arespond("run both slow tools")

    assert answer == "done"
    assert started_order == ["first", "second"]
    assert finished_order == ["second", "first"]


class _GatedTool(Tool):
    def __init__(self) -> None:
        super().__init__(name="danger", description="Side-effecting tool.", requires_approval=True)
        self.calls = 0

    def parameters(self) -> list[ToolParameter]:
        return []

    async def acall(self, arguments):
        self.calls += 1
        return ToolOutcome.ok("executed")


async def test_arespond_asks_for_approval_and_continues_when_denied(scripted_client):
    registry = ToolRegistry()
    tool = _GatedTool()
    registry.register(tool)
    asked: list[str] = []

    async def gate(invocation):
        asked.append(invocation.tool_name)
        return False

    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c1", tool_name="danger", arguments_json="{}")],
                model_id="mock",
            ),
            ToolCompletion(text="moved on", requested_tools=[], model_id="mock"),
        ]
    )
    agent = ReActAgent(
        name="bot", model_client=client, tool_registry=registry, approval_gate=gate, max_steps=5
    )

    answer = await agent.arespond("do the risky thing")

    assert asked == ["danger"]
    assert tool.calls == 0  # 被拒绝，未执行
    assert answer == "moved on"


async def test_steering_injects_a_user_message_at_the_next_step(scripted_client, echo_tool_registry):
    seen: list[list[dict]] = []
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')],
                model_id="mock",
            ),
            ToolCompletion(text="done", requested_tools=[], model_id="mock"),
        ]
    )
    original = client.acomplete_with_tools

    async def spy(messages, tools, tool_choice="auto", **kwargs):
        seen.append([dict(m) for m in messages])
        return await original(messages, tools, tool_choice, **kwargs)

    client.acomplete_with_tools = spy  # type: ignore[method-assign]

    calls = {"n": 0}

    def drain_steer() -> list[str]:
        calls["n"] += 1
        return ["改用中文回答"] if calls["n"] == 2 else []

    agent = ReActAgent(name="bot", model_client=client, tool_registry=echo_tool_registry, max_steps=5)
    answer = await agent.arespond("原始问题", drain_steer=drain_steer)

    assert answer == "done"
    assert not any(m.get("content") == "改用中文回答" for m in seen[0])  # 第一步未注入
    assert any(m.get("content") == "改用中文回答" for m in seen[1])  # 工具调用后注入
    # transcript 顺序：本轮提问 -> steer
    assert [m.content for m in agent.history_snapshot() if m.role == "user"] == ["原始问题", "改用中文回答"]


async def test_recalled_memories_are_injected_as_a_system_message(scripted_client):
    seen: list[list[dict]] = []
    client = scripted_client(
        tool_completions=[ToolCompletion(text="好的", requested_tools=[], model_id="mock")]
    )
    original = client.acomplete_with_tools

    async def spy(messages, tools, tool_choice="auto", **kwargs):
        seen.append([dict(m) for m in messages])
        return await original(messages, tools, tool_choice, **kwargs)

    client.acomplete_with_tools = spy  # type: ignore[method-assign]

    agent = ReActAgent(name="bot", model_client=client)
    await agent.arespond("问题", recalled=["用户叫张三", "用户喜欢简洁"])

    assert seen[0][0]["role"] == "system"  # 原始系统提示
    assert seen[0][1]["role"] == "system"
    assert "用户叫张三" in seen[0][1]["content"]


async def test_steering_does_not_interrupt_an_in_flight_tool_call(echo_tool_registry):
    """FR-006 正向断言：工具调用执行期间排队一条 steering 消息，不会打断/取消这次工具调用——
    这次替换了原来断言"打断正在进行的模型调用"的 test_steering_interrupts_an_in_flight_model_
    call_and_retries（那条断言的行为本身已被移除，不是改名重写）。"""
    tool_started = asyncio.Event()
    release_tool = asyncio.Event()

    class _SlowTool(Tool):
        def __init__(self) -> None:
            super().__init__(name="slow", description="Blocks until released.")

        def parameters(self) -> list[ToolParameter]:
            return []

        async def acall(self, arguments):
            tool_started.set()
            await release_tool.wait()
            return ToolOutcome.ok("slow done")

    echo_tool_registry.register(_SlowTool())

    client = ModelClient(provider="mock")
    calls = {"n": 0}

    async def fake_acomplete_with_tools(messages, tools, tool_choice="auto", **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c1", tool_name="slow", arguments_json="{}")],
                model_id="mock",
            )
        return ToolCompletion(text="done", requested_tools=[], model_id="mock")

    client.acomplete_with_tools = fake_acomplete_with_tools  # type: ignore[method-assign]

    pending: list[str] = []

    def drain_steer() -> list[str]:
        out = list(pending)
        pending.clear()
        return out

    agent = ReActAgent(name="bot", model_client=client, tool_registry=echo_tool_registry, max_steps=5)

    task = asyncio.create_task(agent.arespond("run the slow tool", drain_steer=drain_steer))
    await tool_started.wait()
    pending.append("改用中文回答")  # 工具执行期间排队一条 steering 消息
    await asyncio.sleep(0.01)
    assert not task.done()  # 工具还在执行，没有被取消/打断
    release_tool.set()
    answer = await task

    assert answer == "done"
    assert any(m.content == "改用中文回答" for m in agent.history_snapshot() if m.role == "user")


async def test_followup_injects_a_message_and_keeps_the_run_going(scripted_client):
    client = scripted_client(
        tool_completions=[
            ToolCompletion(text="第一轮回答", requested_tools=[], model_id="mock"),
            ToolCompletion(text="第二轮回答", requested_tools=[], model_id="mock"),
        ]
    )
    calls = {"n": 0}

    def drain_followup() -> list[str]:
        calls["n"] += 1
        return ["还有一件事"] if calls["n"] == 1 else []

    agent = ReActAgent(name="bot", model_client=client, max_steps=5)
    answer = await agent.arespond("原始问题", drain_followup=drain_followup)

    assert answer == "第二轮回答"
    assert [m.content for m in agent.history_snapshot() if m.role == "user"] == ["原始问题", "还有一件事"]


async def test_react_agent_subscribers_see_full_event_sequence_for_a_tool_call_run(scripted_client, echo_tool_registry):
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')],
                model_id="mock",
            ),
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c2", tool_name="echo", arguments_json='{"text": "again"}')],
                model_id="mock",
            ),
            # 没有更多工具调用的纯文本回复即视为最终答案——finish 工具已移除。
            ToolCompletion(text="hi echoed", requested_tools=[], model_id="mock"),
        ]
    )
    agent = ReActAgent(name="bot", model_client=client, tool_registry=echo_tool_registry, max_steps=5)

    events: list[AgentEvent] = []

    async def listener(event: AgentEvent) -> None:
        events.append(event)

    agent.subscribe(listener)

    answer = await agent.arespond_with_callbacks("echo hi then finish")

    assert answer == "hi echoed"
    kinds = [e.kind for e in events]
    assert kinds[0] == EventKind.RUN_START
    assert kinds[-1] == EventKind.RUN_END
    assert EventKind.TURN_START in kinds and EventKind.TURN_END in kinds
    tool_events = [e for e in events if e.kind in (EventKind.TOOL_EXECUTION_START, EventKind.TOOL_EXECUTION_END)]
    # 两次 echo 工具调用各有一对 START/END；第三步的纯文本回复不产生工具执行事件。
    assert [e.kind for e in tool_events] == [
        EventKind.TOOL_EXECUTION_START, EventKind.TOOL_EXECUTION_END,
        EventKind.TOOL_EXECUTION_START, EventKind.TOOL_EXECUTION_END,
    ]
    assert tool_events[0].data["tool_name"] == "echo"
    assert tool_events[2].data["tool_name"] == "echo"


async def test_react_agent_subscribers_see_plain_event_sequence_for_a_no_tool_call_run(scripted_client):
    client = scripted_client(tool_completions=[ToolCompletion(text="direct answer", requested_tools=[], model_id="mock")])
    agent = ReActAgent(name="bot", model_client=client)

    events: list[AgentEvent] = []

    async def listener(event: AgentEvent) -> None:
        events.append(event)

    agent.subscribe(listener)

    answer = await agent.arespond_with_callbacks("what's 2+2")

    assert answer == "direct answer"
    kinds = [e.kind for e in events]
    assert kinds[0] == EventKind.RUN_START
    assert kinds[-1] == EventKind.RUN_END
    assert EventKind.MESSAGE_START in kinds and EventKind.MESSAGE_END in kinds
    assert not any(e.kind in (EventKind.TOOL_EXECUTION_START, EventKind.TOOL_EXECUTION_END) for e in events)


async def test_react_agent_exposes_tool_execution_mode_and_hooks(scripted_client, echo_tool_registry):
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[
                    ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "one"}'),
                    ToolInvocation(call_id="c2", tool_name="echo", arguments_json='{"text": "two"}'),
                ],
                model_id="mock",
            ),
            ToolCompletion(text="done", requested_tools=[], model_id="mock"),
        ]
    )
    order: list[str] = []
    original_acall = echo_tool_registry.acall

    async def spy_acall(name, arguments, *, call_id=None):
        order.append(f"start:{call_id}")
        result = await original_acall(name, arguments, call_id=call_id)
        order.append(f"end:{call_id}")
        return result

    echo_tool_registry.acall = spy_acall  # type: ignore[method-assign]

    before_calls: list[str] = []

    async def before(invocation):
        before_calls.append(invocation.call_id)
        return BeforeCallResult()

    after_calls: list[str] = []

    async def after(invocation, content):
        after_calls.append(invocation.call_id)
        return AfterCallResult(content=f"[hooked] {content}")

    seen: list[list[dict]] = []
    original_acomplete_with_tools = client.acomplete_with_tools

    async def spy_acomplete_with_tools(messages, tools, tool_choice="auto", **kwargs):
        seen.append([dict(m) for m in messages])
        return await original_acomplete_with_tools(messages, tools, tool_choice, **kwargs)

    client.acomplete_with_tools = spy_acomplete_with_tools  # type: ignore[method-assign]

    agent = ReActAgent(
        name="bot",
        model_client=client,
        tool_registry=echo_tool_registry,
        max_steps=5,
        tool_execution_mode="sequential",
        before_tool_call=before,
        after_tool_call=after,
    )

    answer = await agent.arespond("echo both")

    assert answer == "done"
    assert order == ["start:c1", "end:c1", "start:c2", "end:c2"]  # 全局顺序执行模式生效
    assert before_calls == ["c1", "c2"]
    assert after_calls == ["c1", "c2"]
    # afterToolCall 的覆写生效在"发给模型的消息"上（这里用第二步看到的 messages 验证）。
    second_step_messages = seen[1]
    tool_contents = [m["content"] for m in second_step_messages if m.get("role") == "tool"]
    assert tool_contents == ["[hooked] echoed: one", "[hooked] echoed: two"]
    # Agent 自己的历史快照（transcript）保留工具的原始执行结果——afterToolCall 覆写的是"模型看到
    # 的视图"，不是事后篡改审计记录；两者允许不同，这是刻意的设计（见 react_agent.py 的注释）。
    tool_messages = [m.content for m in agent.history_snapshot() if m.role == "tool"]
    assert tool_messages == ["echoed: one", "echoed: two"]


async def test_react_agent_defaults_to_parallel_execution_without_hooks(scripted_client, echo_tool_registry):
    """不传任何新参数时，现状行为（全并发、无钩子）保持不变。"""
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[
                    ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "one"}'),
                    ToolInvocation(call_id="c2", tool_name="echo", arguments_json='{"text": "two"}'),
                ],
                model_id="mock",
            ),
            ToolCompletion(text="done", requested_tools=[], model_id="mock"),
        ]
    )
    started: list[str] = []
    release = asyncio.Event()
    original_acall = echo_tool_registry.acall

    async def spy_acall(name, arguments, *, call_id=None):
        started.append(call_id)
        if len(started) == 1:
            await release.wait()
        else:
            release.set()
        return await original_acall(name, arguments, call_id=call_id)

    echo_tool_registry.acall = spy_acall  # type: ignore[method-assign]

    agent = ReActAgent(name="bot", model_client=client, tool_registry=echo_tool_registry, max_steps=5)
    answer = await agent.arespond("echo both")

    assert answer == "done"
    assert started == ["c1", "c2"]  # 两个调用并发起步


async def test_react_agent_finish_turn_can_end_even_with_pending_tool_calls(scripted_client, echo_tool_registry):
    """finishTurn 替代了 ReAct 原来的 finish 工具终止机制：钩子能在仍有工具调用的情况下强制
    结束运行（US4）。"""
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text="partial",
                requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')],
                model_id="mock",
            ),
            ToolCompletion(text="should not be reached", requested_tools=[], model_id="mock"),
        ]
    )

    async def finish_turn(context):
        return "end"

    agent = ReActAgent(
        name="bot", model_client=client, tool_registry=echo_tool_registry, max_steps=5, finish_turn=finish_turn
    )
    answer = await agent.arespond("echo hi")

    assert answer == "partial"  # 停在第一轮，没有跑到第二轮


async def test_react_agent_default_termination_is_equivalent_to_the_old_finish_tool(scripted_client, echo_tool_registry):
    """一次完整 ReAct 对话（经过若干次工具调用后给出最终回复）在终止机制从 finish 工具换成
    finishTurn 之后，仍能在语义等价的时间点正确结束（SC-005）。"""
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')],
                model_id="mock",
            ),
            ToolCompletion(text="hi echoed, all done", requested_tools=[], model_id="mock"),
        ]
    )
    agent = ReActAgent(name="bot", model_client=client, tool_registry=echo_tool_registry, max_steps=5)

    answer = await agent.arespond("echo hi then finish")

    assert answer == "hi echoed, all done"


async def test_react_agent_exposes_transform_context(scripted_client):
    client = scripted_client(tool_completions=[ToolCompletion(text="done", requested_tools=[], model_id="mock")])
    seen: list[list[dict]] = []
    original = client.acomplete_with_tools

    async def spy(messages, tools, tool_choice="auto", **kwargs):
        seen.append([dict(m) for m in messages])
        return await original(messages, tools, tool_choice, **kwargs)

    client.acomplete_with_tools = spy  # type: ignore[method-assign]

    async def transform(history):
        from core.protocol import ChatMessage

        return [*history, ChatMessage(content="injected", role="user")]

    agent = ReActAgent(name="bot", model_client=client, transform_context=transform)
    await agent.arespond("原始问题")

    assert any(m.get("content") == "injected" for m in seen[0])


async def test_react_agent_exposes_prepare_request_and_prepare_next_turn(scripted_client, echo_tool_registry):
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')],
                model_id="mock",
            ),
            ToolCompletion(text="second", requested_tools=[], model_id="mock"),
        ]
    )
    prepare_request_calls: list[int] = []
    prepare_next_turn_calls = {"n": 0}

    async def prepare_request(context):
        prepare_request_calls.append(context.step)
        return None

    async def prepare_next_turn():
        prepare_next_turn_calls["n"] += 1
        return None

    agent = ReActAgent(
        name="bot",
        model_client=client,
        tool_registry=echo_tool_registry,
        max_steps=5,
        prepare_request=prepare_request,
        prepare_next_turn=prepare_next_turn,
    )
    answer = await agent.arespond("echo then done")

    assert answer == "second"
    assert prepare_request_calls == [1, 2]
    assert prepare_next_turn_calls["n"] == 1  # 只在第一步结束、确定继续时调用一次
