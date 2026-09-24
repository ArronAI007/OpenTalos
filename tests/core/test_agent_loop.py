import asyncio

import pytest

from context import OutputTrimmer
from core.cancellation import CancellationToken
from core.protocol import ChatMessage, Completion, ToolCompletion, ToolInvocation
from core.errors import OperationCancelled
from core.model import FakeModelBackend, ModelClient
from tool.outcome import ToolOutcome
from tool.registry import ToolRegistry
from tool.tool import Tool, ToolParameter
from core.agent_loop import build_reply_message, execute_model_step, run_tool_turn, seed_messages


def test_seed_messages_includes_system_history_and_query():
    history = [ChatMessage(content="hi", role="user"), ChatMessage(content="hello", role="assistant")]
    messages = seed_messages("Be nice.", history, "what's next?")

    assert messages[0] == {"role": "system", "content": "Be nice."}
    assert messages[1] == {"role": "user", "content": "hi"}
    assert messages[2] == {"role": "assistant", "content": "hello"}
    assert messages[3] == {"role": "user", "content": "what's next?"}


def test_seed_messages_omits_system_block_when_no_prompt():
    messages = seed_messages(None, [], "hi")
    assert messages == [{"role": "user", "content": "hi"}]


def test_build_reply_message_shapes_tool_calls_for_the_wire():
    invocation = ToolInvocation(call_id="call_1", tool_name="echo", arguments_json='{"text": "hi"}')
    message = build_reply_message("thinking...", [invocation])

    assert message["role"] == "assistant"
    assert message["content"] == "thinking..."
    assert message["tool_calls"] == [
        {"id": "call_1", "type": "function", "function": {"name": "echo", "arguments": '{"text": "hi"}'}}
    ]


async def test_run_tool_turn_without_registry_just_completes(scripted_client):
    client = scripted_client(completions=[Completion(text="hi there", model_id="mock")])
    answer = await run_tool_turn(client, [{"role": "user", "content": "hi"}], None, 3)
    assert answer == "hi there"


async def test_run_tool_turn_executes_a_tool_then_returns_final_text(scripted_client, echo_tool_registry):
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
    messages = [{"role": "user", "content": "say hi"}]

    answer = await run_tool_turn(client, messages, echo_tool_registry, 3)

    assert answer == "done"
    # assistant tool-call message + tool result message got appended
    assert messages[-2]["role"] == "assistant"
    assert messages[-1] == {"role": "tool", "tool_call_id": "c1", "content": "echoed: hi"}


async def test_run_tool_turn_falls_back_to_plain_complete_after_exhausting_iterations(scripted_client, echo_tool_registry):
    looping_tool_call = ToolCompletion(
        text=None,
        requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')],
        model_id="mock",
    )
    client = scripted_client(
        completions=[Completion(text="giving up", model_id="mock")],
        tool_completions=[looping_tool_call, looping_tool_call],
    )

    answer = await run_tool_turn(client, [{"role": "user", "content": "loop forever"}], echo_tool_registry, 2)

    assert answer == "giving up"


async def test_run_tool_turn_reports_invalid_tool_arguments(scripted_client, echo_tool_registry):
    client = scripted_client(
        tool_completions=[
            ToolCompletion(
                text=None,
                requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json="not json")],
                model_id="mock",
            ),
            ToolCompletion(text="done", requested_tools=[], model_id="mock"),
        ]
    )
    messages: list[dict] = [{"role": "user", "content": "hi"}]

    await run_tool_turn(client, messages, echo_tool_registry, 3)

    tool_message = messages[-1]
    assert tool_message["role"] == "tool"
    assert "Invalid arguments" in tool_message["content"]


def _long_output_registry(line_count: int) -> ToolRegistry:
    class _LongOutputTool(Tool):
        def __init__(self) -> None:
            super().__init__(name="long", description="Returns a lot of lines.")

        def parameters(self) -> list[ToolParameter]:
            return []

        async def acall(self, arguments):
            return ToolOutcome.ok("\n".join(f"line {i}" for i in range(line_count)))

    registry = ToolRegistry()
    registry.register(_LongOutputTool())
    return registry


def _one_long_tool_call() -> list[ToolCompletion]:
    return [
        ToolCompletion(
            text=None,
            requested_tools=[ToolInvocation(call_id="c1", tool_name="long", arguments_json="{}")],
            model_id="mock",
        ),
        ToolCompletion(text="done", requested_tools=[], model_id="mock"),
    ]


async def test_run_tool_turn_feeds_back_the_full_tool_output_without_a_trimmer(scripted_client):
    client = scripted_client(tool_completions=_one_long_tool_call())
    messages: list[dict] = [{"role": "user", "content": "go"}]

    await run_tool_turn(client, messages, _long_output_registry(50), 3)

    tool_message = next(m for m in messages if m["role"] == "tool")
    assert tool_message["content"].count("\n") == 49
    assert "truncated" not in tool_message["content"]


