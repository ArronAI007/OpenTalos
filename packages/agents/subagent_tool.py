from typing import Any

from core.model import ModelClient
from tool.outcome import ToolOutcome
from tool.registry import ToolRegistry
from tool.tool import Tool, ToolParameter

from .builder import build_agent

DEFAULT_SUBAGENT_NAME = "subagent"


class DispatchSubagentTool(Tool):
    """让主 agent 把一个子任务派给一个临时构造的子 ReActAgent 去跑——Claude Code 的 Task
    工具同款思路：没有预定义的角色集合，子 agent 用完即弃，拿到的工具注册表是"主 agent
    全部工具减去这个工具自己"（调用方必须传一份物理上独立的 registry，不能是主 agent
    那份的引用，否则子 agent 会连带看到 dispatch_subagent 自己，能够递归再分派）。
    """

    def __init__(self, model_client: ModelClient, subagent_tools: ToolRegistry) -> None:
        super().__init__(
            name="dispatch_subagent",
            description=(
                "Dispatch a focused sub-task to a fresh subagent instance. Use this for sub-tasks that "
                "can be worked on independently (e.g. in parallel with other sub-tasks) or that would "
                "otherwise clutter your own context. The subagent starts with no memory of this "
                "conversation — give it everything it needs in `prompt`."
            ),
        )
        self._model_client = model_client
        self._subagent_tools = subagent_tools

    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="description", type="string", description="A short (3-5 word) description of the sub-task."
            ),
            ToolParameter(
                name="prompt", type="string", description="The complete task for the subagent to perform."
            ),
        ]

    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
        subagent = build_agent(DEFAULT_SUBAGENT_NAME, self._model_client, tool_registry=self._subagent_tools)
        try:
            answer = await subagent.arespond(arguments["prompt"])
        except Exception as exc:  # noqa: BLE001 - 子 agent 失败不连累主 agent 的整次请求
            return ToolOutcome.error(f"{type(exc).__name__}: {exc}")
        return ToolOutcome.ok(answer)
