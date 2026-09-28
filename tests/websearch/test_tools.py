import json

import httpx

from tool.outcome import OutcomeStatus
from websearch.client import TavilyClient
from websearch.tools import WebSearchTool


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
