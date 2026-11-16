"""Filtered, size-limited, privacy-masked web fetching."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

from privacy.engine import PrivacyEngine
from tool.outcome import ToolOutcome
from tool.tool import Tool, ToolParameter


class WebFetchError(RuntimeError):
    pass


class WebFetchService:
    def __init__(
        self,
        *,
        privacy: PrivacyEngine,
        max_bytes: int = 512_000,
        timeout_seconds: float = 20.0,
        http_get: Callable[[httpx.Request], Any] | None = None,
        resolver: Callable[[str, int], list[tuple]] | None = None,
    ) -> None:
        self.privacy = privacy
        self.max_bytes = max(1, max_bytes)
        self.timeout_seconds = timeout_seconds
        self._http_get = http_get
        self._resolver = resolver or socket.getaddrinfo

    async def fetch(self, url: str, *, scope: str) -> dict[str, Any]:
        parsed = await self._validate_url(url)
        try:
            response = await self._get(url)
        except httpx.HTTPError as error:
            raise WebFetchError(f"web fetch failed: {error}") from error
        if response.status_code >= 400:
            raise WebFetchError(f"web fetch returned HTTP {response.status_code}")
        if 300 <= response.status_code < 400:
            raise WebFetchError("web fetch redirects are not followed")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type and not (
            content_type.startswith("text/")
            or content_type in {"application/json", "application/xml", "application/xhtml+xml"}
        ):
            raise WebFetchError(f"unsupported web fetch content type: {content_type}")
        content = _response_bytes(response)
        if len(content) > self.max_bytes:
            raise WebFetchError(
                f"web fetch response exceeds {self.max_bytes} byte limit"
            )
        text = content.decode(_response_encoding(response), errors="replace")
        if content_type in {"text/html", "application/xhtml+xml"} or "<html" in text[:500].lower():
            text = _HtmlTextExtractor().strip(text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        masked = self.privacy.mask_text(text, scope=scope)
        return {
            "url": str(parsed),
            "status": response.status_code,
            "content_type": content_type or "text/plain",
            "bytes": len(content),
            "text": masked.text,
            "privacy_matches": masked.matches,
        }

    async def _get(self, url: str):
        if self._http_get is not None:
            result = self._http_get(httpx.Request("GET", url))
            if asyncio.iscoroutine(result):
                return await result
            return result
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=False,
        ) as client:
            return await client.get(url)

    async def _validate_url(self, url: str):
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise WebFetchError("web fetch only supports http and https URLs")
        host = parsed.hostname.strip().lower()
        if host == "localhost" or host.endswith(".localhost"):
            raise WebFetchError("web fetch cannot access localhost")
        try:
            addresses = await asyncio.to_thread(
                self._resolver,
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
            )
        except OSError as error:
            raise WebFetchError(f"cannot resolve host: {error}") from error
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                raise WebFetchError("web fetch cannot access local or private network addresses")
        return parsed


class WebFetchTool(Tool):
    def __init__(self, service: WebFetchService) -> None:
        super().__init__(
            name="web_fetch",
            description=(
                "Fetch one public HTTP(S) URL through size, content-type, network, "
                "and privacy filters."
            ),
            untrusted_output=True,
        )
        self.service = service

    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter("url", "string", "Public URL to fetch."),
            ToolParameter(
                "scope",
                "string",
                "Privacy placeholder scope.",
                required=False,
            ),
        ]

    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
        try:
            result = await self.service.fetch(
                arguments["url"],
                scope=arguments.get("scope", "web-fetch"),
            )
        except WebFetchError as error:
            return ToolOutcome.error(str(error))
        return ToolOutcome.ok(result["text"])


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript"}:
            self._hidden_depth += 1
        if tag in {"p", "div", "h1", "h2", "h3", "li", "br"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._hidden_depth:
            self._hidden_depth -= 1
        if tag in {"p", "div", "h1", "h2", "h3", "li"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self._parts.append(data)

    def strip(self, html: str) -> str:
        self.feed(html)
        self.close()
        return "".join(self._parts)


def _response_bytes(response) -> bytes:
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return content
    text = getattr(response, "text", "")
    return str(text).encode("utf-8")


def _response_encoding(response) -> str:
    headers = getattr(response, "headers", {})
    content_type = headers.get("content-type", "")
    match = re.search(r"charset=([\w.-]+)", content_type, re.IGNORECASE)
    return match.group(1) if match else "utf-8"
