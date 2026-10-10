import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.protocol import Completion, ToolCompletion
from core.errors import ModelError, SettingsError
from core.model import (
    ClaudeBackend,
    FakeModelBackend,
    ModelClient,
    OpenAICompatibleBackend,
    _is_retryable,
    create_model_backend,
)


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


def _fake_openai_response(content, *, tool_calls=None, finish_reason=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


async def test_openai_compatible_backend_acomplete_parses_text_and_usage(monkeypatch):
    fake_response = _fake_openai_response("hello there")
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    )
    monkeypatch.setattr("core.model.AsyncOpenAI", lambda **kwargs: fake_client)

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
    monkeypatch.setattr("core.model.AsyncOpenAI", lambda **kwargs: fake_client)

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
    monkeypatch.setattr("core.model.AsyncOpenAI", lambda **kwargs: fake_client)

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
    monkeypatch.setattr("core.model.AsyncOpenAI", lambda **kwargs: fake_client)

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


async def test_openai_compatible_backend_astream_with_tools_forwards_reasoning_deltas(monkeypatch):
    # kimi-k3 这类推理模型流式先吐 reasoning_content 增量再吐 content——两条增量要分通道转发，
    # reasoning 进 on_reasoning_delta、正文进 on_text_delta，互不混淆。
    async def fake_stream():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, reasoning_content="想一"))])
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, reasoning_content="想二"))])
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, reasoning_content=None, tool_calls=None))])
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="答", reasoning_content=None, tool_calls=None))])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=fake_stream())))
    )
    monkeypatch.setattr("core.model.AsyncOpenAI", lambda **kwargs: fake_client)

    backend = OpenAICompatibleBackend(api_key="k", base_url=None, timeout=60, model_name="gpt-test")
    reasoning_seen: list[str] = []
    text_seen: list[str] = []

    async def on_text_delta(chunk: str) -> None:
        text_seen.append(chunk)

    async def on_reasoning_delta(chunk: str) -> None:
        reasoning_seen.append(chunk)

    result = await backend.astream_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "search"}}],
        on_text_delta=on_text_delta,
        on_reasoning_delta=on_reasoning_delta,
    )

    assert reasoning_seen == ["想一", "想二"]
    assert text_seen == ["答"]
    assert result.text == "答"


def test_model_client_reads_reasoning_effort_from_env(monkeypatch):
    monkeypatch.setenv("MODEL_REASONING_EFFORT", "low")
    client = ModelClient(provider="mock")
    assert client.reasoning_effort == "low"


def test_unset_reasoning_effort_is_omitted_from_the_request(monkeypatch):
    monkeypatch.delenv("MODEL_REASONING_EFFORT", raising=False)
    client = ModelClient(provider="mock")
    assert "reasoning_effort" not in client._build_call_kwargs({})


