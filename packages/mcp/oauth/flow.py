"""OAuth 授权码 + PKCE 流程的核心编排（对齐 pi `oauth/flow.ts`，去掉 TS 专属的
`OAuthClientProvider` 接口细节，只留 Python 侧真正需要的纯函数 + 一个并发去重适配器）。"""
import asyncio
import base64
import hashlib
import secrets
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import urlencode

import httpx

from .errors import OAuthRegistrationError
from .types import (
    AuthorizationServerMetadata,
    OAuthClientInformation,
    OAuthClientMetadata,
    OAuthTokens,
    parse_client_information,
    parse_oauth_tokens,
)


def pkce() -> tuple[str, str]:
    """返回 `(code_verifier, code_challenge)`，S256 方法。"""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def start_authorization(
    metadata: AuthorizationServerMetadata,
    *,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
    scope: str | None = None,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    if scope:
        params["scope"] = scope
        if "offline_access" in scope.split():
            params["prompt"] = "consent"
    return f"{metadata.authorization_endpoint}?{urlencode(params)}"


def _apply_client_authentication(
    client_info: OAuthClientInformation, form: dict[str, Any], headers: dict[str, str]
) -> None:
    """选择客户端鉴权方式：有 client_secret 用 HTTP Basic（client_secret_basic），否则把
    client_id 放进表单体（client_secret_post 的无密钥变体，等价于 pi 的 "none" 方法）。"""
    if client_info.client_secret:
        credentials = f"{client_info.client_id}:{client_info.client_secret}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(credentials).decode("ascii")
    else:
        form["client_id"] = client_info.client_id


async def exchange_authorization_code(
    http_client: httpx.AsyncClient,
    metadata: AuthorizationServerMetadata,
    client_info: OAuthClientInformation,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> OAuthTokens:
    form: dict[str, Any] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    headers: dict[str, str] = {}
    _apply_client_authentication(client_info, form, headers)
    response = await http_client.post(metadata.token_endpoint, data=form, headers=headers)
    response.raise_for_status()
    return parse_oauth_tokens(response.json())


async def refresh_authorization(
    http_client: httpx.AsyncClient,
    metadata: AuthorizationServerMetadata,
    client_info: OAuthClientInformation,
    *,
    refresh_token: str,
) -> OAuthTokens:
    form: dict[str, Any] = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    headers: dict[str, str] = {}
    _apply_client_authentication(client_info, form, headers)
    response = await http_client.post(metadata.token_endpoint, data=form, headers=headers)
    response.raise_for_status()
    return parse_oauth_tokens(response.json())


async def register_client(
    http_client: httpx.AsyncClient, metadata: AuthorizationServerMetadata, client_metadata: OAuthClientMetadata
) -> OAuthClientInformation:
    if not metadata.registration_endpoint:
        raise OAuthRegistrationError("authorization server did not advertise a registration_endpoint")
    body = {
        "redirect_uris": client_metadata.redirect_uris,
        "grant_types": client_metadata.grant_types,
        "response_types": client_metadata.response_types,
        "token_endpoint_auth_method": client_metadata.token_endpoint_auth_method,
    }
    if client_metadata.client_name:
        body["client_name"] = client_metadata.client_name
    if client_metadata.scope:
        body["scope"] = client_metadata.scope
    response = await http_client.post(metadata.registration_endpoint, json=body)
    if response.status_code >= 400:
        raise OAuthRegistrationError(f"dynamic client registration failed: HTTP {response.status_code}")
    return parse_client_information(response.json())


def step_up_scope(granted_scope: str | None, challenged_scope: str) -> str:
    """SEP-2350：已授予 scope 和服务端要求的 scope 取并集，而不是替换。"""
    granted = set(granted_scope.split()) if granted_scope else set()
    challenged = set(challenged_scope.split())
    return " ".join(sorted(granted | challenged))


class _RefreshingOAuthProvider(Protocol):
    async def refresh(self) -> None: ...
    async def current_access_token(self) -> str | None: ...


class RefreshDedupAuthProvider:
    """把一个具体的 OAuth 状态持有者包装成传输层需要的 `AuthProvider`
    （`token()`/`on_unauthorized()`）。并发多个请求同时收到 401 时，只触发一次真正的刷新，
    其余请求 `await` 同一个进行中的刷新任务、共享结果——核心是 `self._inflight` 这一个
    模块/实例作用域的锁存 `asyncio.Task`。"""

    def __init__(self, provider: _RefreshingOAuthProvider) -> None:
        self._provider = provider
        self._inflight: asyncio.Task[None] | None = None

    async def token(self) -> str | None:
        return await self._provider.current_access_token()

    async def on_unauthorized(self, context: dict[str, Any] | None = None) -> None:
        if self._inflight is None or self._inflight.done():
            self._inflight = asyncio.create_task(self._provider.refresh())
        await self._inflight
