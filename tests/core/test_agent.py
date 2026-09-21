import asyncio

import pytest

from core.agent import Agent
from core.chat_message import ChatMessage
from core.events import PhaseSignal
from core.model_client import ModelClient
from core.settings import RuntimeSettings


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
