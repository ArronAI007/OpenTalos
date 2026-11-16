import pytest

from privacy.engine import PrivacyEngine
from privacy.store import PrivacyStore
from websearch.fetch import WebFetchError, WebFetchService


def _public_resolver(_host, _port):
    return [(None, None, None, "", ("93.184.216.34", 443))]


@pytest.mark.asyncio
async def test_web_fetch_limits_size_strips_html_and_redacts(tmp_path) -> None:
    def handler(_request):
        return type(
            "Response",
            (),
            {
                "status_code": 200,
                "headers": {"content-type": "text/html; charset=utf-8"},
                "text": "<html><body><h1>Hello</h1><p>alice@example.com</p></body></html>",
                "content": b"<html><body><h1>Hello</h1><p>alice@example.com</p></body></html>",
            },
        )()

    privacy = PrivacyEngine(PrivacyStore(tmp_path / "privacy.db"))
    service = WebFetchService(
        privacy=privacy,
        http_get=handler,
        max_bytes=1024,
        resolver=_public_resolver,
    )

    result = await service.fetch("https://example.com/page", scope="thread")

    assert "Hello" in result["text"]
    assert "<h1>" not in result["text"]
    assert "alice@example.com" not in result["text"]
    assert "OPENTALOS_EMAIL" in result["text"]


@pytest.mark.asyncio
async def test_web_fetch_blocks_local_and_private_targets(tmp_path) -> None:
    service = WebFetchService(
        privacy=PrivacyEngine(PrivacyStore(tmp_path / "privacy.db")),
    )

    for url in (
        "http://localhost:8080/admin",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "file:///etc/passwd",
    ):
        with pytest.raises(WebFetchError):
            await service.fetch(url, scope="thread")


@pytest.mark.asyncio
async def test_web_fetch_rejects_oversized_and_non_text_content(tmp_path) -> None:
    service = WebFetchService(
        privacy=PrivacyEngine(PrivacyStore(tmp_path / "privacy.db")),
        max_bytes=10,
        http_get=lambda _request: type(
            "Response",
            (),
            {
                "status_code": 200,
                "headers": {"content-type": "application/octet-stream"},
                "text": "",
                "content": b"x" * 20,
            },
        )(),
        resolver=_public_resolver,
    )
    with pytest.raises(WebFetchError, match="content type"):
        await service.fetch("https://example.com/file", scope="thread")
