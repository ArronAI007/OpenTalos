import asyncio
import json

import pytest

from context import TokenBudget
from core.agent import Agent, RuntimeSettings
from core.protocol import AgentEvent, ChatMessage, Completion, EventKind
from core.model import FakeModelBackend, ModelClient
from memory import WorkingMemory
from observability import RunRecorder


class _EchoAgent(Agent):
    async def arespond(self, input_text: str, **kwargs: object) -> str:
        return f"echo: {input_text}"


class _FailingAgent(Agent):
    async def arespond(self, input_text: str, **kwargs: object) -> str:
        raise ValueError("boom")


def _make_agent(cls, name="echo", *, model_client, min_retain_turns=10, trace_dir=None, **kwargs):
    """测试本地的构造 helper：补齐 Agent 现在要求的 history/token_estimator（core 不再内置默认实
    现，这两个是必填项），trace_dir 转成 trace_recorder_factory，保持测试调用点简洁。"""
    history = WorkingMemory(min_retain_turns=min_retain_turns, message_type=ChatMessage)
    trace_recorder_factory = (lambda: RunRecorder(output_dir=trace_dir)) if trace_dir else None
    return cls(
        name,
        model_client,
        history=history,
        token_estimator=TokenBudget(),
        trace_recorder_factory=trace_recorder_factory,
        **kwargs,
    )


@pytest.fixture
def model_client() -> ModelClient:
    return ModelClient(provider="mock")


async def test_arespond_with_callbacks_returns_arespond_result(model_client):
    agent = _make_agent(_EchoAgent, model_client=model_client)
    result = await agent.arespond_with_callbacks("hi")
    assert result == "echo: hi"


async def test_arespond_with_callbacks_calls_on_start_and_on_finish(model_client):
    events: list[AgentEvent] = []

    async def record(event: AgentEvent) -> None:
        events.append(event)

    agent = _make_agent(_EchoAgent, model_client=model_client)
    await agent.arespond_with_callbacks("hi", on_start=record, on_finish=record)

    assert [e.kind for e in events] == [EventKind.RUN_START, EventKind.RUN_END]
    assert events[1].data["status"] == "completed"


async def test_arespond_with_callbacks_calls_on_error_and_reraises(model_client):
    events: list[AgentEvent] = []

    async def record(event: AgentEvent) -> None:
        events.append(event)

    agent = _make_agent(_FailingAgent, "failing", model_client=model_client)

    with pytest.raises(ValueError, match="boom"):
        await agent.arespond_with_callbacks("hi", on_error=record)

    assert len(events) == 1
    assert events[0].kind == EventKind.RUN_END
    assert events[0].data["status"] == "failed"
    assert events[0].data["error"] == "boom"


async def test_arespond_with_callbacks_ignores_callback_exceptions(model_client):
    async def broken_callback(event: AgentEvent) -> None:
        raise RuntimeError("callback broke")

    agent = _make_agent(_EchoAgent, model_client=model_client)
    result = await agent.arespond_with_callbacks("hi", on_start=broken_callback)
    assert result == "echo: hi"


async def test_arespond_with_callbacks_ignores_callback_timeout(model_client):
    async def slow_callback(event: AgentEvent) -> None:
        await asyncio.sleep(1)

    settings = RuntimeSettings(callback_timeout_seconds=0.01)
    agent = _make_agent(_EchoAgent, model_client=model_client, settings=settings)
    result = await agent.arespond_with_callbacks("hi", on_start=slow_callback)
    assert result == "echo: hi"


def test_record_message_history_snapshot_reset_history(model_client):
    agent = _make_agent(_EchoAgent, model_client=model_client)
    agent.record_message(ChatMessage(content="hi", role="user"))
    agent.record_message(ChatMessage(content="hello", role="assistant"))

    history = agent.history_snapshot()
    assert [m.content for m in history] == ["hi", "hello"]

    agent.reset_history()
    assert agent.history_snapshot() == []


def test_history_snapshot_returns_a_copy(model_client):
    agent = _make_agent(_EchoAgent, model_client=model_client)
    agent.record_message(ChatMessage(content="hi", role="user"))
    history = agent.history_snapshot()
    history.append(ChatMessage(content="not stored", role="user"))
    assert len(agent.history_snapshot()) == 1