async def test_run_tool_turn_trims_oversized_tool_output_and_points_at_the_saved_file(scripted_client, tmp_path):
    client = scripted_client(tool_completions=_one_long_tool_call())
    trimmer = OutputTrimmer(max_lines=5, max_bytes=1_000_000, output_dir=str(tmp_path))
    messages: list[dict] = [{"role": "user", "content": "go"}]

    await run_tool_turn(client, messages, _long_output_registry(50), 3, trimmer=trimmer)

    content = next(m for m in messages if m["role"] == "tool")["content"]
    assert content.startswith("line 0\nline 1")
    assert "line 40" not in content
    assert "output truncated: 50 lines" in content
    saved = list(tmp_path.glob("long_*.json"))
    assert len(saved) == 1
    assert "line 49" in saved[0].read_text(encoding="utf-8")


async def test_run_tool_turn_leaves_short_tool_output_untouched_even_with_a_trimmer(scripted_client, tmp_path):
    client = scripted_client(tool_completions=_one_long_tool_call())
    trimmer = OutputTrimmer(max_lines=100, max_bytes=1_000_000, output_dir=str(tmp_path))
    messages: list[dict] = [{"role": "user", "content": "go"}]

    await run_tool_turn(client, messages, _long_output_registry(3), 3, trimmer=trimmer)

    content = next(m for m in messages if m["role"] == "tool")["content"]
    assert content == "line 0\nline 1\nline 2"
    assert list(tmp_path.glob("*.json")) == []


async def test_execute_model_step_returns_completion_without_touching_messages_when_no_tools_requested(scripted_client):
    client = scripted_client(tool_completions=[ToolCompletion(text="direct answer", requested_tools=[], model_id="mock")])
    messages = [{"role": "user", "content": "hi"}]

    async def handle_invocation(invocation):
        raise AssertionError("should not be called when no tools were requested")

    completion = await execute_model_step(client, messages, [], handle_invocation=handle_invocation)

    assert completion.text == "direct answer"
    assert messages == [{"role": "user", "content": "hi"}]


async def test_execute_model_step_appends_assistant_and_tool_messages_via_the_given_handler():
    client = ModelClient(provider="mock")

    async def fake_acomplete_with_tools(messages, tools, tool_choice="auto", **kwargs):
        return ToolCompletion(
            text=None,
            requested_tools=[ToolInvocation(call_id="c1", tool_name="custom", arguments_json="{}")],
            model_id="mock",
        )

    client.acomplete_with_tools = fake_acomplete_with_tools
    messages: list[dict] = [{"role": "user", "content": "hi"}]
    handled: list[str] = []

    async def handle_invocation(invocation):
        handled.append(invocation.call_id)
        return {"role": "tool", "tool_call_id": invocation.call_id, "content": "handled"}

    completion = await execute_model_step(client, messages, [], handle_invocation=handle_invocation)

    assert handled == ["c1"]
    assert len(completion.requested_tools) == 1
    assert messages[-2]["role"] == "assistant"
    assert messages[-1] == {"role": "tool", "tool_call_id": "c1", "content": "handled"}


async def test_execute_model_step_raises_when_already_cancelled():
    client = ModelClient(provider="mock")
    token = CancellationToken()
    token.cancel()

    async def handle_invocation(invocation):
        raise AssertionError("should not be reached")

    with pytest.raises(OperationCancelled):
        await execute_model_step(
            client, [{"role": "user", "content": "hi"}], [], cancellation=token, handle_invocation=handle_invocation
        )


async def test_run_tool_turn_streams_text_when_no_registry_and_on_text_delta_is_given():
    client = ModelClient(provider="mock")
    client._backend = FakeModelBackend(model_name="mock-model", response=Completion(text="hello world", model_id="mock"))
    seen: list[str] = []

    async def collect(chunk: str) -> None:
        seen.append(chunk)

    answer = await run_tool_turn(client, [{"role": "user", "content": "hi"}], None, 3, on_text_delta=collect)

    assert answer == "hello world"
    assert "".join(seen) == "hello world"


async def test_run_tool_turn_uses_streaming_backend_call_when_tools_and_on_text_delta_are_given(echo_tool_registry):
    client = ModelClient(provider="mock")

    async def fake_astream_with_tools(messages, tools, tool_choice="auto", on_text_delta=None, **kwargs):
        if on_text_delta is not None:
            await on_text_delta("partial")
        return ToolCompletion(text="partial", requested_tools=[], model_id="mock")

    client.astream_with_tools = fake_astream_with_tools

    seen: list[str] = []

    async def collect(chunk: str) -> None:
        seen.append(chunk)

    answer = await run_tool_turn(
        client, [{"role": "user", "content": "hi"}], echo_tool_registry, 3, on_text_delta=collect
    )

    assert answer == "partial"
    assert seen == ["partial"]


