from collections.abc import Sequence
from typing import Any

import pytest

from core.completion import Completion, ToolCompletion
from core.model_client import ModelClient
from tool.outcome import ToolOutcome
from tool.registry import ToolRegistry
from tool.tool import Tool, ToolParameter


class _EchoTool(Tool):
    def __init__(self) -> None:
        super().__init__(name="echo", description="Echoes the given text back.")

    def parameters(self) -> list[ToolParameter]:
        return [ToolParameter(name="text", type="string", description="Text to echo")]

    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
        return ToolOutcome.ok(f"echoed: {arguments['text']}")


@pytest.fixture
def echo_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(_EchoTool())
    return registry


@pytest.fixture
def scripted_client():
    """构造一个 ModelClient，acomplete/acomplete_with_tools 按顺序吐出脚本里的响应。

    FakeModelBackend.acomplete_with_tools 永远返回空的 requested_tools，没法用来测多轮工具
    调用，所以直接换掉 ModelClient 实例上的两个方法。
    """

    def _build(
        *,
        completions: Sequence[Completion] = (),
        tool_completions: Sequence[ToolCompletion] = (),
    ) -> ModelClient:
        client = ModelClient(provider="mock")

        if completions:
            queue = list(completions)

            async def fake_acomplete(messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
                return queue.pop(0)

            client.acomplete = fake_acomplete  # type: ignore[method-assign]

        if tool_completions:
            tool_queue = list(tool_completions)

            async def fake_acomplete_with_tools(
                messages: list[dict[str, Any]],
                tools: list[dict[str, Any]],
                tool_choice: str | dict = "auto",
                **kwargs: Any,
            ) -> ToolCompletion:
                return tool_queue.pop(0)

            client.acomplete_with_tools = fake_acomplete_with_tools  # type: ignore[method-assign]

        return client

    return _build
