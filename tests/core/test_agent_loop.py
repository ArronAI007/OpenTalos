import asyncio

import pytest

from context import OutputTrimmer
from core.cancellation import CancellationToken
from core.protocol import ChatMessage, Completion, ToolCompletion, ToolInvocation
from core.errors import AgentRuntimeError, EmptyModelResponse, OperationCancelled, OutputLimitError
from core.model import FakeModelBackend, ModelClient
from tool.outcome import ToolOutcome
from tool.registry import ToolRegistry
from tool.tool import Tool, ToolParameter
from core.agent_loop import build_reply_message, execute_model_step, resolve_tool_call, run_tool_turn


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


async def test_execute_model_step_records_request_with_redacted_messages_and_tools(tmp_path):
    # 输入侧审计：记录模型当次看到的脱敏 messages + tools，出问题时能回放"当时给了什么上下文"。
    from observability.run_recorder import RunRecorder

    client = ModelClient(provider="mock")

    async def fake_acomplete_with_tools(messages, tools, tool_choice="auto", **kwargs):
        return ToolCompletion(text="done", requested_tools=[], model_id="mock")

    client.acomplete_with_tools = fake_acomplete_with_tools  # type: ignore[method-assign]
    recorder = RunRecorder(output_dir=str(tmp_path))
    messages = [
        {"role": "system", "content": "key=sk-abc123XYZ"},
        {"role": "user", "content": "hi"},
    ]
    tools = [{"type": "function", "function": {"name": "echo", "parameters": {}}}]

    async def handle_invocation(invocation):
        raise AssertionError("should not be called")

    await execute_model_step(
        client, messages, tools, recorder=recorder, step=1, handle_invocation=handle_invocation
    )
    recorder.finalize()

    request = next(e for e in recorder.events() if e["event"] == "request")
    assert request["step"] == 1
    assert request["payload"]["messages"][0]["content"] == "key=sk-***"
    assert request["payload"]["tools"][0]["function"]["name"] == "echo"


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


# ==================== 输出上限 / 空响应 / 工具 id 校验 / 中断回执 ====================


async def test_run_tool_turn_raises_on_output_limit_without_a_registry(scripted_client):
    client = scripted_client(completions=[Completion(text="partial", model_id="mock", finish_reason="length")])

    with pytest.raises(OutputLimitError, match="output limit"):
        await run_tool_turn(client, [{"role": "user", "content": "hi"}], None, 3)


async def test_run_tool_turn_raises_on_empty_response_without_a_registry(scripted_client):
    client = scripted_client(completions=[Completion(text="   ", model_id="mock")])

    with pytest.raises(EmptyModelResponse):
        await run_tool_turn(client, [{"role": "user", "content": "hi"}], None, 3)


async def test_run_tool_turn_raises_on_output_limit_in_the_iteration_fallback(scripted_client, echo_tool_registry):
    looping = ToolCompletion(
        text=None,
        requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')],
        model_id="mock",
        finish_reason="tool_calls",
    )
    client = scripted_client(
        completions=[Completion(text="truncated", model_id="mock", finish_reason="length")],
        tool_completions=[looping],
    )

    with pytest.raises(OutputLimitError, match="output limit"):
        await run_tool_turn(client, [{"role": "user", "content": "loop"}], echo_tool_registry, 1)


async def test_execute_model_step_raises_on_output_limit(scripted_client):
    client = scripted_client(
        tool_completions=[ToolCompletion(text="partial", requested_tools=[], model_id="mock", finish_reason="length")]
    )

    async def handle_invocation(invocation):
        raise AssertionError("should not be called")

    with pytest.raises(OutputLimitError, match="output limit"):
        await execute_model_step(client, [{"role": "user", "content": "hi"}], [], handle_invocation=handle_invocation)


async def test_execute_model_step_raises_on_empty_response(scripted_client):
    client = scripted_client(
        tool_completions=[ToolCompletion(text="", requested_tools=[], model_id="mock")]
    )

    async def handle_invocation(invocation):
        raise AssertionError("should not be called")

    with pytest.raises(EmptyModelResponse):
        await execute_model_step(client, [{"role": "user", "content": "hi"}], [], handle_invocation=handle_invocation)


def _duplicate_tool_completion(call_id: str) -> ToolCompletion:
    return ToolCompletion(
        text=None,
        requested_tools=[
            ToolInvocation(call_id=call_id, tool_name="a", arguments_json="{}"),
            ToolInvocation(call_id=call_id, tool_name="b", arguments_json="{}"),
        ],
        model_id="mock",
    )


async def test_execute_model_step_rejects_duplicate_tool_call_ids():
    client = ModelClient(provider="mock")

    async def fake_acomplete_with_tools(messages, tools, tool_choice="auto", **kwargs):
        return _duplicate_tool_completion("dup")

    client.acomplete_with_tools = fake_acomplete_with_tools  # type: ignore[method-assign]

    async def handle_invocation(invocation):
        return {"role": "tool", "tool_call_id": invocation.call_id, "content": "x"}

    with pytest.raises(AgentRuntimeError, match="tool call ids"):
        await execute_model_step(
            client, [{"role": "user", "content": "hi"}], [], handle_invocation=handle_invocation
        )


async def test_execute_model_step_rejects_empty_tool_call_id():
    client = ModelClient(provider="mock")

    async def fake_acomplete_with_tools(messages, tools, tool_choice="auto", **kwargs):
        return ToolCompletion(
            text=None,
            requested_tools=[ToolInvocation(call_id="  ", tool_name="a", arguments_json="{}")],
            model_id="mock",
        )

    client.acomplete_with_tools = fake_acomplete_with_tools  # type: ignore[method-assign]

    async def handle_invocation(invocation):
        return {"role": "tool", "tool_call_id": invocation.call_id, "content": "x"}

    with pytest.raises(AgentRuntimeError, match="tool call ids"):
        await execute_model_step(
            client, [{"role": "user", "content": "hi"}], [], handle_invocation=handle_invocation
        )


