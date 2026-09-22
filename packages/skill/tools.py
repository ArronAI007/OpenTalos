from typing import Any

from tool.outcome import ToolOutcome
from tool.tool import Tool, ToolParameter

from .client import SkillClient, SkillServiceError
from .models import RunScriptResponse


class ReadSkillTool(Tool):
    """读一个技能的完整文档（SKILL.md）。模型先读文档、再决定怎么跑脚本。"""

    def __init__(self, client: SkillClient) -> None:
        super().__init__(
            name="read_skill",
            description=(
                "Read a skill's full documentation (SKILL.md) to learn what it does and how to run "
                "its scripts. Always read a skill's documentation before running its scripts."
            ),
        )
        self._client = client

    def parameters(self) -> list[ToolParameter]:
        return [ToolParameter(name="skill_name", type="string", description="Name of the skill to read.")]

    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
        try:
            return ToolOutcome.ok(await self._client.read_skill(arguments["skill_name"]))
        except SkillServiceError as error:
            return ToolOutcome.error(str(error))


class RunSkillScriptTool(Tool):
    """在 skill 服务上执行技能脚本，回传 stdout/stderr/退出码。"""

    def __init__(self, client: SkillClient) -> None:
        super().__init__(
            name="run_skill_script",
            description=(
                "Execute a script belonging to a skill and return its output. "
                "Use read_skill first to learn the correct script_relative_path and args."
            ),
        )
        self._client = client

    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(name="skill_name", type="string", description="Name of the skill that owns the script."),
            ToolParameter(
                name="script_relative_path",
                type="string",
                description="Script path relative to the skill directory, as documented in the skill's SKILL.md.",
            ),
            ToolParameter(
                name="args",
                type="array",
                description="Command-line arguments for the script.",
                required=False,
                items="string",
            ),
            ToolParameter(
                name="input_text",
                type="string",
                description="Input text for scripts that read data, as documented in the skill's SKILL.md.",
                required=False,
            ),
        ]

    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
        try:
            result = await self._client.run_script(
                arguments["skill_name"],
                arguments["script_relative_path"],
                args=arguments.get("args"),
                input_text=arguments.get("input_text"),
            )
        except SkillServiceError as error:
            return ToolOutcome.error(str(error))
        return ToolOutcome.ok(_render_result(result))


def _render_result(result: RunScriptResponse) -> str:
    """脚本跑完（哪怕退出码非 0）都算工具调用成功——把现场完整留给模型判断。"""
    if result.timed_out:
        return "The script timed out before producing a result."
    if result.exit_code != 0:
        return f"The script exited with code {result.exit_code}.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return result.stdout or "(no output)"