def test_configured_reasoning_effort_is_sent_and_per_call_overrides_win(monkeypatch):
    monkeypatch.delenv("MODEL_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("MODEL_TEMPERATURE", raising=False)
    client = ModelClient(provider="mock", reasoning_effort="low")
    assert client._build_call_kwargs({}) == {"reasoning_effort": "low"}
    assert client._build_call_kwargs({"reasoning_effort": "max"}) == {"reasoning_effort": "max"}


def test_create_model_backend_returns_openai_compatible_backend_for_that_provider(monkeypatch):
    monkeypatch.setattr("core.model.AsyncOpenAI", lambda **kwargs: SimpleNamespace())
    backend = create_model_backend("openai-compatible", api_key="k", base_url=None, timeout=60, model_name="gpt-test")
    assert isinstance(backend, OpenAICompatibleBackend)


def _fake_claude_message(text, *, tool_use_blocks=None, stop_reason="end_turn"):
    blocks = [SimpleNamespace(type="text", text=text)]
    if tool_use_blocks:
        blocks += tool_use_blocks
    usage = SimpleNamespace(input_tokens=20, output_tokens=8)
    return SimpleNamespace(content=blocks, usage=usage, stop_reason=stop_reason)


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
    monkeypatch.setattr("core.model.AsyncAnthropic", lambda **kwargs: fake_client)

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
    monkeypatch.setattr("core.model.AsyncAnthropic", lambda **kwargs: fake_client)

    backend = ClaudeBackend(api_key="k", base_url=None, timeout=60, model_name="claude-test")
    result = await backend.acomplete_with_tools([{"role": "user", "content": "hi"}], tools=[{"name": "search"}])

    assert result.text is None
    assert len(result.requested_tools) == 1
    assert result.requested_tools[0].tool_name == "search"
    assert json.loads(result.requested_tools[0].arguments_json) == {"q": "x"}


async def test_claude_backend_astream_yields_text_chunks(monkeypatch):
    fake_stream = _FakeClaudeStream(["he", "llo"], SimpleNamespace(input_tokens=1, output_tokens=2))
    fake_client = SimpleNamespace(messages=SimpleNamespace(stream=Mock(return_value=fake_stream)))
    monkeypatch.setattr("core.model.AsyncAnthropic", lambda **kwargs: fake_client)

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
    monkeypatch.setattr("core.model.AsyncAnthropic", lambda **kwargs: fake_client)

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
    monkeypatch.setattr("core.model.AsyncAnthropic", lambda **kwargs: SimpleNamespace())
    backend = create_model_backend("anthropic", api_key="k", base_url=None, timeout=60, model_name="claude-test")
    assert isinstance(backend, ClaudeBackend)


def test_model_client_requires_provider(monkeypatch):
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    with pytest.raises(SettingsError, match="provider"):
        ModelClient()


def test_model_client_requires_model_and_api_key_for_non_mock_provider(monkeypatch):
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(SettingsError, match="模型名称"):
        ModelClient(provider="openai-compatible")


def test_model_client_mock_provider_needs_no_model_or_api_key():
    client = ModelClient(provider="mock")
    assert isinstance(client._backend, FakeModelBackend)


def test_model_client_defaults_timeout_to_60_seconds(monkeypatch):
    monkeypatch.delenv("MODEL_TIMEOUT", raising=False)
    client = ModelClient(provider="mock")
    assert client.timeout == 60


def test_model_client_leaves_temperature_unset_when_not_configured(monkeypatch):
    monkeypatch.delenv("MODEL_TEMPERATURE", raising=False)
    client = ModelClient(provider="mock")
    assert client.temperature is None


def test_model_client_reads_temperature_from_env(monkeypatch):
    monkeypatch.setenv("MODEL_TEMPERATURE", "1")
    client = ModelClient(provider="mock")
    assert client.temperature == 1.0


def test_model_client_explicit_temperature_overrides_env(monkeypatch):
    monkeypatch.setenv("MODEL_TEMPERATURE", "1")
    client = ModelClient(provider="mock", temperature=0.2)
    assert client.temperature == 0.2


def test_unset_temperature_and_max_tokens_are_omitted_from_the_request(monkeypatch):
    monkeypatch.delenv("MODEL_TEMPERATURE", raising=False)
    monkeypatch.delenv("MODEL_REASONING_EFFORT", raising=False)
    client = ModelClient(provider="mock")
    assert client._build_call_kwargs({}) == {}


def test_configured_temperature_and_max_tokens_are_sent(monkeypatch):
    monkeypatch.delenv("MODEL_TEMPERATURE", raising=False)
    monkeypatch.delenv("MODEL_REASONING_EFFORT", raising=False)
    client = ModelClient(provider="mock", temperature=0.3, max_tokens=256)
    assert client._build_call_kwargs({}) == {"temperature": 0.3, "max_tokens": 256}


def test_per_call_overrides_win_over_the_client_defaults(monkeypatch):
    monkeypatch.delenv("MODEL_TEMPERATURE", raising=False)
    monkeypatch.delenv("MODEL_REASONING_EFFORT", raising=False)
    client = ModelClient(provider="mock", temperature=0.3)
    assert client._build_call_kwargs({"temperature": 0.9, "max_tokens": 16}) == {"temperature": 0.9, "max_tokens": 16}


async def test_model_client_acomplete_delegates_to_backend():
    client = ModelClient(provider="mock")
    client._backend = FakeModelBackend(model_name="mock-model", response=Completion(text="hi", model_id="mock-model"))
    result = await client.acomplete([{"role": "user", "content": "hello"}])
    assert result.text == "hi"


async def test_model_client_astream_updates_last_stream_summary():
    client = ModelClient(provider="mock")
    client._backend = FakeModelBackend(model_name="mock-model", response=Completion(text="ab", model_id="mock-model"))
    chunks = [chunk async for chunk in client.astream([{"role": "user", "content": "hi"}])]
    assert chunks == ["a", "b"]
    assert client.last_stream_summary is not None


async def test_model_client_astream_with_tools_delegates_to_backend_and_forwards_deltas():
    client = ModelClient(provider="mock")
    client._backend = FakeModelBackend(model_name="mock-model", response=Completion(text="ab", model_id="mock-model"))
    seen: list[str] = []

    async def on_text_delta(chunk: str) -> None:
        seen.append(chunk)

    result = await client.astream_with_tools([{"role": "user", "content": "hi"}], tools=[], on_text_delta=on_text_delta)

    assert seen == ["a", "b"]
    assert result.text == "ab"


def test_model_client_complete_sync_wrapper_matches_async_result():
    client = ModelClient(provider="mock")
    client._backend = FakeModelBackend(model_name="mock-model", response=Completion(text="hi", model_id="mock-model"))
    result = client.complete([{"role": "user", "content": "hello"}])
    assert result.text == "hi"


def test_model_client_stream_sync_wrapper_yields_chunks():
    client = ModelClient(provider="mock")
    client._backend = FakeModelBackend(model_name="mock-model", response=Completion(text="ab", model_id="mock-model"))
    chunks = list(client.stream([{"role": "user", "content": "hello"}]))
    assert chunks == ["a", "b"]


def test_model_client_complete_with_tools_sync_wrapper_matches_async_result():
    client = ModelClient(provider="mock")
    client._backend = FakeModelBackend(model_name="mock-model", response=Completion(text="hi", model_id="mock-model"))
    result = client.complete_with_tools([{"role": "user", "content": "hello"}], tools=[])
    assert result.text == "hi"


# ==================== finish_reason / 流式 usage / 资源释放 ====================


async def test_openai_backend_acomplete_captures_finish_reason(monkeypatch):
    fake_response = _fake_openai_response("partial", finish_reason="length")
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    )
    monkeypatch.setattr("core.model.AsyncOpenAI", lambda **kwargs: fake_client)

    backend = OpenAICompatibleBackend(api_key="k", base_url=None, timeout=60, model_name="gpt-test")
    result = await backend.acomplete([{"role": "user", "content": "hi"}])

    assert result.finish_reason == "length"


