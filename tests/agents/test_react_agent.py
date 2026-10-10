import asyncio

import pytest

from core.cancellation import CancellationToken
from core.protocol import ToolCompletion, ToolInvocation
from core.errors import EmptyModelResponse, OperationCancelled, OutputLimitError
from core.model import ModelClient
from tool.outcome import ToolOutcome
from tool.registry import ToolRegistry
from tool.tool import Tool, ToolParameter
from agents.react_agent import FINISH_TOOL_NAME, STEP_LIMIT_MESSAGE, ReActAgent


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
            ToolCompletion(
                text=None,
                requested_tools=[
                    ToolInvocation(call_id="c2", tool_name="finish", arguments_json='{"final_answer": "hi echoed"}')
                ],
                model_id="mock",
            ),
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


async def test_finish_tool_is_offered_even_without_a_tool_registry(scripted_client):
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[
                    ToolInvocation(call_id="c1", tool_name="finish", arguments_json='{"final_answer": "42"}')
                ],
                model_id="mock",
            )
        ]
    )
    agent = ReActAgent(name="bot", model_client=client)

    answer = await agent.arespond("what is the answer")

    assert answer == "42"


async def test_arespond_streams_text_when_on_text_delta_is_given():
    client = ModelClient(provider="mock")

    async def fake_astream_with_tools(messages, tools, tool_choice="auto", on_text_delta=None, **kwargs):
        if on_text_delta is not None:
            await on_text_delta("42")
        return ToolCompletion(
            text=None,
            requested_tools=[ToolInvocation(call_id="c1", tool_name=FINISH_TOOL_NAME, arguments_json='{"final_answer": "42"}')],
            model_id="mock",
        )

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
        return ToolCompletion(
            text=None,
            requested_tools=[ToolInvocation(call_id="c3", tool_name=FINISH_TOOL_NAME, arguments_json='{"final_answer": "done"}')],
            model_id="mock",
        )

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
            ToolCompletion(
                text=None,
                requested_tools=[
                    ToolInvocation(call_id="c2", tool_name=FINISH_TOOL_NAME, arguments_json='{"final_answer": "moved on"}')
                ],
                model_id="mock",
            ),
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


async def test_steering_interrupts_an_in_flight_model_call_and_retries():
    client = ModelClient(provider="mock")
    calls = {"n": 0}
    seen: list[list[dict]] = []
    first_started = asyncio.Event()

    async def fake_acomplete_with_tools(messages, tools, tool_choice="auto", **kwargs):
        calls["n"] += 1
        seen.append([dict(m) for m in messages])
        if calls["n"] == 1:
            first_started.set()
            await asyncio.sleep(3600)  # 只能被 steer 打断，不会自然醒
        return ToolCompletion(text="重跑后的回答", requested_tools=[], model_id="mock")

    client.acomplete_with_tools = fake_acomplete_with_tools  # type: ignore[method-assign]

    steer_event = asyncio.Event()
    pending: list[str] = []

    def drain_steer() -> list[str]:
        out = list(pending)
        pending.clear()
        return out

    interrupts = {"n": 0}

    async def on_steer_interrupt() -> None:
        interrupts["n"] += 1

    agent = ReActAgent(name="bot", model_client=client)

    async def scenario() -> str:
        task = asyncio.create_task(
            agent.arespond(
                "原始问题",
                drain_steer=drain_steer,
                steer_event=steer_event,
                on_steer_interrupt=on_steer_interrupt,
            )
        )
        await first_started.wait()
        pending.append("改用中文")
        steer_event.set()
        return await task

    answer = await scenario()

    assert answer == "重跑后的回答"
    assert interrupts["n"] == 1  # 打断了一次
    assert calls["n"] == 2  # 第一步重跑了一次
    assert any(m.get("content") == "改用中文" for m in seen[1])  # 重跑时已带上 steer
