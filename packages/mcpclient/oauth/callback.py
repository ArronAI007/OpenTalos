"""OAuth 回调的运行时无关等待原语——不监听任何端口（见 research.md Decision 6：真正接收浏览器
重定向的 HTTP 路由由 apps/api/main.py 提供，这里只是一个 pending-Future 登记表）。"""
import asyncio
from typing import Any


class PendingCallbackRegistry:
    def __init__(self) -> None:
        self._pending: dict[str, "asyncio.Future[dict[str, Any]]"] = {}

    def register(self, state: str) -> "asyncio.Future[dict[str, Any]]":
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[state] = future
        return future

    def resolve(self, state: str, params: dict[str, Any]) -> bool:
        future = self._pending.pop(state, None)
        if future is None or future.done():
            return False
        future.set_result(params)
        return True
