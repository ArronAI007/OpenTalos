"""传输层使用的最小鉴权接口——`StreamableHttpTransport` 只依赖这个形状，不知道 token 从哪来。"""
from typing import Any, Protocol


class AuthProvider(Protocol):
    async def token(self) -> str | None: ...

    async def on_unauthorized(self, context: dict[str, Any] | None = None) -> None: ...
