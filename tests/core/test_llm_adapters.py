import pytest

from core.exceptions import ConfigError
from core.llm_adapters import MockAdapter, create_adapter
from core.llm_response import LLMResponse


async def test_mock_adapter_ainvoke_returns_configured_response():
    adapter = MockAdapter(model="mock-model", response=LLMResponse(content="hi there", model="mock-model"))
    result = await adapter.ainvoke([{"role": "user", "content": "hello"}])
    assert result.content == "hi there"


async def test_mock_adapter_ainvoke_uses_responder_when_given():
    def responder(messages):
        return LLMResponse(content=f"echo: {messages[-1]['content']}", model="mock-model")

    adapter = MockAdapter(model="mock-model", responder=responder)
    result = await adapter.ainvoke([{"role": "user", "content": "hello"}])
    assert result.content == "echo: hello"


async def test_mock_adapter_ainvoke_defaults_to_empty_content_when_unconfigured():
    adapter = MockAdapter(model="mock-model")
    result = await adapter.ainvoke([{"role": "user", "content": "hello"}])
    assert result.content == ""


async def test_mock_adapter_astream_invoke_yields_response_content_character_by_character():
    adapter = MockAdapter(model="mock-model", response=LLMResponse(content="ab", model="mock-model"))
    chunks = [chunk async for chunk in adapter.astream_invoke([{"role": "user", "content": "hi"}])]
    assert chunks == ["a", "b"]
    assert adapter.last_stats is not None


async def test_mock_adapter_ainvoke_with_tools_returns_no_tool_calls():
    adapter = MockAdapter(model="mock-model", response=LLMResponse(content="hi", model="mock-model"))
    result = await adapter.ainvoke_with_tools([{"role": "user", "content": "hi"}], tools=[])
    assert result.tool_calls == []
    assert result.content == "hi"


def test_create_adapter_returns_mock_adapter_for_mock_provider():
    adapter = create_adapter("mock", api_key="mock", base_url=None, timeout=60, model="mock-model")
    assert isinstance(adapter, MockAdapter)


def test_create_adapter_rejects_unknown_provider():
    with pytest.raises(ConfigError, match="Unknown MODEL_PROVIDER"):
        create_adapter("does-not-exist", api_key="k", base_url=None, timeout=60, model="m")


from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.llm_adapters import OpenAICompatibleAdapter


def _fake_openai_response(content, *, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


async def test_openai_compatible_adapter_ainvoke_parses_content_and_usage(monkeypatch):
    fake_response = _fake_openai_response("hello there")
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    )
    monkeypatch.setattr("core.llm_adapters.AsyncOpenAI", lambda **kwargs: fake_client)

    adapter = OpenAICompatibleAdapter(api_key="k", base_url=None, timeout=60, model="gpt-test")
    result = await adapter.ainvoke([{"role": "user", "content": "hi"}])

    assert result.content == "hello there"
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    fake_client.chat.completions.create.assert_awaited_once()


async def test_openai_compatible_adapter_ainvoke_with_tools_parses_tool_calls(monkeypatch):
    tool_call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="search", arguments='{"q": "x"}'))
    fake_response = _fake_openai_response(None, tool_calls=[tool_call])
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    )
    monkeypatch.setattr("core.llm_adapters.AsyncOpenAI", lambda **kwargs: fake_client)

    adapter = OpenAICompatibleAdapter(api_key="k", base_url=None, timeout=60, model="gpt-test")
    result = await adapter.ainvoke_with_tools(
        [{"role": "user", "content": "hi"}], tools=[{"type": "function", "function": {"name": "search"}}]
    )

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "search"
    assert result.tool_calls[0].arguments == '{"q": "x"}'


async def test_openai_compatible_adapter_astream_invoke_yields_delta_content(monkeypatch):
    async def fake_stream():
        for text in ["hel", "lo"]:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=fake_stream())))
    )
    monkeypatch.setattr("core.llm_adapters.AsyncOpenAI", lambda **kwargs: fake_client)

    adapter = OpenAICompatibleAdapter(api_key="k", base_url=None, timeout=60, model="gpt-test")
    chunks = [chunk async for chunk in adapter.astream_invoke([{"role": "user", "content": "hi"}])]
    assert chunks == ["hel", "lo"]
    assert adapter.last_stats is not None