async def test_run_tool_turn_forwards_reasoning_deltas_when_tools_and_callback_are_given(echo_tool_registry):
    client = ModelClient(provider="mock")

    async def fake_astream_with_tools(messages, tools, tool_choice="auto", on_text_delta=None, on_reasoning_delta=None, **kwargs):
        assert on_reasoning_delta is not None
        await on_reasoning_delta("想一下")
        return ToolCompletion(text="done", requested_tools=[], model_id="mock")

    client.astream_with_tools = fake_astream_with_tools

    reasoning: list[str] = []

    async def collect_reasoning(chunk: str) -> None:
        reasoning.append(chunk)

    answer = await run_tool_turn(
        client, [{"role": "user", "content": "hi"}], echo_tool_registry, 3, on_reasoning_delta=collect_reasoning
    )

    assert answer == "done"
    assert reasoning == ["想一下"]


async def test_run_tool_turn_raises_when_already_cancelled_without_a_registry():
    client = ModelClient(provider="mock")
    token = CancellationToken()
    token.cancel()

    with pytest.raises(OperationCancelled):
        await run_tool_turn(client, [{"role": "user", "content": "hi"}], None, 3, cancellation=token)


async def test_run_tool_turn_raises_when_already_cancelled_with_a_registry(echo_tool_registry):
    client = ModelClient(provider="mock")
    token = CancellationToken()
    token.cancel()

    with pytest.raises(OperationCancelled):
        await run_tool_turn(client, [{"role": "user", "content": "hi"}], echo_tool_registry, 3, cancellation=token)


async def test_run_tool_turn_executes_multiple_tool_calls_from_one_batch_concurrently(scripted_client, echo_tool_registry):
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
    messages: list[dict] = [{"role": "user", "content": "echo both"}]

    answer = await run_tool_turn(client, messages, echo_tool_registry, 3)

    assert answer == "done"
    tool_messages = [m for m in messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["c1", "c2"]
    assert [m["content"] for m in tool_messages] == ["echoed: one", "echoed: two"]


async def test_run_tool_turn_stops_once_the_shared_token_budget_is_exceeded(echo_tool_registry):
    client = ModelClient(provider="mock")
    call_count = {"n": 0}

    async def fake_acomplete_with_tools(messages, tools, tool_choice="auto", **kwargs):
        call_count["n"] += 1
        return ToolCompletion(
            text=None,
            requested_tools=[
                ToolInvocation(call_id=f"c{call_count['n']}", tool_name="echo", arguments_json='{"text": "hi"}')
            ],
            model_id="mock",
            token_usage={"total_tokens": 60},
        )

    client.acomplete_with_tools = fake_acomplete_with_tools
    token = CancellationToken(token_budget=100)

    with pytest.raises(OperationCancelled, match="token budget"):
        await run_tool_turn(client, [{"role": "user", "content": "hi"}], echo_tool_registry, 10, cancellation=token)

    # 第一步花掉 60 token（未超预算，那批工具正常执行），第二步再花 60（累计 120 > 100）——
    # 应该在发起第三次模型调用、或者跑第二批工具之前就被挡住，而不是无限循环到 max_iterations。
    assert call_count["n"] == 2


async def test_run_tool_turn_stops_once_the_shared_timeout_elapses(echo_tool_registry):
    client = ModelClient(provider="mock")

    async def fake_acomplete_with_tools(messages, tools, tool_choice="auto", **kwargs):
        await asyncio.sleep(0.02)
        return ToolCompletion(
            text=None,
            requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')],
            model_id="mock",
        )

    client.acomplete_with_tools = fake_acomplete_with_tools
    token = CancellationToken(timeout_seconds=0.01)

    with pytest.raises(OperationCancelled, match="timeout"):
        await run_tool_turn(client, [{"role": "user", "content": "hi"}], echo_tool_registry, 10, cancellation=token)


async def test_run_tool_turn_runs_tool_calls_concurrently_not_sequentially():
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

    registry = ToolRegistry()
    registry.register(_SlowTool())

    client = ModelClient(provider="mock")

    async def fake_acomplete_with_tools(messages, tools, tool_choice="auto", **kwargs):
        if any(m.get("role") == "tool" for m in messages):
            return ToolCompletion(text="done", requested_tools=[], model_id="mock")
        return ToolCompletion(
            text=None,
            requested_tools=[
                ToolInvocation(call_id="c1", tool_name="slow", arguments_json='{"name": "first"}'),
                ToolInvocation(call_id="c2", tool_name="slow", arguments_json='{"name": "second"}'),
            ],
            model_id="mock",
        )

    client.acomplete_with_tools = fake_acomplete_with_tools

    await run_tool_turn(client, [{"role": "user", "content": "go"}], registry, 3)

    # 如果是串行执行，先启动、睡得更久的 "first" 会先结束；并行执行时后启动、睡得更短的
    # "second" 反而先结束——用完成顺序反证两个工具调用确实是并发跑的。
    assert started_order == ["first", "second"]
    assert finished_order == ["second", "first"]
