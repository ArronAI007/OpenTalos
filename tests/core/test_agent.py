import asyncio

import pytest

from core.agent import Agent, AgentPhase, PhaseSignal, RuntimeSettings
from core.protocol import ChatMessage, Completion
from core.model import FakeModelBackend, ModelClient


class _EchoAgent(Agent):
    async def arespond(self, input_text: str, **kwargs: object) -> str:
        return f"echo: {input_text}"


class _FailingAgent(Agent):
    async def arespond(self, input_text: str, **kwargs: object) -> str:
        raise ValueError("boom")


@pytest.fixture
def model_client() -> ModelClient:
    return ModelClient(provider="mock")


async def test_arespond_with_callbacks_returns_arespond_result(model_client):
    agent = _EchoAgent(name="echo", model_client=model_client)
    result = await agent.arespond_with_callbacks("hi")
    assert result == "echo: hi"


async def test_arespond_with_callbacks_calls_on_start_and_on_finish(model_client):
    signals: list[PhaseSignal] = []

    async def record(signal: PhaseSignal) -> None:
        signals.append(signal)

    agent = _EchoAgent(name="echo", model_client=model_client)
    await agent.arespond_with_callbacks("hi", on_start=record, on_finish=record)

    assert [s.phase.value for s in signals] == ["started", "finished"]


async def test_arespond_with_callbacks_calls_on_error_and_reraises(model_client):
    signals: list[PhaseSignal] = []

    async def record(signal: PhaseSignal) -> None:
        signals.append(signal)

    agent = _FailingAgent(name="failing", model_client=model_client)

    with pytest.raises(ValueError, match="boom"):
        await agent.arespond_with_callbacks("hi", on_error=record)

    assert len(signals) == 1
    assert signals[0].phase.value == "failed"
    assert signals[0].data["error"] == "boom"


async def test_arespond_with_callbacks_ignores_callback_exceptions(model_client):
    async def broken_callback(signal: PhaseSignal) -> None:
        raise RuntimeError("callback broke")

    agent = _EchoAgent(name="echo", model_client=model_client)
    result = await agent.arespond_with_callbacks("hi", on_start=broken_callback)
    assert result == "echo: hi"


async def test_arespond_with_callbacks_ignores_callback_timeout(model_client):
    async def slow_callback(signal: PhaseSignal) -> None:
        await asyncio.sleep(1)

    settings = RuntimeSettings(callback_timeout_seconds=0.01)
    agent = _EchoAgent(name="echo", model_client=model_client, settings=settings)
    result = await agent.arespond_with_callbacks("hi", on_start=slow_callback)
    assert result == "echo: hi"


def test_record_message_history_snapshot_reset_history(model_client):
    agent = _EchoAgent(name="echo", model_client=model_client)
    agent.record_message(ChatMessage(content="hi", role="user"))
    agent.record_message(ChatMessage(content="hello", role="assistant"))

    history = agent.history_snapshot()
    assert [m.content for m in history] == ["hi", "hello"]

    agent.reset_history()
    assert agent.history_snapshot() == []


def test_history_snapshot_returns_a_copy(model_client):
    agent = _EchoAgent(name="echo", model_client=model_client)
    agent.record_message(ChatMessage(content="hi", role="user"))
    history = agent.history_snapshot()
    history.append(ChatMessage(content="not stored", role="user"))
    assert len(agent.history_snapshot()) == 1


def test_build_context_includes_system_prompt_history_and_query(model_client):
    agent = _EchoAgent(name="echo", model_client=model_client, system_prompt="Be concise.")
    agent.record_message(ChatMessage(content="hi", role="user"))
    agent.record_message(ChatMessage(content="hello there", role="assistant"))

    context = agent.build_context("hi again")

    assert "Be concise." in context
    assert "[user] hi" in context
    assert "hi again" in context


def test_compress_history_folds_old_turns_and_produces_chat_messages(model_client):
    agent = _EchoAgent(name="echo", model_client=model_client, min_retain_turns=1)
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
    agent = _EchoAgent(name="echo", model_client=model_client, min_retain_turns=10)
    agent.record_message(ChatMessage(content="hi", role="user"))

    assert agent.compress_history("summary") is False
    assert len(agent.history_snapshot()) == 1


def test_recorder_is_none_by_default(model_client):
    agent = _EchoAgent(name="echo", model_client=model_client)
    assert agent.recorder is None


def test_recorder_is_created_when_trace_dir_is_given(model_client, tmp_path):
    agent = _EchoAgent(name="echo", model_client=model_client, trace_dir=str(tmp_path))
    assert agent.recorder is not None
    agent.recorder.finalize()
    assert agent.recorder.jsonl_path.parent == tmp_path


async def test_maybe_compress_history_is_a_noop_when_compaction_is_disabled(model_client):
    agent = _EchoAgent(name="echo", model_client=model_client, min_retain_turns=1)
    for i in range(4):
        agent.record_message(ChatMessage(content=f"question {i}", role="user"))
        agent.record_message(ChatMessage(content=f"answer {i}", role="assistant"))

    changed = await agent.maybe_compress_history()

    assert changed is False
    assert len(agent.history_snapshot()) == 8


async def test_maybe_compress_history_is_a_noop_below_the_token_limit(model_client):
    agent = _EchoAgent(name="echo", model_client=model_client, min_retain_turns=1, compaction_token_limit=100_000)
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
    agent = _EchoAgent(name="echo", model_client=client, min_retain_turns=1, compaction_token_limit=5)
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
    agent = _EchoAgent(name="echo", model_client=client, min_retain_turns=1, compaction_token_limit=5)
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
    agent = _EchoAgent(name="echo", model_client=model_client)
    agent.record_message(ChatMessage(content="hi", role="user"))
    agent.record_message(ChatMessage(content="hello", role="assistant"))

    data = agent.snapshot_history()
    assert [m["content"] for m in data["messages"]] == ["hi", "hello"]

    other = _EchoAgent(name="other", model_client=model_client)
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

def test_phase_signal_emit_sets_timestamp_and_data():
    signal = PhaseSignal.emit(AgentPhase.STARTED, "my-agent", input_text="hi")
    assert signal.phase == AgentPhase.STARTED
    assert signal.agent_name == "my-agent"
    assert signal.data == {"input_text": "hi"}
    assert signal.timestamp > 0


def test_phase_signal_to_dict_uses_phase_value():
    signal = PhaseSignal.emit(AgentPhase.FINISHED, "my-agent", result="done")
    data = signal.to_dict()
    assert data == {
        "phase": "finished",
        "timestamp": signal.timestamp,
        "agent_name": "my-agent",
        "data": {"result": "done"},
    }


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