async def test_openai_backend_acomplete_with_tools_captures_finish_reason(monkeypatch):
    fake_response = _fake_openai_response("done", finish_reason="tool_calls")
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    )
    monkeypatch.setattr("core.model.AsyncOpenAI", lambda **kwargs: fake_client)

    backend = OpenAICompatibleBackend(api_key="k", base_url=None, timeout=60, model_name="gpt-test")
    result = await backend.acomplete_with_tools([{"role": "user", "content": "hi"}], tools=[])

    assert result.finish_reason == "tool_calls"


async def test_openai_backend_astream_captures_usage_and_finish_reason(monkeypatch):
    async def fake_stream():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="hi"), finish_reason=None)], usage=None)
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason="stop")], usage=None)
        yield SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=3, completion_tokens=4, total_tokens=7))

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=fake_stream())))
    )
    monkeypatch.setattr("core.model.AsyncOpenAI", lambda **kwargs: fake_client)

    backend = OpenAICompatibleBackend(api_key="k", base_url=None, timeout=60, model_name="gpt-test")
    chunks = [chunk async for chunk in backend.astream([{"role": "user", "content": "hi"}])]

    assert chunks == ["hi"]
    assert backend.last_stream_summary is not None
    assert backend.last_stream_summary.finish_reason == "stop"
    assert backend.last_stream_summary.token_usage == {
        "prompt_tokens": 3,
        "completion_tokens": 4,
        "total_tokens": 7,
    }


