import pytest

from providers.factory import create_provider_from_env
from providers.mock_provider import MockProvider


def test_returns_mock_provider_when_MODEL_PROVIDER_is_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    provider = create_provider_from_env()
    assert isinstance(provider, MockProvider)


def test_raises_when_MODEL_PROVIDER_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    with pytest.raises(RuntimeError, match="MODEL_PROVIDER"):
        create_provider_from_env()


def test_raises_when_MODEL_PROVIDER_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "not-a-real-provider")
    with pytest.raises(RuntimeError, match="Unknown MODEL_PROVIDER"):
        create_provider_from_env()


def test_raises_when_anthropic_selected_without_MODEL_API_KEY(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "anthropic")
    monkeypatch.setenv("MODEL_NAME", "claude-test")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MODEL_API_KEY"):
        create_provider_from_env()


def test_raises_when_ollama_selected_without_MODEL_BASE_URL(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("MODEL_NAME", "llama3")
    monkeypatch.delenv("MODEL_BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="MODEL_BASE_URL"):
        create_provider_from_env()
