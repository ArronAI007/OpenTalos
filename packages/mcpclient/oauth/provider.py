"""`MCPOAuthProvider`：绑定单个 `server_url` 的具体 OAuth 状态持有者；凭据存储通过注入的
`OAuthStateStore` 完全由调用方决定（FR-012），这个包本身只提供一个内存实现。"""
import asyncio
import secrets
from dataclasses import dataclass
from typing import Protocol

import httpx

from .discovery import discover_oauth_server_info
from .errors import MCPOAuthAuthorizationRequiredError, OAuthError
from .flow import exchange_authorization_code, pkce, refresh_authorization, register_client, start_authorization, step_up_scope
from .types import (
    AuthorizationServerMetadata,
    OAuthClientInformation,
    OAuthClientMetadata,
    OAuthTokens,
)


@dataclass
class MCPOAuthState:
    tokens: OAuthTokens | None = None
    client_information: OAuthClientInformation | None = None
    code_verifier: str | None = None


class OAuthStateStore(Protocol):
    async def load(self, server_url: str) -> MCPOAuthState | None: ...
    async def save(self, server_url: str, state: MCPOAuthState) -> None: ...


class MemoryOAuthStateStore:
    """默认的内存实现——测试/未显式配置持久化时的兜底行为，不代表这个包替调用方做了选择。"""

    def __init__(self) -> None:
        self._states: dict[str, MCPOAuthState] = {}

    async def load(self, server_url: str) -> MCPOAuthState | None:
        return self._states.get(server_url)

    async def save(self, server_url: str, state: MCPOAuthState) -> None:
        self._states[server_url] = state


class MCPOAuthProvider:
    def __init__(
        self,
        server_url: str,
        store: OAuthStateStore,
        *,
        client_metadata: OAuthClientMetadata,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._server_url = server_url
        self._store = store
        self._client_metadata = client_metadata
        self._http_client = http_client or httpx.AsyncClient()
        self._redirect_uri = client_metadata.redirect_uris[0]
        self._writes = asyncio.Lock()  # 序列化对 store 的写入，避免并发 refresh/complete 互相覆盖
        self._auth_server_metadata: AuthorizationServerMetadata | None = None

    async def _discover(self) -> AuthorizationServerMetadata:
        if self._auth_server_metadata is None:
            _, auth_meta = await discover_oauth_server_info(self._http_client, self._server_url)
            if auth_meta is None:
                raise OAuthError(f"could not discover authorization server metadata for {self._server_url!r}")
            self._auth_server_metadata = auth_meta
        return self._auth_server_metadata

    async def _ensure_client_registered(self) -> OAuthClientInformation:
        async with self._writes:
            state = await self._store.load(self._server_url) or MCPOAuthState()
            if state.client_information is not None:
                return state.client_information
            metadata = await self._discover()
            info = await register_client(self._http_client, metadata, self._client_metadata)
            state.client_information = info
            await self._store.save(self._server_url, state)
            return info

    async def start_authorization(self) -> str:
        metadata = await self._discover()
        client_info = await self._ensure_client_registered()
        code_verifier, code_challenge = pkce()
        async with self._writes:
            state = await self._store.load(self._server_url) or MCPOAuthState()
            state.code_verifier = code_verifier
            await self._store.save(self._server_url, state)
        return start_authorization(
            metadata,
            client_id=client_info.client_id,
            redirect_uri=self._redirect_uri,
            code_challenge=code_challenge,
            state=secrets.token_urlsafe(16),
            scope=self._client_metadata.scope,
        )

    async def complete_authorization(self, authorization_code: str) -> None:
        metadata = await self._discover()
        async with self._writes:
            state = await self._store.load(self._server_url)
            if state is None or state.code_verifier is None:
                raise OAuthError("no pending authorization for this server — call start_authorization() first")
            if state.client_information is None:
                raise OAuthError("client is not registered yet")
            tokens = await exchange_authorization_code(
                self._http_client,
                metadata,
                state.client_information,
                code=authorization_code,
                code_verifier=state.code_verifier,
                redirect_uri=self._redirect_uri,
            )
            state.tokens = tokens
            state.code_verifier = None
            await self._store.save(self._server_url, state)

    async def refresh(self) -> None:
        """FR-011 Acceptance Scenario 1：本地没有可刷新的凭据（从未授权过，或 refresh_token
        缺失）时，抛出 `MCPOAuthAuthorizationRequiredError`（携带一个新的授权 URL）而不是普通
        地返回或报连接失败——调用方据此知道"该发起授权流程了"。"""
        state = await self._store.load(self._server_url)
        has_refreshable = (
            state is not None
            and state.tokens is not None
            and state.tokens.refresh_token is not None
            and state.client_information is not None
        )
        if not has_refreshable:
            authorization_url = await self.start_authorization()
            raise MCPOAuthAuthorizationRequiredError(
                "no local credentials to refresh — authorization required", authorization_url
            )
        metadata = await self._discover()
        new_tokens = await refresh_authorization(
            self._http_client, metadata, state.client_information, refresh_token=state.tokens.refresh_token
        )
        async with self._writes:
            state.tokens = new_tokens
            await self._store.save(self._server_url, state)

    async def current_access_token(self) -> str | None:
        state = await self._store.load(self._server_url)
        return state.tokens.access_token if state and state.tokens else None

    async def step_up(self, challenged_scope: str) -> str:
        state = await self._store.load(self._server_url)
        granted_scope = state.tokens.scope if state and state.tokens else None
        new_scope = step_up_scope(granted_scope, challenged_scope)
        metadata = await self._discover()
        client_info = await self._ensure_client_registered()
        code_verifier, code_challenge = pkce()
        async with self._writes:
            next_state = await self._store.load(self._server_url) or MCPOAuthState()
            next_state.code_verifier = code_verifier
            await self._store.save(self._server_url, next_state)
        return start_authorization(
            metadata,
            client_id=client_info.client_id,
            redirect_uri=self._redirect_uri,
            code_challenge=code_challenge,
            state=secrets.token_urlsafe(16),
            scope=new_scope,
        )
