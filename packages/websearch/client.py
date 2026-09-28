import httpx
from pydantic import ValidationError

from .models import ExtractResponse, SearchResponse

DEFAULT_TIMEOUT_SECONDS = 30.0
_BASE_URL = "https://api.tavily.com"


class WebSearchServiceError(RuntimeError):
    """Tavily 不可达或返回了错误。message 面向调用方，可能原样喂给模型。"""


class TavilyClient:
    """Tavily search/extract REST API 的异步 HTTP 客户端。

    测试可以通过 client 参数注入一个自定义 httpx.AsyncClient（如 MockTransport），
    不依赖真实网络。认证走每次请求的 Authorization: Bearer 头——Tavily 早期支持把
    api_key 放进请求体，该方式已弃用，部分新账号的 key 会直接拒绝。
    """

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def search(self, query: str, *, max_results: int = 5) -> SearchResponse:
        data = await self._request("/search", {"query": query, "max_results": max_results})
        try:
            return SearchResponse.model_validate(data)
        except ValidationError as error:
            raise WebSearchServiceError(f"Unexpected search response shape: {error}") from error

    async def extract(self, urls: list[str]) -> ExtractResponse:
        data = await self._request("/extract", {"urls": urls})
        try:
            return ExtractResponse.model_validate(data)
        except ValidationError as error:
            raise WebSearchServiceError(f"Unexpected extract response shape: {error}") from error

    async def _request(self, path: str, json_body: dict) -> dict:
        try:
            response = await self._client.post(
                f"{_BASE_URL}{path}",
                json=json_body,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.HTTPError as error:
            raise WebSearchServiceError(f"Tavily is unreachable: {error}") from error
        if response.status_code >= 400:
            detail = None
            if response.headers.get("content-type", "").startswith("application/json"):
                body = response.json()
                detail = body.get("detail")
                if isinstance(detail, dict):
                    detail = detail.get("error")
            raise WebSearchServiceError(str(detail or response.text))
        return response.json()
