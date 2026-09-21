import asyncio

import pytest

from core.agent import Agent
from core.config import Config
from core.lifecycle import AgentEvent
from core.llm import LLMClient
from core.message import Message


class _EchoAgent(Agent):
    async def arun(self, input_text: str, **kwargs: object) -> str:
        return f"echo: {input_text}"


class _FailingAgent(Agent):
    async def arun(self, input_text: str, **kwargs: object) -> str:
        raise ValueError("boom")


@pytest.fixture
def llm() -> LLMClient:
    return LLMClient(provider="mock")


async def test_run_with_hooks_returns_arun_result(llm):
    agent = _EchoAgent(name="echo", llm=llm)
    result = await agent.run_with_hooks("hi")
    assert result == "echo: hi"


async def test_run_with_hooks_calls_on_start_and_on_finish(llm):
    events: list[AgentEvent] = []

    async def record(event: AgentEvent) -> None:
        events.append(event)

    agent = _EchoAgent(name="echo", llm=llm)
    await agent.run_with_hooks("hi", on_start=record, on_finish=record)

    assert [e.type.value for e in events] == ["agent_start", "agent_finish"]


async def test_run_with_hooks_calls_on_error_and_reraises(llm):
    events: list[AgentEvent] = []

    async def record(event: AgentEvent) -> None:
        events.append(event)

    agent = _FailingAgent(name="failing", llm=llm)

    with pytest.raises(ValueError, match="boom"):
        await agent.run_with_hooks("hi", on_error=record)

    assert len(events) == 1
    assert events[0].type.value == "agent_error"
    assert events[0].data["error"] == "boom"


async def test_run_with_hooks_ignores_hook_exceptions(llm):
    async def broken_hook(event: AgentEvent) -> None:
        raise RuntimeError("hook broke")

    agent = _EchoAgent(name="echo", llm=llm)
    result = await agent.run_with_hooks("hi", on_start=broken_hook)
    assert result == "echo: hi"


async def test_run_with_hooks_ignores_hook_timeout(llm):
    async def slow_hook(event: AgentEvent) -> None:
        await asyncio.sleep(1)

    config = Config(hook_timeout_seconds=0.01)
    agent = _EchoAgent(name="echo", llm=llm, config=config)
    result = await agent.run_with_hooks("hi", on_start=slow_hook)
    assert result == "echo: hi"


def test_add_message_get_history_clear_history(llm):
    agent = _EchoAgent(name="echo", llm=llm)
    agent.add_message(Message(content="hi", role="user"))
    agent.add_message(Message(content="hello", role="assistant"))

    history = agent.get_history()
    assert [m.content for m in history] == ["hi", "hello"]

    agent.clear_history()
    assert agent.get_history() == []


def test_get_history_returns_a_copy(llm):
    agent = _EchoAgent(name="echo", llm=llm)
    agent.add_message(Message(content="hi", role="user"))
    history = agent.get_history()
    history.append(Message(content="not stored", role="user"))
    assert len(agent.get_history()) == 1
