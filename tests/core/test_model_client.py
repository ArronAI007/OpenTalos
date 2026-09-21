import pytest

from core.completion import Completion
from core.errors import SettingsError
from core.model_backends import FakeModelBackend
from core.model_client import ModelClient


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
