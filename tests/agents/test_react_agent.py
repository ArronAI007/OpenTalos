import asyncio

import pytest

from core.cancellation import CancellationToken
from core.protocol import ToolCompletion, ToolInvocation
from core.errors import OperationCancelled
from core.model import ModelClient
from tool.outcome import ToolOutcome
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
