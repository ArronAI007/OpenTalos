"""OAuth 相关 dataclass + 结构校验 parse 函数（对齐 pi `oauth/types.ts`）。"""
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .errors import OAuthError, OAuthInsecureEndpointError

_SAFE_URL_SCHEMES = ("http", "https")


def _check_safe_url(url: str, field_name: str) -> None:
    scheme = urlparse(url).scheme.lower()
    if scheme and scheme not in _SAFE_URL_SCHEMES:
        raise OAuthInsecureEndpointError(f"{field_name} 使用了不安全的 URL scheme: {scheme!r} ({url!r})")


@dataclass
class OAuthTokens:
    access_token: str
    token_type: str
    expires_in: int | None = None
    refresh_token: str | None = None
    scope: str | None = None


@dataclass
class OAuthClientInformation:
    client_id: str
    client_secret: str | None = None
    client_id_issued_at: int | None = None
    client_secret_expires_at: int | None = None


@dataclass
class OAuthClientMetadata:
    redirect_uris: list[str]
    client_name: str | None = None
    scope: str | None = None
    grant_types: list[str] = field(default_factory=lambda: ["authorization_code", "refresh_token"])
    response_types: list[str] = field(default_factory=lambda: ["code"])
    token_endpoint_auth_method: str = "none"


@dataclass
class OAuthProtectedResourceMetadata:
    resource: str
    authorization_servers: list[str] = field(default_factory=list)
    scopes_supported: list[str] | None = None


@dataclass
class AuthorizationServerMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None = None
    scopes_supported: list[str] | None = None
    token_endpoint_auth_methods_supported: list[str] | None = None
    code_challenge_methods_supported: list[str] | None = None


def _require(data: dict[str, Any], key: str, type_: type, context: str) -> Any:
    value = data.get(key)
    if not isinstance(value, type_) or (type_ is str and not value):
        raise OAuthError(f"{context}: 字段 {key!r} 缺失或类型不对，收到: {value!r}")
    return value


def parse_oauth_tokens(data: dict[str, Any]) -> OAuthTokens:
    access_token = _require(data, "access_token", str, "OAuthTokens")
    token_type = _require(data, "token_type", str, "OAuthTokens")
    return OAuthTokens(
        access_token=access_token,
        token_type=token_type,
        expires_in=data.get("expires_in"),
        refresh_token=data.get("refresh_token"),
        scope=data.get("scope"),
    )


def parse_client_information(data: dict[str, Any]) -> OAuthClientInformation:
    client_id = _require(data, "client_id", str, "OAuthClientInformation")
    return OAuthClientInformation(
        client_id=client_id,
        client_secret=data.get("client_secret"),
        client_id_issued_at=data.get("client_id_issued_at"),
        client_secret_expires_at=data.get("client_secret_expires_at"),
    )


def parse_protected_resource_metadata(data: dict[str, Any]) -> OAuthProtectedResourceMetadata:
    resource = _require(data, "resource", str, "OAuthProtectedResourceMetadata")
    _check_safe_url(resource, "resource")
    servers = data.get("authorization_servers", [])
    for server in servers:
        _check_safe_url(server, "authorization_servers[]")
    return OAuthProtectedResourceMetadata(
        resource=resource, authorization_servers=list(servers), scopes_supported=data.get("scopes_supported")
    )


def parse_authorization_server_metadata(data: dict[str, Any]) -> AuthorizationServerMetadata:
    issuer = _require(data, "issuer", str, "AuthorizationServerMetadata")
    authorization_endpoint = _require(data, "authorization_endpoint", str, "AuthorizationServerMetadata")
    token_endpoint = _require(data, "token_endpoint", str, "AuthorizationServerMetadata")
    for name, url in (
        ("issuer", issuer),
        ("authorization_endpoint", authorization_endpoint),
        ("token_endpoint", token_endpoint),
        ("registration_endpoint", data.get("registration_endpoint")),
    ):
        if url:
            _check_safe_url(url, name)
    return AuthorizationServerMetadata(
        issuer=issuer,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        registration_endpoint=data.get("registration_endpoint"),
        scopes_supported=data.get("scopes_supported"),
        token_endpoint_auth_methods_supported=data.get("token_endpoint_auth_methods_supported"),
        code_challenge_methods_supported=data.get("code_challenge_methods_supported"),
    )
