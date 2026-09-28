from typing import Any

from tool.outcome import ToolOutcome
from tool.tool import Tool, ToolParameter

from .client import TavilyClient, WebSearchServiceError
from .models import ExtractResponse, ExtractedPage, SearchResponse

DEFAULT_MAX_RESULTS = 5
MAX_EXTRACT_CHARS = 8000


class WebSearchTool(Tool):
    """联网搜索，返回标题/链接/摘要列表。深入某条结果时配合 web_extractor 抓正文。"""

    def __init__(self, client: TavilyClient) -> None:
        super().__init__(
            name="web_search",
            description=(
                "Search the web for up-to-date information. Returns a numbered list of "
                "results (title, url, snippet). Use web_extractor to read a result's full "
                "page content."
            ),
        )
        self._client = client

    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(name="query", type="string", description="The search query."),
            ToolParameter(
                name="max_results",
                type="integer",
                description="Maximum number of results to return.",
                required=False,
            ),
        ]

    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
        try:
            response = await self._client.search(
                arguments["query"], max_results=arguments.get("max_results", DEFAULT_MAX_RESULTS)
            )
        except WebSearchServiceError as error:
            return ToolOutcome.error(str(error))
        return ToolOutcome.ok(_render_search(response))


def _render_search(response: SearchResponse) -> str:
    if not response.results:
        return "No results found for the given query."
    blocks = [
        f"{index}. {result.title}\n   URL: {result.url}\n   {result.content}"
        for index, result in enumerate(response.results, start=1)
    ]
    return "\n\n".join(blocks)


class WebExtractorTool(Tool):
    """抓取指定网页的正文，配合 web_search 定位到具体链接后使用。"""

    def __init__(self, client: TavilyClient) -> None:
        super().__init__(
            name="web_extractor",
            description=(
                "Fetch the full page content of one or more URLs, typically ones found via "
                "web_search. Long pages are truncated."
            ),
        )
        self._client = client

    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="urls", type="array", description="URLs to extract content from.", items="string"
            ),
        ]

    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
        try:
            response = await self._client.extract(arguments["urls"])
        except WebSearchServiceError as error:
            return ToolOutcome.error(str(error))
        return ToolOutcome.ok(_render_extract(response))


def _render_extract(response: ExtractResponse) -> str:
    blocks = [_render_page(page) for page in response.results]
    blocks += [
        f"## {failure.url} (extraction failed)\n{failure.error}" for failure in response.failed_results
    ]
    if not blocks:
        return "No content could be extracted from the given URLs."
    return "\n\n".join(blocks)


def _render_page(page: ExtractedPage) -> str:
    content = page.raw_content
    if len(content) > MAX_EXTRACT_CHARS:
        content = content[:MAX_EXTRACT_CHARS] + "…(内容已截断)"
    return f"## {page.url}\n{content}"
