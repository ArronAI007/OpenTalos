"""a2apeer.client 的真机测试——demo_peer fixture 来自同目录的 conftest.py（见 Task 1），
经过自己写的 send_message 包装调用，不直接用官方 SDK 的 client。"""
import pytest

from a2apeer.client import A2APeerError, send_message


class TestSendMessage:
    async def test_returns_real_reply_text(self, demo_peer: str) -> None:
        reply = await send_message(demo_peer, "hi")
        assert reply == "HELLO FROM PEER"

    async def test_unreachable_peer_raises_a2a_peer_error(self) -> None:
        with pytest.raises(A2APeerError):
            await send_message("http://127.0.0.1:1/", "hi")