def test_build_context_includes_system_prompt_history_and_query(model_client):
    agent = _make_agent(_EchoAgent, model_client=model_client, system_prompt="Be concise.")
    agent.record_message(ChatMessage(content="hi", role="user"))
    agent.record_message(ChatMessage(content="hello there", role="assistant"))

    context = agent.build_context("hi again")

    assert "Be concise." in context
    assert "[user] hi" in context
    assert "hi again" in context


def test_compress_history_folds_old_turns_and_produces_chat_messages(model_client):
    agent = _make_agent(_EchoAgent, model_client=model_client, min_retain_turns=1)
    for i in range(4):
        agent.record_message(ChatMessage(content=f"question {i}", role="user"))
        agent.record_message(ChatMessage(content=f"answer {i}", role="assistant"))

    changed = agent.compress_history("earlier discussion")
    assert changed is True

    history = agent.history_snapshot()
    assert isinstance(history[0], ChatMessage)
    assert history[0].role == "summary"
    assert "earlier discussion" in history[0].content


def test_compress_history_is_a_noop_below_the_retain_threshold(model_client):
    agent = _make_agent(_EchoAgent, model_client=model_client, min_retain_turns=10)
    agent.record_message(ChatMessage(content="hi", role="user"))

    assert agent.compress_history("summary") is False
    assert len(agent.history_snapshot()) == 1


def test_recorder_is_none_by_default(model_client):
    agent = _make_agent(_EchoAgent, model_client=model_client)
    assert agent.recorder is None


def test_recorder_is_created_per_turn_and_finalized(model_client, tmp_path):
    agent = _make_agent(_EchoAgent, model_client=model_client, trace_dir=str(tmp_path))
    assert agent.recorder is None  # 一轮一份：轮与轮之间不持有 recorder

    asyncio.run(agent.arespond_with_callbacks("hi"))

    assert agent.recorder is None  # 轮末已 finalize
    jsonl_files = list(tmp_path.glob("run-*.jsonl"))
    html_files = list(tmp_path.glob("run-*.html"))
    assert len(jsonl_files) == 1 and len(html_files) == 1

    events = [json.loads(line)["event"] for line in jsonl_files[0].read_text(encoding="utf-8").splitlines()]
    assert events[0] == "session_start"
    assert events[-1] == "session_end"
    # 统计面板只在 finalize 时写；生产路径下以前永远不会出现
    assert "Session Stats" in html_files[0].read_text(encoding="utf-8")


def test_each_turn_produces_its_own_trace(model_client, tmp_path):
    agent = _make_agent(_EchoAgent, model_client=model_client, trace_dir=str(tmp_path))
    asyncio.run(agent.arespond_with_callbacks("one"))
    asyncio.run(agent.arespond_with_callbacks("two"))
    assert len(list(tmp_path.glob("run-*.jsonl"))) == 2


def test_trace_metadata_lands_in_session_start(model_client, tmp_path):
    agent = _make_agent(
        _EchoAgent, model_client=model_client, trace_dir=str(tmp_path), trace_metadata={"task_id": "t-1"}
    )
    asyncio.run(agent.arespond_with_callbacks("hi"))
    first = next(tmp_path.glob("run-*.jsonl")).read_text(encoding="utf-8").splitlines()[0]
    assert json.loads(first)["payload"]["task_id"] == "t-1"


async def test_maybe_compress_history_is_a_noop_when_compaction_is_disabled(model_client):
    agent = _make_agent(_EchoAgent, model_client=model_client, min_retain_turns=1)
    for i in range(4):
        agent.record_message(ChatMessage(content=f"question {i}", role="user"))
        agent.record_message(ChatMessage(content=f"answer {i}", role="assistant"))

    changed = await agent.maybe_compress_history()

    assert changed is False
    assert len(agent.history_snapshot()) == 8