def test_create_adapter_returns_openai_compatible_adapter_for_that_provider(monkeypatch):
    monkeypatch.setattr("core.llm_adapters.AsyncOpenAI", lambda **kwargs: SimpleNamespace())
    adapter = create_adapter("openai-compatible", api_key="k", base_url=None, timeout=60, model="gpt-test")
    assert isinstance(adapter, OpenAICompatibleAdapter)


import json
from unittest.mock import Mock

from core.llm_adapters import AnthropicAdapter


def _fake_anthropic_message(text, *, tool_use_blocks=None):
    blocks = [SimpleNamespace(type="text", text=text)]
    if tool_use_blocks:
        blocks += tool_use_blocks
    usage = SimpleNamespace(input_tokens=20, output_tokens=8)
    return SimpleNamespace(content=blocks, usage=usage)


class _FakeAnthropicStream:
    def __init__(self, chunks, final_usage):
        self._chunks = chunks
        self._final_usage = final_usage

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def _iter_text(self):
        for chunk in self._chunks:
            yield chunk

    @property
    def text_stream(self):
        return self._iter_text()

    async def get_final_message(self):
        return SimpleNamespace(usage=self._final_usage)


async def test_anthropic_adapter_ainvoke_parses_text_content_and_splits_system_message(monkeypatch):
    fake_response = _fake_anthropic_message("hello from claude")
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    monkeypatch.setattr("core.llm_adapters.AsyncAnthropic", lambda **kwargs: fake_client)

    adapter = AnthropicAdapter(api_key="k", base_url=None, timeout=60, model="claude-test")
    result = await adapter.ainvoke([{"role": "system", "content": "be nice"}, {"role": "user", "content": "hi"}])

    assert result.content == "hello from claude"
    assert result.usage == {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28}
    _, kwargs = fake_client.messages.create.call_args
    assert kwargs["system"] == "be nice"
    assert kwargs["messages"] == [{"role": "user", "content": "hi"}]


async def test_anthropic_adapter_ainvoke_with_tools_parses_tool_use_blocks(monkeypatch):
    tool_block = SimpleNamespace(type="tool_use", id="call_1", name="search", input={"q": "x"})
    fake_response = _fake_anthropic_message("", tool_use_blocks=[tool_block])
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    monkeypatch.setattr("core.llm_adapters.AsyncAnthropic", lambda **kwargs: fake_client)

    adapter = AnthropicAdapter(api_key="k", base_url=None, timeout=60, model="claude-test")
    result = await adapter.ainvoke_with_tools([{"role": "user", "content": "hi"}], tools=[{"name": "search"}])

    assert result.content is None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "search"
    assert json.loads(result.tool_calls[0].arguments) == {"q": "x"}


async def test_anthropic_adapter_astream_invoke_yields_text_chunks(monkeypatch):
    fake_stream = _FakeAnthropicStream(["he", "llo"], SimpleNamespace(input_tokens=1, output_tokens=2))
    fake_client = SimpleNamespace(messages=SimpleNamespace(stream=Mock(return_value=fake_stream)))
    monkeypatch.setattr("core.llm_adapters.AsyncAnthropic", lambda **kwargs: fake_client)

    adapter = AnthropicAdapter(api_key="k", base_url=None, timeout=60, model="claude-test")
    chunks = [chunk async for chunk in adapter.astream_invoke([{"role": "user", "content": "hi"}])]

    assert chunks == ["he", "llo"]
    assert adapter.last_stats.usage == {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}


def test_create_adapter_returns_anthropic_adapter_for_that_provider(monkeypatch):
    monkeypatch.setattr("core.llm_adapters.AsyncAnthropic", lambda **kwargs: SimpleNamespace())
    adapter = create_adapter("anthropic", api_key="k", base_url=None, timeout=60, model="claude-test")
    assert isinstance(adapter, AnthropicAdapter)