async def test_openai_backend_astream_with_tools_captures_usage_and_finish_reason(monkeypatch):
    async def fake_stream():
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="hi", tool_calls=None), finish_reason="tool_calls")],
            usage=None,
        )
        yield SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2))

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=fake_stream())))
    )
    monkeypatch.setattr("core.model.AsyncOpenAI", lambda **kwargs: fake_client)

    backend = OpenAICompatibleBackend(api_key="k", base_url=None, timeout=60, model_name="gpt-test")
    result = await backend.astream_with_tools([{"role": "user", "content": "hi"}], tools=[])

    assert result.finish_reason == "tool_calls"
    assert result.token_usage == {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}


async def test_openai_backend_falls_back_when_stream_options_are_rejected(monkeypatch):
    calls: list[dict] = []

    async def fake_stream():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="hi"), finish_reason="stop")], usage=None)

    async def create(**kwargs):
        calls.append(kwargs)
        if "stream_options" in kwargs:
            raise RuntimeError("stream_options not supported")
        return fake_stream()

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr("core.model.AsyncOpenAI", lambda **kwargs: fake_client)

    backend = OpenAICompatibleBackend(api_key="k", base_url=None, timeout=60, model_name="gpt-test")
    chunks = [chunk async for chunk in backend.astream([{"role": "user", "content": "hi"}])]

    assert chunks == ["hi"]
    assert "stream_options" in calls[0]
    assert "stream_options" not in calls[1]
    assert backend._stream_usage_enabled is False

    # 已判定不支持后，后续流式请求别再白打一次带 stream_options 的失败请求。
    [chunk async for chunk in backend.astream([{"role": "user", "content": "again"}])]
    assert all("stream_options" not in call for call in calls[2:])


async def test_claude_backend_captures_stop_reason_as_finish_reason(monkeypatch):
    fake_response = _fake_claude_message("done", stop_reason="max_tokens")
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    monkeypatch.setattr("core.model.AsyncAnthropic", lambda **kwargs: fake_client)

    backend = ClaudeBackend(api_key="k", base_url=None, timeout=60, model_name="claude-test")
    result = await backend.acomplete([{"role": "user", "content": "hi"}])

    assert result.finish_reason == "max_tokens"


async def test_openai_backend_aclose_closes_the_underlying_client(monkeypatch):
    fake_client = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr("core.model.AsyncOpenAI", lambda **kwargs: fake_client)

    backend = OpenAICompatibleBackend(api_key="k", base_url=None, timeout=60, model_name="gpt-test")
    await backend.aclose()

    fake_client.close.assert_awaited_once()


async def test_model_client_aclose_is_idempotent_and_blocks_further_calls():
    client = ModelClient(provider="mock")
    closed = {"count": 0}

    async def fake_aclose() -> None:
        closed["count"] += 1

    client._backend.aclose = fake_aclose  # type: ignore[method-assign]

    await client.aclose()
    await client.aclose()

    assert closed["count"] == 1
    with pytest.raises(ModelError, match="closed"):
        await client.acomplete([{"role": "user", "content": "hi"}])


async def test_model_client_works_as_an_async_context_manager():
    client = ModelClient(provider="mock")
    closed = {"count": 0}

    async def fake_aclose() -> None:
        closed["count"] += 1

    client._backend.aclose = fake_aclose  # type: ignore[method-assign]

    async with client as entered:
        assert entered is client

    assert closed["count"] == 1


# ==================== 瞬态错误重试 / 退避 ====================


class _RetryableError(Exception):
    def __init__(self, status_code: int, retry_after: str | None = None) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code
        if retry_after is not None:
            self.response = SimpleNamespace(headers={"retry-after": retry_after})


def test_is_retryable_classifies_transient_errors():
    assert _is_retryable(_RetryableError(429))
    assert _is_retryable(_RetryableError(500))
    assert _is_retryable(_RetryableError(503))
    assert _is_retryable(asyncio.TimeoutError())
    assert not _is_retryable(_RetryableError(400))
    assert not _is_retryable(_RetryableError(401))
    assert not _is_retryable(ValueError("nope"))


