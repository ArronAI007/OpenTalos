"""最小传输接口——协议核心（`MCPClient`）只通过这个接口和传输交互，不感知消息来自哪种传输。"""
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable


@runtime_checkable
class McpTransport(Protocol):
    on_message: Callable[[dict[str, Any]], Awaitable[None]] | None
    on_error: Callable[[Exception], Awaitable[None]] | None
    on_close: Callable[[], Awaitable[None]] | None

    async def start(self) -> None: ...

    async def send(self, message: dict[str, Any]) -> None: ...

    async def close(self) -> None: ...


class TransportEventsMixin:
    """`on_message`/`on_error`/`on_close` 三个回调槽位 + "close 只触发一次"的共享样板，供三种
    传输实现复用（对应 pi 的 `TransportEvents` 基类）。"""

    def __init__(self) -> None:
        self.on_message: Callable[[dict[str, Any]], Awaitable[None]] | None = None
        self.on_error: Callable[[Exception], Awaitable[None]] | None = None
        self.on_close: Callable[[], Awaitable[None]] | None = None
        self._close_emitted = False

    async def _emit_message(self, message: dict[str, Any]) -> None:
        if self.on_message is not None:
            await self.on_message(message)

    async def _emit_error(self, error: Exception) -> None:
        if self.on_error is not None:
            await self.on_error(error)

    async def _emit_close(self) -> None:
        if self._close_emitted:
            return
        self._close_emitted = True
        if self.on_close is not None:
            await self.on_close()
