"""OAuth 发现协议：WWW-Authenticate 解析 + 受保护资源/授权服务器元数据发现。"""
import re
from urllib.parse import urljoin, urlparse

import httpx

from .errors import OAuthIssuerMismatchError
from .types import (
    AuthorizationServerMetadata,
    OAuthProtectedResourceMetadata,
    parse_authorization_server_metadata,
    parse_protected_resource_metadata,
)

_WWW_AUTHENTICATE_PARAM_RE = re.compile(r'(\w+)="([^"]*)"')


def parse_www_authenticate(header: str) -> dict[str, str]:
    return dict(_WWW_AUTHENTICATE_PARAM_RE.findall(header))


async def discover_protected_resource_metadata(
    http_client: httpx.AsyncClient, server_url: str
) -> OAuthProtectedResourceMetadata | None:
    parsed = urlparse(server_url)
    candidates = []
    if parsed.path and parsed.path != "/":
        candidates.append(f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-protected-resource{parsed.path}")
    candidates.append(f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-protected-resource")
    for url in candidates:
        response = await http_client.get(url)
        if response.status_code in (404,) or response.status_code >= 500:
            continue
        if response.status_code == 200:
            return parse_protected_resource_metadata(response.json())
    return None


async def discover_authorization_server_metadata(
    http_client: httpx.AsyncClient, issuer_url: str, *, skip_issuer_validation: bool = False
) -> AuthorizationServerMetadata | None:
    parsed = urlparse(issuer_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    candidates = [
        urljoin(origin + "/", f".well-known/oauth-authorization-server{parsed.path}"),
        f"{origin}/.well-known/oauth-authorization-server",
        urljoin(origin + "/", f".well-known/openid-configuration{parsed.path}"),
        f"{origin}/.well-known/openid-configuration",
    ]
    for url in candidates:
        response = await http_client.get(url)
        if response.status_code != 200:
            continue
        metadata = parse_authorization_server_metadata(response.json())
        if not skip_issuer_validation and metadata.issuer.rstrip("/") != issuer_url.rstrip("/"):
            raise OAuthIssuerMismatchError(
                f"discovered issuer {metadata.issuer!r} does not match requested {issuer_url!r}"
            )
        return metadata
    return None


async def discover_oauth_server_info(
    http_client: httpx.AsyncClient, server_url: str
) -> tuple[OAuthProtectedResourceMetadata | None, AuthorizationServerMetadata | None]:
    protected_resource = await discover_protected_resource_metadata(http_client, server_url)
    if protected_resource and protected_resource.authorization_servers:
        issuer_url = protected_resource.authorization_servers[0]
    else:
        parsed = urlparse(server_url)
        issuer_url = f"{parsed.scheme}://{parsed.netloc}"
    auth_server = await discover_authorization_server_metadata(http_client, issuer_url)
    return protected_resource, auth_server
