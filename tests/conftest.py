import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

# packages/ 本身加进 sys.path——每个模块目录（skill/、core/、agents/...）本身就是一个用目录名
# 命名的 Python 包（各自有 __init__.py），所以测试里用 `from skill.discovery import ...` 这种带
# 包名前缀的写法，不同模块之间不会因为同名文件（比如都叫 models.py）互相冲突。
#
# 没有用 pytest 的 `pythonpath` ini 选项——在这个仓库实际安装的 pytest 9.1.1 上实测不生效
# （sys.path 里始终没有 packages/），改用最直接可靠、不依赖 pytest 具体版本行为的 conftest.py
# 手动插入方式。
_PACKAGES_DIR = Path(__file__).resolve().parent.parent / "packages"
if str(_PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_DIR))

from core.protocol import Completion, ToolCompletion  # noqa: E402
from core.model import ModelClient  # noqa: E402
from tool.outcome import ToolOutcome  # noqa: E402
from tool.registry import ToolRegistry  # noqa: E402
from tool.tool import Tool, ToolParameter  # noqa: E402


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

            text_queue = list(completions)

            async def fake_astream(messages: list[dict[str, Any]], **kwargs: Any):
                for char in text_queue.pop(0).text:
                    yield char

            client.astream = fake_astream  # type: ignore[method-assign]

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

            stream_queue = list(tool_completions)

            async def fake_astream_with_tools(
                messages: list[dict[str, Any]],
                tools: list[dict],
                on_text_delta=None,
                **kwargs: Any,
            ) -> ToolCompletion:
                completion = stream_queue.pop(0)
                if on_text_delta is not None:
                    for char in completion.text or "":
                        await on_text_delta(char)
                return completion

            client.astream_with_tools = fake_astream_with_tools  # type: ignore[method-assign]

        return client

    return _build
