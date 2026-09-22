import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.completion import Completion
from core.errors import SettingsError
from core.model_backends import ClaudeBackend, FakeModelBackend, OpenAICompatibleBackend, create_model_backend


async def test_fake_backend_acomplete_returns_configured_response():
    backend = FakeModelBackend(model_name="mock-model", response=Completion(text="hi there", model_id="mock-model"))
    result = await backend.acomplete([{"role": "user", "content": "hello"}])
    assert result.text == "hi there"


async def test_fake_backend_acomplete_uses_responder_when_given():
    def responder(messages):
        return Completion(text=f"echo: {messages[-1]['content']}", model_id="mock-model")

    backend = FakeModelBackend(model_name="mock-model", responder=responder)
    result = await backend.acomplete([{"role": "user", "content": "hello"}])
    assert result.text == "echo: hello"


async def test_fake_backend_acomplete_defaults_to_empty_text_when_unconfigured():
    backend = FakeModelBackend(model_name="mock-model")
    result = await backend.acomplete([{"role": "user", "content": "hello"}])
    assert result.text == ""


async def test_fake_backend_astream_yields_response_text_character_by_character():
    backend = FakeModelBackend(model_name="mock-model", response=Completion(text="ab", model_id="mock-model"))
    chunks = [chunk async for chunk in backend.astream([{"role": "user", "content": "hi"}])]
    assert chunks == ["a", "b"]
    assert backend.last_stream_summary is not None


async def test_fake_backend_acomplete_with_tools_returns_no_requested_tools():
    backend = FakeModelBackend(model_name="mock-model", response=Completion(text="hi", model_id="mock-model"))
    result = await backend.acomplete_with_tools([{"role": "user", "content": "hi"}], tools=[])
    assert result.requested_tools == []
    assert result.text == "hi"


async def test_fake_backend_astream_with_tools_forwards_deltas_and_returns_full_text():
    backend = FakeModelBackend(model_name="mock-model", response=Completion(text="ab", model_id="mock-model"))
    seen: list[str] = []

    async def on_text_delta(chunk: str) -> None:
        seen.append(chunk)

    result = await backend.astream_with_tools([{"role": "user", "content": "hi"}], tools=[], on_text_delta=on_text_delta)

    assert seen == ["a", "b"]
    assert result.text == "ab"
    assert result.requested_tools == []


def test_create_model_backend_returns_fake_backend_for_mock_provider():
    backend = create_model_backend("mock", api_key="mock", base_url=None, timeout=60, model_name="mock-model")
    assert isinstance(backend, FakeModelBackend)


def test_create_model_backend_rejects_unknown_provider():
    with pytest.raises(SettingsError, match="Unknown MODEL_PROVIDER"):
        create_model_backend("does-not-exist", api_key="k", base_url=None, timeout=60, model_name="m")


def _fake_openai_response(content, *, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


async def test_openai_compatible_backend_acomplete_parses_text_and_usage(monkeypatch):
    fake_response = _fake_openai_response("hello there")
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    )
    monkeypatch.setattr("core.model_backends.AsyncOpenAI", lambda **kwargs: fake_client)

    backend = OpenAICompatibleBackend(api_key="k", base_url=None, timeout=60, model_name="gpt-test")
    result = await backend.acomplete([{"role": "user", "content": "hi"}])

    assert result.text == "hello there"
    assert result.token_usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    fake_client.chat.completions.create.assert_awaited_once()


async def test_openai_compatible_backend_acomplete_with_tools_parses_requested_tools(monkeypatch):
    tool_call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="search", arguments='{"q": "x"}'))
    fake_response = _fake_openai_response(None, tool_calls=[tool_call])
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    )
    monkeypatch.setattr("core.model_backends.AsyncOpenAI", lambda **kwargs: fake_client)

    backend = OpenAICompatibleBackend(api_key="k", base_url=None, timeout=60, model_name="gpt-test")
    result = await backend.acomplete_with_tools(
        [{"role": "user", "content": "hi"}], tools=[{"type": "function", "function": {"name": "search"}}]
    )

    assert len(result.requested_tools) == 1
    assert result.requested_tools[0].tool_name == "search"
    assert result.requested_tools[0].arguments_json == '{"q": "x"}'


async def test_openai_compatible_backend_astream_yields_delta_text(monkeypatch):
    async def fake_stream():
        for text in ["hel", "lo"]:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=fake_stream())))
    )
    monkeypatch.setattr("core.model_backends.AsyncOpenAI", lambda **kwargs: fake_client)

    backend = OpenAICompatibleBackend(api_key="k", base_url=None, timeout=60, model_name="gpt-test")
    chunks = [chunk async for chunk in backend.astream([{"role": "user", "content": "hi"}])]
    assert chunks == ["hel", "lo"]
    assert backend.last_stream_summary is not None


