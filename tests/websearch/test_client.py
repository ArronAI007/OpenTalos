import json

import httpx
import pytest

from websearch.client import TavilyClient, WebSearchServiceError


def _build_client(handler) -> TavilyClient:
    return TavilyClient("tvly-test", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_search_returns_parsed_results():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        assert request.headers["authorization"] == "Bearer tvly-test"
        return httpx.Response(
            200,
            json={
                "query": "leo messi",
                "results": [
                    {"title": "Leo Messi - Wikipedia", "url": "https://en.wikipedia.org/wiki/Lionel_Messi",
                     "content": "Argentine footballer.", "score": 0.9},
                ],
            },
        )

    response = await _build_client(handler).search("leo messi")

    assert response.query == "leo messi"
    assert response.results[0].title == "Leo Messi - Wikipedia"
    assert response.results[0].url == "https://en.wikipedia.org/wiki/Lionel_Messi"


async def test_search_sends_the_query_and_max_results_in_the_body():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"query": "x", "results": []})

    await _build_client(handler).search("x", max_results=3)

    assert captured == {"query": "x", "max_results": 3}


async def test_search_http_error_raises_service_error_with_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": {"error": "Invalid API key."}})

    with pytest.raises(WebSearchServiceError, match="Invalid API key"):
        await _build_client(handler).search("x")


async def test_an_unreachable_service_raises_a_clear_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(WebSearchServiceError, match="unreachable"):
        await _build_client(handler).search("x")


async def test_extract_returns_parsed_pages():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/extract"
        assert json.loads(request.content) == {"urls": ["https://example.com/a"]}
        return httpx.Response(
            200,
            json={
                "results": [{"url": "https://example.com/a", "raw_content": "Full article text."}],
                "failed_results": [],
            },
        )

    response = await _build_client(handler).extract(["https://example.com/a"])

    assert response.results[0].url == "https://example.com/a"
    assert response.results[0].raw_content == "Full article text."
    assert response.failed_results == []


async def test_extract_reports_partial_failures_alongside_successes():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [{"url": "https://example.com/ok", "raw_content": "ok content"}],
                "failed_results": [{"url": "https://example.com/bad", "error": "Timeout while fetching."}],
            },
        )

    response = await _build_client(handler).extract(["https://example.com/ok", "https://example.com/bad"])

    assert len(response.results) == 1
    assert len(response.failed_results) == 1
    assert response.failed_results[0].error == "Timeout while fetching."


async def test_extract_http_error_raises_service_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(432, json={"detail": {"error": "URL is not crawlable."}})

    with pytest.raises(WebSearchServiceError, match="not crawlable"):
        await _build_client(handler).extract(["https://example.com/blocked"])