async def test_maybe_compress_history_is_a_noop_below_the_token_limit(model_client):
    agent = _make_agent(
        _EchoAgent, model_client=model_client, min_retain_turns=1, compaction_token_limit=100_000
    )
    agent.record_message(ChatMessage(content="hi", role="user"))
    agent.record_message(ChatMessage(content="hello", role="assistant"))

    changed = await agent.maybe_compress_history()

    assert changed is False
    assert len(agent.history_snapshot()) == 2


async def test_maybe_compress_history_summarizes_and_folds_history_once_over_the_limit():
    client = ModelClient(provider="mock")
    client._backend = FakeModelBackend(
        model_name="mock-model", response=Completion(text="condensed summary", model_id="mock-model")
    )
    agent = _make_agent(_EchoAgent, model_client=client, min_retain_turns=1, compaction_token_limit=5)
    for i in range(4):
        agent.record_message(ChatMessage(content=f"question {i}", role="user"))
        agent.record_message(ChatMessage(content=f"answer {i}", role="assistant"))

    changed = await agent.maybe_compress_history()

    assert changed is True
    history = agent.history_snapshot()
    assert history[0].role == "summary"
    assert "condensed summary" in history[0].content


async def test_maybe_compress_history_notifies_on_compression_when_folded():
    client = ModelClient(provider="mock")
    client._backend = FakeModelBackend(
        model_name="mock-model", response=Completion(text="condensed summary", model_id="mock-model")
    )
    agent = _make_agent(_EchoAgent, model_client=client, min_retain_turns=1, compaction_token_limit=5)
    for i in range(4):
        agent.record_message(ChatMessage(content=f"question {i}", role="user"))
        agent.record_message(ChatMessage(content=f"answer {i}", role="assistant"))

    notified: list[bool] = []

    async def on_compression() -> None:
        notified.append(True)

    agent.on_compression = on_compression

    changed = await agent.maybe_compress_history()

    assert changed is True
    assert notified == [True]


def test_snapshot_and_restore_history_round_trip(model_client):
    agent = _make_agent(_EchoAgent, model_client=model_client)
    agent.record_message(ChatMessage(content="hi", role="user"))
    agent.record_message(ChatMessage(content="hello", role="assistant"))

    data = agent.snapshot_history()
    assert [m["content"] for m in data["messages"]] == ["hi", "hello"]

    other = _make_agent(_EchoAgent, "other", model_client=model_client)
    other.restore_history(data)
    assert [m.content for m in other.history_snapshot()] == ["hi", "hello"]


def test_runtime_settings_has_expected_defaults():
    settings = RuntimeSettings()
    assert settings.temperature == 0.7
    assert settings.max_tokens is None
    assert settings.debug is False
    assert settings.log_level == "INFO"
    assert settings.callback_timeout_seconds == 5.0


def test_runtime_settings_accepts_overrides():
    settings = RuntimeSettings(
        temperature=0.2, max_tokens=100, debug=True, log_level="DEBUG", callback_timeout_seconds=1.0
    )
    assert settings.temperature == 0.2
    assert settings.max_tokens == 100
    assert settings.debug is True
    assert settings.log_level == "DEBUG"
    assert settings.callback_timeout_seconds == 1.0

def test_agent_event_emit_sets_timestamp_and_data():
    event = AgentEvent.emit(EventKind.RUN_START, "my-agent", input_text="hi")
    assert event.kind == EventKind.RUN_START
    assert event.agent_name == "my-agent"
    assert event.data == {"input_text": "hi"}
    assert event.timestamp > 0


def test_agent_event_to_dict_uses_kind_value():
    event = AgentEvent.emit(EventKind.RUN_END, "my-agent", result="done")
    data = event.to_dict()
    assert data == {
        "kind": "run_end",
        "timestamp": event.timestamp,
        "agent_name": "my-agent",
        "data": {"result": "done"},
    }


async def test_subscribe_notifies_multiple_listeners_in_registration_order(model_client):
    order: list[str] = []

    async def first(event: AgentEvent) -> None:
        order.append("first-start")
        await asyncio.sleep(0.02)
        order.append("first-end")

    async def second(event: AgentEvent) -> None:
        order.append("second-start")
        order.append("second-end")

    agent = _make_agent(_EchoAgent, model_client=model_client)
    agent.subscribe(first)
    agent.subscribe(second)

    await agent.arespond_with_callbacks("hi")

    # 两个监听器各自对 RUN_START 和 RUN_END 都要被按注册顺序依次 await，first 在 second 开始之前
    # 必须已经完全跑完（而不是两者交错）。
    assert order == [
        "first-start", "first-end", "second-start", "second-end",
        "first-start", "first-end", "second-start", "second-end",
    ]


