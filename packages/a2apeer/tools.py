"""让任意 OpenTalos agent 把一个固定的 A2A peer 当工具调用——语义是"问另一个 agent"，
不是"访问某个外部数据源"，和 websearch/MCP 工具的定位不同。"""
from typing import Any

from tool.outcome import ToolOutcome
from tool.tool import Tool, ToolParameter

from .client import A2APeerError, send_message


class A2ATool(Tool):
    def __init__(self, peer_url: str) -> None:
        super().__init__(
            name="ask_peer_agent",
            description="Ask another OpenTalos agent instance a question over the A2A protocol and get its reply.",
            untrusted_output=True,
        )
        self._peer_url = peer_url

    def parameters(self) -> list[ToolParameter]:
        return [ToolParameter(name="question", type="string", description="The question to ask the peer agent.")]

    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
        try:
            reply = await send_message(self._peer_url, arguments["question"])
        except A2APeerError as error:
            return ToolOutcome.error(str(error))
        return ToolOutcome.ok(reply)
