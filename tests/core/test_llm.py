import pytest

from core.exceptions import ConfigError
from core.llm import LLMClient
from core.llm_adapters import MockAdapter
from core.llm_response import LLMResponse


def test_llm_client_requires_provider(monkeypatch):
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    with pytest.raises(ConfigError, match="provider"):
        LLMClient()


def test_llm_client_requires_model_and_api_key_for_non_mock_provider(monkeypatch):
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="模型名称"):
        LLMClient(provider="openai-compatible")


def test_llm_client_mock_provider_needs_no_model_or_api_key():
    client = LLMClient(provider="mock")
    assert isinstance(client._adapter, MockAdapter)


def test_llm_client_defaults_timeout_to_60_seconds(monkeypatch):
    monkeypatch.delenv("MODEL_TIMEOUT", raising=False)
    client = LLMClient(provider="mock")
    assert client.timeout == 60


async def test_llm_client_ainvoke_delegates_to_adapter():
    client = LLMClient(provider="mock")
    client._adapter = MockAdapter(model="mock-model", response=LLMResponse(content="hi", model="mock-model"))
    result = await client.ainvoke([{"role": "user", "content": "hello"}])
    assert result.content == "hi"


async def test_llm_client_astream_invoke_updates_last_call_stats():
    client = LLMClient(provider="mock")
    client._adapter = MockAdapter(model="mock-model", response=LLMResponse(content="ab", model="mock-model"))
    chunks = [chunk async for chunk in client.astream_invoke([{"role": "user", "content": "hi"}])]
    assert chunks == ["a", "b"]
    assert client.last_call_stats is not None


def test_llm_client_invoke_sync_wrapper_matches_async_result():
    client = LLMClient(provider="mock")
    client._adapter = MockAdapter(model="mock-model", response=LLMResponse(content="hi", model="mock-model"))
    result = client.invoke([{"role": "user", "content": "hello"}])
    assert result.content == "hi"


def test_llm_client_stream_invoke_sync_wrapper_yields_chunks():
    client = LLMClient(provider="mock")
    client._adapter = MockAdapter(model="mock-model", response=LLMResponse(content="ab", model="mock-model"))
    chunks = list(client.stream_invoke([{"role": "user", "content": "hello"}]))
    assert chunks == ["a", "b"]


def test_llm_client_invoke_with_tools_sync_wrapper_matches_async_result():
    client = LLMClient(provider="mock")
    client._adapter = MockAdapter(model="mock-model", response=LLMResponse(content="hi", model="mock-model"))
    result = client.invoke_with_tools([{"role": "user", "content": "hello"}], tools=[])
    assert result.content == "hi"
