"""packages/a2apeer 的真机测试——对 demo_server.py 发起真实子进程 + 真实 HTTP 调用，不 mock。
demo_peer fixture 来自同目录的 conftest.py（pytest 自动发现，不需要 import）。"""
import uuid

import httpx
from a2a.client import create_client
from a2a.types import Message, Part, Role, SendMessageRequest


class TestBuildA2AApp:
    async def test_agent_card_is_reachable(self, demo_peer: str) -> None:
        async with httpx.AsyncClient() as http:
            resp = await http.get(f"{demo_peer}.well-known/agent-card.json")
        assert resp.status_code == 200
        assert resp.json()["name"] == "demo"

    async def test_real_message_round_trip(self, demo_peer: str) -> None:
        client = await create_client(demo_peer)
        request = SendMessageRequest(
            message=Message(message_id=uuid.uuid4().hex, role=Role.ROLE_USER, parts=[Part(text="hi")])
        )
        reply_text = None
        async for response in client.send_message(request):
            if response.WhichOneof("payload") == "message":
                reply_text = "".join(
                    part.text for part in response.message.parts if part.WhichOneof("content") == "text"
                )
                break
        assert reply_text == "HELLO FROM PEER"
