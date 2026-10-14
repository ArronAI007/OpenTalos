"""纯内存配对传输，不涉及任何真实子进程/网络 I/O——供协议核心自身的单元测试使用。"""
import copy
from typing import Any

from .base import TransportEventsMixin


class InMemoryTransport(TransportEventsMixin):
    def __init__(self) -> None:
        super().__init__()
        self._peer: "InMemoryTransport | None" = None
        self._closed = False

    async def start(self) -> None:
        return None

    async def send(self, message: dict[str, Any]) -> None:
        if self._closed or self._peer is None:
            raise RuntimeError("InMemoryTransport is not connected to a peer, or already closed")
        payload = copy.deepcopy(message)
        await self._peer._emit_message(payload)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._emit_close()
        if self._peer is not None and not self._peer._closed:
            await self._peer.close()


def create_in_memory_transport_pair() -> tuple[InMemoryTransport, InMemoryTransport]:
    client_side = InMemoryTransport()
    server_side = InMemoryTransport()
    client_side._peer = server_side
    server_side._peer = client_side
    return client_side, server_side
