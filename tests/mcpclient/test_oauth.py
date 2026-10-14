"""OAuth 客户端子集的单测：用 httpx.MockTransport 搭一个假的授权服务器（发现元数据/注册/token
端点都是固定响应，不涉及真实网络），覆盖 PKCE 流程、并发 401 去重、issuer/URL scheme 安全校验。"""
import asyncio
import json

import httpx
import pytest

from mcpclient.oauth.discovery import discover_authorization_server_metadata
from mcpclient.oauth.errors import (
    MCPOAuthAuthorizationRequiredError,
    OAuthInsecureEndpointError,
    OAuthIssuerMismatchError,
)
from mcpclient.oauth.flow import RefreshDedupAuthProvider, step_up_scope
from mcpclient.oauth.provider import MCPOAuthProvider, MemoryOAuthStateStore
from mcpclient.oauth.types import OAuthClientMetadata, parse_authorization_server_metadata

_SERVER_URL = "https://fake-mcp-server.example/mcp"
_AUTH_ORIGIN = "https://fake-mcp-server.example"


class _FakeAuthServer:
    def __init__(self) -> None:
        self.refresh_call_count = 0
        self.registered_client_id = "client-abc"

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/.well-known/oauth-protected-resource":
            return httpx.Response(404)
        if path == "/.well-known/oauth-authorization-server":
            return httpx.Response(
                200,
                json={
                    "issuer": _AUTH_ORIGIN,
                    "authorization_endpoint": f"{_AUTH_ORIGIN}/authorize",
                    "token_endpoint": f"{_AUTH_ORIGIN}/token",
                    "registration_endpoint": f"{_AUTH_ORIGIN}/register",
                },
            )
        if path == "/register":
            return httpx.Response(200, json={"client_id": self.registered_client_id})
        if path == "/token":
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            if form.get("grant_type") == "authorization_code":
                return httpx.Response(
                    200,
                    json={
                        "access_token": "access-1",
                        "token_type": "Bearer",
                        "refresh_token": "refresh-1",
                        "scope": "tools",
                    },
                )
            if form.get("grant_type") == "refresh_token":
                self.refresh_call_count += 1
                return httpx.Response(
                    200, json={"access_token": f"access-{self.refresh_call_count + 1}", "token_type": "Bearer"}
                )
        return httpx.Response(404)


def _make_provider(fake_server: _FakeAuthServer) -> MCPOAuthProvider:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(fake_server.handler))
    return MCPOAuthProvider(
        _SERVER_URL,
        MemoryOAuthStateStore(),
        client_metadata=OAuthClientMetadata(redirect_uris=["http://127.0.0.1:0/callback"]),
        http_client=http_client,
    )


class TestAuthorizationRequiredOnFirstConnect:
    async def test_refresh_without_credentials_raises_with_authorization_url(self) -> None:
        provider = _make_provider(_FakeAuthServer())
        with pytest.raises(MCPOAuthAuthorizationRequiredError) as exc_info:
            await provider.refresh()
        assert exc_info.value.authorization_url.startswith(f"{_AUTH_ORIGIN}/authorize")


class TestFullPkceFlow:
    async def test_start_then_complete_authorization_stores_tokens(self) -> None:
        provider = _make_provider(_FakeAuthServer())
        auth_url = await provider.start_authorization()
        assert "code_challenge=" in auth_url
        assert "code_challenge_method=S256" in auth_url

        await provider.complete_authorization("fake-authorization-code")

        token = await provider.current_access_token()
        assert token == "access-1"


class TestConcurrentRefreshDedup:
    async def test_five_concurrent_401s_trigger_exactly_one_refresh(self) -> None:
        fake_server = _FakeAuthServer()
        provider = _make_provider(fake_server)
        # 先走一遍完整授权，确保有 refresh_token 可用。
        await provider.start_authorization()
        await provider.complete_authorization("fake-authorization-code")

        auth_provider = RefreshDedupAuthProvider(provider)
        await asyncio.gather(*(auth_provider.on_unauthorized() for _ in range(5)))

        assert fake_server.refresh_call_count == 1


class TestStepUpScope:
    def test_step_up_scope_unions_granted_and_challenged(self) -> None:
        assert step_up_scope("tools", "tools admin") == "admin tools"
        assert step_up_scope(None, "tools") == "tools"

    async def test_step_up_builds_a_new_authorization_url_with_union_scope(self) -> None:
        fake_server = _FakeAuthServer()
        provider = _make_provider(fake_server)
        await provider.start_authorization()
        await provider.complete_authorization("fake-authorization-code")

        url = await provider.step_up("admin")
        assert "scope=admin+tools" in url or "scope=tools+admin" in url


class TestDiscoverySecurity:
    async def test_issuer_mismatch_is_rejected(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "issuer": "https://attacker.example",
                    "authorization_endpoint": f"{_AUTH_ORIGIN}/authorize",
                    "token_endpoint": f"{_AUTH_ORIGIN}/token",
                },
            )

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with pytest.raises(OAuthIssuerMismatchError):
            await discover_authorization_server_metadata(http_client, _AUTH_ORIGIN)

    def test_insecure_url_scheme_is_rejected(self) -> None:
        with pytest.raises(OAuthInsecureEndpointError):
            parse_authorization_server_metadata(
                {
                    "issuer": _AUTH_ORIGIN,
                    "authorization_endpoint": "javascript:alert(1)",
                    "token_endpoint": f"{_AUTH_ORIGIN}/token",
                }
            )
