import json

import httpx

from tool.outcome import OutcomeStatus
from websearch.client import TavilyClient
from websearch.tools import WebExtractorTool, WebSearchTool


def _build_client(handler) -> TavilyClient:
    return TavilyClient("tvly-test", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _search_handler(request: httpx.Request) -> httpx.Response:
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


async def test_web_search_renders_a_numbered_list():
    tool = WebSearchTool(_build_client(_search_handler))

    outcome = await tool.acall({"query": "leo messi"})

    assert outcome.status is OutcomeStatus.OK
    assert "1. Leo Messi - Wikipedia" in outcome.output
    assert "https://en.wikipedia.org/wiki/Lionel_Messi" in outcome.output
    assert "Argentine footballer." in outcome.output


async def test_web_search_reports_no_results():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"query": "x", "results": []})

    tool = WebSearchTool(_build_client(handler))

    outcome = await tool.acall({"query": "x"})

    assert outcome.status is OutcomeStatus.OK
    assert outcome.output == "No results found for the given query."


async def test_web_search_defaults_max_results_to_five():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"query": "x", "results": []})

    tool = WebSearchTool(_build_client(handler))
    await tool.acall({"query": "x"})

    assert captured["max_results"] == 5


async def test_web_search_turns_a_service_error_into_an_error_outcome():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    tool = WebSearchTool(_build_client(handler))

    outcome = await tool.acall({"query": "x"})

    assert outcome.status is OutcomeStatus.ERROR
    assert "unreachable" in outcome.output


def test_web_search_schema_makes_query_required_and_max_results_optional():
    schema = WebSearchTool(_build_client(_search_handler)).to_function_schema()

    properties = schema["function"]["parameters"]["properties"]
    assert properties["query"]["type"] == "string"
    assert properties["max_results"]["type"] == "integer"
    assert schema["function"]["parameters"]["required"] == ["query"]


def _extract_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "results": [{"url": "https://example.com/a", "raw_content": "Full article text."}],
            "failed_results": [],
        },
    )


async def test_web_extractor_renders_page_content():
    tool = WebExtractorTool(_build_client(_extract_handler))

    outcome = await tool.acall({"urls": ["https://example.com/a"]})

    assert outcome.status is OutcomeStatus.OK
    assert "## https://example.com/a" in outcome.output
    assert "Full article text." in outcome.output


async def test_web_extractor_truncates_long_pages():
    long_content = "x" * 9000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"url": "https://example.com/a", "raw_content": long_content}], "failed_results": []},
        )

    tool = WebExtractorTool(_build_client(handler))

    outcome = await tool.acall({"urls": ["https://example.com/a"]})

    assert len(outcome.output) < 9000
    assert "内容已截断" in outcome.output


async def test_web_extractor_lists_failures_alongside_successes():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [{"url": "https://example.com/ok", "raw_content": "ok content"}],
                "failed_results": [{"url": "https://example.com/bad", "error": "Timeout while fetching."}],
            },
        )

    tool = WebExtractorTool(_build_client(handler))

    outcome = await tool.acall({"urls": ["https://example.com/ok", "https://example.com/bad"]})

    assert outcome.status is OutcomeStatus.OK
    assert "ok content" in outcome.output
    assert "https://example.com/bad (extraction failed)" in outcome.output
    assert "Timeout while fetching." in outcome.output


async def test_web_extractor_turns_a_service_error_into_an_error_outcome():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    tool = WebExtractorTool(_build_client(handler))

    outcome = await tool.acall({"urls": ["https://example.com/a"]})

    assert outcome.status is OutcomeStatus.ERROR
    assert "unreachable" in outcome.output


def test_web_extractor_schema_types_urls_as_a_required_string_array():
    schema = WebExtractorTool(_build_client(_extract_handler)).to_function_schema()

    properties = schema["function"]["parameters"]["properties"]
    assert properties["urls"]["type"] == "array"
    assert properties["urls"]["items"] == {"type": "string"}
    assert schema["function"]["parameters"]["required"] == ["urls"]
