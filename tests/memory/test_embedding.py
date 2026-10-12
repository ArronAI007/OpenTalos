from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from memory.embedding import EmbeddingClient


def _fake_embedding_response(vector: list[float]):
    return SimpleNamespace(data=[SimpleNamespace(embedding=vector)])


async def test_embed_returns_the_vector_from_the_api_response(monkeypatch) -> None:
    fake_response = _fake_embedding_response([0.1, 0.2, 0.3])
    fake_client = SimpleNamespace(embeddings=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    monkeypatch.setattr("memory.embedding.AsyncOpenAI", lambda **kwargs: fake_client)

    client = EmbeddingClient(model_name="text-embedding-3-small", api_key="test-key")
    result = await client.embed("hello")

    assert result == [0.1, 0.2, 0.3]
    fake_client.embeddings.create.assert_awaited_once_with(model="text-embedding-3-small", input="hello")


async def test_embed_reads_config_from_env_vars_by_default(monkeypatch) -> None:
    monkeypatch.setenv("EMBED_MODEL_NAME", "env-model")
    monkeypatch.setenv("EMBED_API_KEY", "env-key")
    fake_response = _fake_embedding_response([1.0])
    fake_client = SimpleNamespace(embeddings=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    monkeypatch.setattr("memory.embedding.AsyncOpenAI", lambda **kwargs: fake_client)

    client = EmbeddingClient()
    result = await client.embed("hello")

    assert result == [1.0]


async def test_embed_raises_when_model_name_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("EMBED_MODEL_NAME", raising=False)
    client = EmbeddingClient(api_key="test-key")
    with pytest.raises(RuntimeError):
        await client.embed("hello")


async def test_embed_raises_when_api_key_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("EMBED_API_KEY", raising=False)
    client = EmbeddingClient(model_name="text-embedding-3-small")
    with pytest.raises(RuntimeError):
        await client.embed("hello")


def test_construction_never_raises_even_with_no_config(monkeypatch) -> None:
    monkeypatch.delenv("EMBED_MODEL_NAME", raising=False)
    monkeypatch.delenv("EMBED_API_KEY", raising=False)
    EmbeddingClient()  # 不应该抛任何异常