async def test_openai_compatible_backend_astream_with_tools_forwards_text_and_accumulates_tool_calls(monkeypatch):
    def _tool_call_delta(*, index, call_id=None, name=None, arguments=None):
        function = SimpleNamespace(name=name, arguments=arguments) if (name or arguments) else None
        return SimpleNamespace(index=index, id=call_id, function=function)

    async def fake_stream():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="hel", tool_calls=None))])
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[_tool_call_delta(index=0, call_id="call_1", name="search", arguments='{"q":')],
                    )
                )
            ]
        )
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[_tool_call_delta(index=0, arguments='"x"}')])
                )
            ]
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=fake_stream())))
    )
    monkeypatch.setattr("core.model_backends.AsyncOpenAI", lambda **kwargs: fake_client)

    backend = OpenAICompatibleBackend(api_key="k", base_url=None, timeout=60, model_name="gpt-test")
    seen: list[str] = []

    async def on_text_delta(chunk: str) -> None:
        seen.append(chunk)

    result = await backend.astream_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "search"}}],
        on_text_delta=on_text_delta,
    )

    assert seen == ["hel"]
    assert result.text == "hel"
    assert len(result.requested_tools) == 1
    assert result.requested_tools[0].call_id == "call_1"
    assert result.requested_tools[0].tool_name == "search"
    assert result.requested_tools[0].arguments_json == '{"q":"x"}'


def test_create_model_backend_returns_openai_compatible_backend_for_that_provider(monkeypatch):
    monkeypatch.setattr("core.model_backends.AsyncOpenAI", lambda **kwargs: SimpleNamespace())
    backend = create_model_backend("openai-compatible", api_key="k", base_url=None, timeout=60, model_name="gpt-test")
    assert isinstance(backend, OpenAICompatibleBackend)


def _fake_claude_message(text, *, tool_use_blocks=None):
    blocks = [SimpleNamespace(type="text", text=text)]
    if tool_use_blocks:
        blocks += tool_use_blocks
    usage = SimpleNamespace(input_tokens=20, output_tokens=8)
    return SimpleNamespace(content=blocks, usage=usage)


class _FakeClaudeStream:
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


async def test_claude_backend_acomplete_parses_text_and_splits_system_message(monkeypatch):
    fake_response = _fake_claude_message("hello from claude")
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    monkeypatch.setattr("core.model_backends.AsyncAnthropic", lambda **kwargs: fake_client)

    backend = ClaudeBackend(api_key="k", base_url=None, timeout=60, model_name="claude-test")
    result = await backend.acomplete([{"role": "system", "content": "be nice"}, {"role": "user", "content": "hi"}])

    assert result.text == "hello from claude"
    assert result.token_usage == {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28}
    _, kwargs = fake_client.messages.create.call_args
    assert kwargs["system"] == "be nice"
    assert kwargs["messages"] == [{"role": "user", "content": "hi"}]


async def test_claude_backend_acomplete_with_tools_parses_tool_use_blocks(monkeypatch):
    tool_block = SimpleNamespace(type="tool_use", id="call_1", name="search", input={"q": "x"})
    fake_response = _fake_claude_message("", tool_use_blocks=[tool_block])
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    monkeypatch.setattr("core.model_backends.AsyncAnthropic", lambda **kwargs: fake_client)

    backend = ClaudeBackend(api_key="k", base_url=None, timeout=60, model_name="claude-test")
    result = await backend.acomplete_with_tools([{"role": "user", "content": "hi"}], tools=[{"name": "search"}])

    assert result.text is None
    assert len(result.requested_tools) == 1
    assert result.requested_tools[0].tool_name == "search"
    assert json.loads(result.requested_tools[0].arguments_json) == {"q": "x"}


async def test_claude_backend_astream_yields_text_chunks(monkeypatch):
    fake_stream = _FakeClaudeStream(["he", "llo"], SimpleNamespace(input_tokens=1, output_tokens=2))
    fake_client = SimpleNamespace(messages=SimpleNamespace(stream=Mock(return_value=fake_stream)))
    monkeypatch.setattr("core.model_backends.AsyncAnthropic", lambda **kwargs: fake_client)

    backend = ClaudeBackend(api_key="k", base_url=None, timeout=60, model_name="claude-test")
    chunks = [chunk async for chunk in backend.astream([{"role": "user", "content": "hi"}])]

    assert chunks == ["he", "llo"]
    assert backend.last_stream_summary.token_usage == {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}


async def test_claude_backend_astream_with_tools_forwards_text_and_parses_tool_use_from_final_message(monkeypatch):
    tool_block = SimpleNamespace(type="tool_use", id="call_1", name="search", input={"q": "x"})
    final_message = _fake_claude_message("hello", tool_use_blocks=[tool_block])
    fake_stream = _FakeClaudeStream(["he", "llo"], final_message.usage)
    fake_stream.get_final_message = AsyncMock(return_value=final_message)
    fake_client = SimpleNamespace(messages=SimpleNamespace(stream=Mock(return_value=fake_stream)))
    monkeypatch.setattr("core.model_backends.AsyncAnthropic", lambda **kwargs: fake_client)

    backend = ClaudeBackend(api_key="k", base_url=None, timeout=60, model_name="claude-test")
    seen: list[str] = []

    async def on_text_delta(chunk: str) -> None:
        seen.append(chunk)

    result = await backend.astream_with_tools(
        [{"role": "user", "content": "hi"}], tools=[{"name": "search"}], on_text_delta=on_text_delta
    )

    assert seen == ["he", "llo"]
    assert result.text == "hello"
    assert len(result.requested_tools) == 1
    assert result.requested_tools[0].tool_name == "search"
    assert json.loads(result.requested_tools[0].arguments_json) == {"q": "x"}


def test_create_model_backend_returns_claude_backend_for_anthropic_provider(monkeypatch):
    monkeypatch.setattr("core.model_backends.AsyncAnthropic", lambda **kwargs: SimpleNamespace())
    backend = create_model_backend("anthropic", api_key="k", base_url=None, timeout=60, model_name="claude-test")
    assert isinstance(backend, ClaudeBackend)
