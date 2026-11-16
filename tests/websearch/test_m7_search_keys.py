from pathlib import Path

import httpx
import pytest

from websearch.key_rotation import (
    RotatingTavilyClient,
    SearchKeyStore,
    SearchKeysExhaustedError,
)


def test_search_keys_rotate_mask_and_cool_down(tmp_path: Path) -> None:
    store = SearchKeyStore(tmp_path / "search.db")
    first = store.add_key(provider="tavily", name="Primary", api_key="tvly-first-secret")
    second = store.add_key(provider="tavily", name="Backup", api_key="tvly-second-secret")

    assert "api_key" not in store.list_keys()[0]
    assert store.select_key("tavily")["id"] == first["id"]
    assert store.select_key("tavily")["id"] == second["id"]
    assert store.select_key("tavily")["id"] == first["id"]

    store.mark_refused(first["id"], status_code=429, cooldown_seconds=60)
    assert store.select_key("tavily")["id"] == second["id"]
    usage = store.usage(first["id"])
    assert usage["failures"] == 1
    assert usage["cooldown_until"]


@pytest.mark.asyncio
async def test_rotating_tavily_client_retries_refused_key(tmp_path: Path) -> None:
    store = SearchKeyStore(tmp_path / "search.db")
    first = store.add_key(provider="tavily", name="Primary", api_key="first")
    second = store.add_key(provider="tavily", name="Backup", api_key="second")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.headers["authorization"].removeprefix("Bearer ")
        seen.append(key)
        if key == "first":
            return httpx.Response(429, json={"detail": "quota"})
        return httpx.Response(
            200,
            json={
                "query": "hello",
                "results": [
                    {
                        "title": "Result",
                        "url": "https://example.com",
                        "content": "ok",
                        "score": 1.0,
                    }
                ],
            },
        )

    client = RotatingTavilyClient(
        store,
        provider="tavily",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    response = await client.search("hello")

    assert response.results[0].title == "Result"
    assert seen == ["first", "second"]
    assert store.usage(first["id"])["cooldown_until"]
    assert store.usage(second["id"])["successes"] == 1


@pytest.mark.asyncio
async def test_rotating_tavily_client_reports_exhaustion(tmp_path: Path) -> None:
    store = SearchKeyStore(tmp_path / "search.db")
    store.add_key(provider="tavily", name="Only", api_key="first")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"detail": "quota"})

    client = RotatingTavilyClient(
        store,
        provider="tavily",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(SearchKeysExhaustedError):
        await client.search("hello")