async def test_acomplete_retries_a_transient_error_then_succeeds():
    client = ModelClient(provider="mock", max_retries=3, retry_base_seconds=0)
    calls = {"n": 0}

    async def flaky(messages, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _RetryableError(429)
        return Completion(text="ok", model_id="mock")

    client._backend.acomplete = flaky  # type: ignore[method-assign]
    result = await client.acomplete([{"role": "user", "content": "hi"}])

    assert result.text == "ok"
    assert calls["n"] == 3


async def test_acomplete_does_not_retry_a_client_error():
    client = ModelClient(provider="mock", max_retries=3, retry_base_seconds=0)
    calls = {"n": 0}

    async def bad(messages, **kwargs):
        calls["n"] += 1
        raise _RetryableError(400)

    client._backend.acomplete = bad  # type: ignore[method-assign]
    with pytest.raises(_RetryableError):
        await client.acomplete([{"role": "user", "content": "hi"}])

    assert calls["n"] == 1


async def test_acomplete_reraises_after_exhausting_retries():
    client = ModelClient(provider="mock", max_retries=2, retry_base_seconds=0)
    calls = {"n": 0}

    async def always(messages, **kwargs):
        calls["n"] += 1
        raise _RetryableError(503)

    client._backend.acomplete = always  # type: ignore[method-assign]
    with pytest.raises(_RetryableError):
        await client.acomplete([{"role": "user", "content": "hi"}])

    assert calls["n"] == 3  # 首次 + 2 次重试


async def test_backoff_honours_the_retry_after_header(monkeypatch):
    client = ModelClient(provider="mock", max_retries=1, retry_base_seconds=5, retry_max_seconds=8)
    delays: list[float] = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr("core.model.asyncio.sleep", fake_sleep)
    calls = {"n": 0}

    async def flaky(messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _RetryableError(429, retry_after="2")
        return Completion(text="ok", model_id="mock")

    client._backend.acomplete = flaky  # type: ignore[method-assign]
    await client.acomplete([{"role": "user", "content": "hi"}])

    assert delays == [2.0]


async def test_astream_retries_before_the_first_chunk():
    client = ModelClient(provider="mock", max_retries=2, retry_base_seconds=0)
    calls = {"n": 0}

    async def flaky(messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _RetryableError(503)
        yield "a"
        yield "b"

    client._backend.astream = flaky  # type: ignore[method-assign]
    chunks = [chunk async for chunk in client.astream([{"role": "user", "content": "hi"}])]

    assert chunks == ["a", "b"]
    assert calls["n"] == 2


async def test_astream_does_not_retry_after_the_first_chunk():
    client = ModelClient(provider="mock", max_retries=3, retry_base_seconds=0)
    calls = {"n": 0}

    async def flaky(messages, **kwargs):
        calls["n"] += 1
        yield "a"
        raise _RetryableError(500)

    client._backend.astream = flaky  # type: ignore[method-assign]
    seen: list[str] = []
    with pytest.raises(_RetryableError):
        async for chunk in client.astream([{"role": "user", "content": "hi"}]):
            seen.append(chunk)

    assert seen == ["a"]
    assert calls["n"] == 1


async def test_astream_with_tools_retries_when_nothing_was_emitted():
    client = ModelClient(provider="mock", max_retries=2, retry_base_seconds=0)
    calls = {"n": 0}

    async def flaky(messages, tools, *, on_text_delta=None, on_reasoning_delta=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _RetryableError(503)
        return ToolCompletion(text="done", requested_tools=[], model_id="mock")

    client._backend.astream_with_tools = flaky  # type: ignore[method-assign]
    result = await client.astream_with_tools([{"role": "user", "content": "hi"}], [])

    assert result.text == "done"
    assert calls["n"] == 2


async def test_astream_with_tools_does_not_retry_after_a_delta_was_emitted():
    client = ModelClient(provider="mock", max_retries=3, retry_base_seconds=0)
    calls = {"n": 0}

    async def flaky(messages, tools, *, on_text_delta=None, on_reasoning_delta=None, **kwargs):
        calls["n"] += 1
        if on_text_delta is not None:
            await on_text_delta("partial")
        raise _RetryableError(500)

    client._backend.astream_with_tools = flaky  # type: ignore[method-assign]
    seen: list[str] = []

    async def collect(chunk: str) -> None:
        seen.append(chunk)

    with pytest.raises(_RetryableError):
        await client.astream_with_tools([{"role": "user", "content": "hi"}], [], on_text_delta=collect)

    assert seen == ["partial"]
    assert calls["n"] == 1
