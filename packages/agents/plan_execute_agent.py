import json

from core.agent import Agent, AssemblyConfig
from core.chat_message import ChatMessage
from core.model_client import ModelClient
from core.settings import RuntimeSettings
from tool.registry import ToolRegistry

from .dialogue import run_tool_turn

DEFAULT_PLANNER_PROMPT = "You break a complex question into an ordered list of independent, executable sub-steps."
DEFAULT_RUNNER_PROMPT = "You execute a single step of a larger plan, using the prior steps' results as context."

PROPOSE_STEPS_TOOL = {
    "type": "function",
    "function": {
        "name": "propose_steps",
        "description": "Propose an ordered list of steps to solve the question.",
        "parameters": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered, independently executable steps.",
                }
            },
            "required": ["steps"],
        },
    },
}


class PlanExecuteAgent(Agent):
    """先把问题拆成有序步骤（强制 function call），再逐步执行，滚动累积上下文。"""

    def __init__(
        self,
        name: str,
        model_client: ModelClient,
        system_prompt: str | None = None,
        settings: RuntimeSettings | None = None,
        tool_registry: ToolRegistry | None = None,
        max_tool_iterations: int = 3,
        runner_system_prompt: str | None = None,
        context_config: AssemblyConfig | None = None,
        min_retain_turns: int = 10,
    ) -> None:
        super().__init__(
            name,
            model_client,
            system_prompt or DEFAULT_PLANNER_PROMPT,
            settings,
            context_config,
            min_retain_turns,
        )
        self.tool_registry = tool_registry
        self.max_tool_iterations = max_tool_iterations
        self.runner_system_prompt = runner_system_prompt or DEFAULT_RUNNER_PROMPT

    async def arespond(self, input_text: str, **kwargs: object) -> str:
        steps = await self._plan(input_text, **kwargs)
        answer = await self._run_steps(input_text, steps, **kwargs)

        self.record_message(ChatMessage(content=input_text, role="user"))
        self.record_message(ChatMessage(content=answer, role="assistant"))
        return answer

    async def _plan(self, question: str, **kwargs: object) -> list[str]:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Produce a step-by-step plan for:\n\n{question}"},
        ]
        completion = await self.model_client.acomplete_with_tools(
            messages,
            [PROPOSE_STEPS_TOOL],
            tool_choice={"type": "function", "function": {"name": "propose_steps"}},
            **kwargs,
        )
        if not completion.requested_tools:
            return [question]
        try:
            arguments = json.loads(completion.requested_tools[0].arguments_json)
        except json.JSONDecodeError:
            return [question]
        return arguments.get("steps") or [question]

    async def _run_steps(self, question: str, steps: list[str], **kwargs: object) -> str:
        history: list[tuple[str, str]] = []
        answer = ""
        for step in steps:
            context = _render_step(question, steps, history, step)
            messages = [{"role": "system", "content": self.runner_system_prompt}, {"role": "user", "content": context}]
            answer = await run_tool_turn(self.model_client, messages, self.tool_registry, self.max_tool_iterations, **kwargs)
            history.append((step, answer))
        return answer


def _render_step(question: str, steps: list[str], history: list[tuple[str, str]], current: str) -> str:
    plan_text = "\n".join(f"{i}. {step}" for i, step in enumerate(steps, start=1))
    history_text = "\n\n".join(f"Step: {step}\nResult: {result}" for step, result in history) or "(none yet)"
    return (
        f"# Original question\n{question}\n\n"
        f"# Full plan\n{plan_text}\n\n"
        f"# Completed steps\n{history_text}\n\n"
        f"# Current step\n{current}\n\n"
        "Execute the current step and give its result."
    )