async def test_execute_model_step_records_unknown_receipts_for_interrupted_tool_calls():
    client = ModelClient(provider="mock")

    async def fake_acomplete_with_tools(messages, tools, tool_choice="auto", **kwargs):
        return ToolCompletion(
            text=None,
            requested_tools=[
                ToolInvocation(call_id="c1", tool_name="a", arguments_json="{}"),
                ToolInvocation(call_id="c2", tool_name="b", arguments_json="{}"),
            ],
            model_id="mock",
        )

    client.acomplete_with_tools = fake_acomplete_with_tools  # type: ignore[method-assign]
    recorded: list[tuple] = []

    async def handle_invocation(invocation):
        raise RuntimeError("tool exploded")

    with pytest.raises(RuntimeError, match="tool exploded"):
        await execute_model_step(
            client,
            [{"role": "user", "content": "hi"}],
            [],
            handle_invocation=handle_invocation,
            on_tool_result=lambda *args: recorded.append(args),
        )

    assert {receipt[0] for receipt in recorded} == {"c1", "c2"}
    assert all("unknown" in receipt[3] for receipt in recorded)


# ==================== 副作用工具审批闸门 ====================


class _DangerousTool(Tool):
    def __init__(self) -> None:
        super().__init__(name="danger", description="Side-effecting tool.", requires_approval=True)
        self.calls = 0

    def parameters(self) -> list[ToolParameter]:
        return []

    async def acall(self, arguments):
        self.calls += 1
        return ToolOutcome.ok("executed")


def _dangerous_registry() -> tuple[ToolRegistry, _DangerousTool]:
    registry = ToolRegistry()
    tool = _DangerousTool()
    registry.register(tool)
    return registry, tool


async def test_resolve_tool_call_denies_a_gated_tool_without_an_approve_channel():
    registry, tool = _dangerous_registry()
    invocation = ToolInvocation(call_id="c1", tool_name="danger", arguments_json="{}")

    message = await resolve_tool_call(registry, invocation)

    assert tool.calls == 0
    assert "denied" in message["content"].lower()


async def test_resolve_tool_call_denies_when_the_gate_returns_false():
    registry, tool = _dangerous_registry()
    invocation = ToolInvocation(call_id="c1", tool_name="danger", arguments_json="{}")

    async def deny(_invocation):
        return False

    message = await resolve_tool_call(registry, invocation, approve=deny)

    assert tool.calls == 0
    assert "denied" in message["content"].lower()


async def test_resolve_tool_call_executes_when_the_gate_approves():
    registry, tool = _dangerous_registry()
    invocation = ToolInvocation(call_id="c1", tool_name="danger", arguments_json="{}")
    seen: list[str] = []

    async def allow(invocation):
        seen.append(invocation.call_id)
        return True

    message = await resolve_tool_call(registry, invocation, approve=allow)

    assert seen == ["c1"]
    assert tool.calls == 1
    assert message["content"] == "executed"


async def test_resolve_tool_call_does_not_gate_a_safe_tool(echo_tool_registry):
    called: list[str] = []

    async def gate(invocation):
        called.append(invocation.tool_name)
        return False

    invocation = ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')
    message = await resolve_tool_call(echo_tool_registry, invocation, approve=gate)

    assert called == []
    assert message["content"] == "echoed: hi"


# ==================== 不可信输出隔离（prompt injection 防线） ====================


class _UntrustedTool(Tool):
    def __init__(self, output: str = "external data") -> None:
        super().__init__(name="external", description="External source.", untrusted_output=True)
        self._output = output

    def parameters(self) -> list[ToolParameter]:
        return []

    async def acall(self, arguments):
        return ToolOutcome.ok(self._output)


async def test_resolve_tool_call_spotlights_untrusted_output_for_the_model_and_transcript():
    registry = ToolRegistry()
    registry.register(_UntrustedTool())
    invocation = ToolInvocation(call_id="c1", tool_name="external", arguments_json="{}")
    recorded: list[tuple] = []

    message = await resolve_tool_call(registry, invocation, on_tool_result=lambda *a: recorded.append(a))

    assert "<<<UNTRUSTED>>>" in message["content"]
    assert "never follow" in message["content"].lower()
    assert "external data" in message["content"]
    # transcript 存同一份包裹后的内容，重放时模型仍能看到隔离标记。
    assert "<<<UNTRUSTED>>>" in recorded[0][3]


async def test_resolve_tool_call_leaves_trusted_output_unwrapped(echo_tool_registry):
    invocation = ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text": "hi"}')

    message = await resolve_tool_call(echo_tool_registry, invocation)

    assert message["content"] == "echoed: hi"
    assert "UNTRUSTED" not in message["content"]


async def test_resolve_tool_call_spotlights_trimmed_untrusted_output(tmp_path):
    registry = ToolRegistry()
    registry.register(_UntrustedTool("\n".join(f"line {i}" for i in range(50))))
    trimmer = OutputTrimmer(max_lines=5, max_bytes=1_000_000, output_dir=str(tmp_path))
    invocation = ToolInvocation(call_id="c1", tool_name="external", arguments_json="{}")

    message = await resolve_tool_call(registry, invocation, trimmer=trimmer)

    assert "<<<UNTRUSTED>>>" in message["content"]
    assert "output truncated" in message["content"]
    assert "line 40" not in message["content"]