async def test_subscribe_listener_exception_does_not_stop_other_listeners_or_main_flow(model_client):
    order: list[str] = []

    async def broken(event: AgentEvent) -> None:
        order.append("broken")
        raise RuntimeError("listener broke")

    async def healthy(event: AgentEvent) -> None:
        order.append("healthy")

    agent = _make_agent(_EchoAgent, model_client=model_client)
    agent.subscribe(broken)
    agent.subscribe(healthy)

    result = await agent.arespond_with_callbacks("hi")

    assert result == "echo: hi"
    assert order.count("broken") == 2  # RUN_START + RUN_END
    assert order.count("healthy") == 2


async def test_run_end_listeners_finish_before_arespond_with_callbacks_returns(model_client):
    finished_before_return = False

    async def slow_listener(event: AgentEvent) -> None:
        nonlocal finished_before_return
        if event.kind == EventKind.RUN_END:
            await asyncio.sleep(0.05)
            finished_before_return = True

    agent = _make_agent(_EchoAgent, model_client=model_client)
    agent.subscribe(slow_listener)

    await agent.arespond_with_callbacks("hi")

    assert finished_before_return is True


async def test_subscribe_returns_an_unsubscribe_function(model_client):
    received: list[AgentEvent] = []

    async def listener(event: AgentEvent) -> None:
        received.append(event)

    agent = _make_agent(_EchoAgent, model_client=model_client)
    unsubscribe = agent.subscribe(listener)
    unsubscribe()

    await agent.arespond_with_callbacks("hi")

    assert received == []


def test_scripted_client_streams_tool_completion_via_astream(scripted_client):
    """SSE 路径走的是 astream_with_tools：夹具必须也能驱动它（增量吐 text + 返回 completion）。"""
    import asyncio

    from core.protocol import ToolCompletion, ToolInvocation

    completion = ToolCompletion(
        text="done",
        requested_tools=[ToolInvocation(call_id="c1", tool_name="echo", arguments_json='{"text":"hi"}')],
        model_id="mock-model",
    )
    client = scripted_client(tool_completions=[completion])

    async def run() -> tuple[list[str], ToolCompletion]:
        deltas: list[str] = []

        async def on_delta(chunk: str) -> None:
            deltas.append(chunk)

        result = await client.astream_with_tools([], [], on_text_delta=on_delta)
        return deltas, result

    deltas, result = asyncio.run(run())
    assert "".join(deltas) == "done"
    assert result.requested_tools[0].tool_name == "echo"


async def test_build_messages_uses_transform_context_return_value(model_client):
    async def transform(history: list[ChatMessage]) -> list[ChatMessage]:
        return [*history, ChatMessage(content="injected by transform_context", role="user")]

    agent = _make_agent(_EchoAgent, model_client=model_client, transform_context=transform)
    agent.record_message(ChatMessage(content="original", role="user"))

    messages = await agent.build_messages("latest question")

    assert any(m.get("content") == "injected by transform_context" for m in messages)


async def test_build_messages_degrades_to_original_history_when_transform_context_raises(model_client):
    async def broken_transform(history: list[ChatMessage]) -> list[ChatMessage]:
        raise RuntimeError("transform_context broke")

    agent = _make_agent(_EchoAgent, model_client=model_client, transform_context=broken_transform)
    agent.record_message(ChatMessage(content="original", role="user"))

    messages = await agent.build_messages("latest question")

    assert any(m.get("content") == "original" for m in messages)  # 降级：原始历史仍然生效


async def test_build_messages_uses_original_history_when_transform_context_not_provided(model_client):
    agent = _make_agent(_EchoAgent, model_client=model_client)
    agent.record_message(ChatMessage(content="original", role="user"))

    messages = await agent.build_messages("latest question")

    assert any(m.get("content") == "original" for m in messages)
