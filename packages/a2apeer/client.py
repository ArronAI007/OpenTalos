"""A2A 客户端：对官方 SDK client 的薄封装。每次调用都新建连接（create_client 内部会重新
解析一次 AgentCard），用完即弃——和 mcpclient 的"现连现用完就关"同一个取舍。"""
import uuid

from a2a.client import create_client
from a2a.types import Message, Part, Role, SendMessageRequest


class A2APeerError(Exception):
    """连接/握手/消息往返失败统一包成这个异常——和 mcpclient 的 MCPConnectionError 同一个
    角色：调用方只用认这一种异常类型，不用关心底层是 AgentCard 解析失败、HTTP 连不上、
    还是官方 SDK 内部的哪种异常。"""


async def send_message(peer_url: str, text: str) -> str:
    try:
        client = await create_client(peer_url)
        async for response in client.send_message(SendMessageRequest(
            message=Message(message_id=uuid.uuid4().hex, role=Role.ROLE_USER, parts=[Part(text=text)])
        )):
            if response.WhichOneof("payload") == "message":
                return "".join(
                    part.text for part in response.message.parts if part.WhichOneof("content") == "text"
                )
    except Exception as exc:  # noqa: BLE001
        raise A2APeerError(f"{type(exc).__name__}: {exc}") from exc
    raise A2APeerError("no message response received")
