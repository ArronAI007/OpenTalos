import json
from typing import Any

from core.agent import Agent, AssemblyConfig
from core.chat_message import ChatMessage
from core.completion import ToolInvocation
from core.model_client import ModelClient
from core.settings import RuntimeSettings
from tool.registry import ToolRegistry

from .dialogue import build_reply_message, resolve_tool_call, seed_messages

FINISH_TOOL_NAME = "finish"

FINISH_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": FINISH_TOOL_NAME,
        "description": "Call this once you have the final answer for the user's request.",
        "parameters": {
            "type": "object",
            "properties": {"final_answer": {"type": "string", "description": "The final answer to return."}},
            "required": ["final_answer"],
        },
    },
}

DEFAULT_SYSTEM_PROMPT = (
    "You solve tasks by alternating between reasoning and tool calls. "
    f"Call tools as needed, then call `{FINISH_TOOL_NAME}` with your final answer once you are done."
)

STEP_LIMIT_MESSAGE = "Reached the step limit without a final answer."


class ReActAgent(Agent):
    """ReAct 风格：一步步推理 + 调用工具，直到模型主动调用内置 finish 工具或用光步数。"""

    def __init__(
        self,
        name: str,
        model_client: ModelClient,
        system_prompt: str | None = None,
        settings: RuntimeSettings | None = None,
        tool_registry: ToolRegistry | None = None,
        max_steps: int = 6,
        context_config: AssemblyConfig | None = None,
        min_retain_turns: int = 10,
    ) -> None:
        super().__init__(
            name,
            model_client,
            system_prompt or DEFAULT_SYSTEM_PROMPT,
            settings,
            context_config,
            min_retain_turns,
        )
        self.tool_registry = tool_registry
        self.max_steps = max_steps

    def _tool_schemas(self) -> list[dict[str, Any]]:
        extra = self.tool_registry.function_schemas() if self.tool_registry else []
        return [FINISH_TOOL_SCHEMA, *extra]

    async def arespond(self, input_text: str, **kwargs: object) -> str:
        messages = seed_messages(self.system_prompt, self.history_snapshot(), input_text)
        tools = self._tool_schemas()
        answer: str | None = None

        for _ in range(self.max_steps):
            completion = await self.model_client.acomplete_with_tools(messages, tools, **kwargs)
            if not completion.requested_tools:
                answer = completion.text or ""
                break

            messages.append(build_reply_message(completion.text, completion.requested_tools))
            finished = False
            for invocation in completion.requested_tools:
                if invocation.tool_name == FINISH_TOOL_NAME:
                    answer = _read_final_answer(invocation)
                    messages.append({"role": "tool", "tool_call_id": invocation.call_id, "content": "acknowledged"})
                    finished = True
                    continue
                messages.append(await self._resolve(invocation))
            if finished:
                break

        if answer is None:
            answer = STEP_LIMIT_MESSAGE

        self.record_message(ChatMessage(content=input_text, role="user"))
        self.record_message(ChatMessage(content=answer, role="assistant"))
        return answer

    async def _resolve(self, invocation: ToolInvocation) -> dict[str, str]:
        if self.tool_registry is None:
            return {"role": "tool", "tool_call_id": invocation.call_id, "content": "No tools are available."}
        return await resolve_tool_call(self.tool_registry, invocation)


def _read_final_answer(invocation: ToolInvocation) -> str:
    try:
        arguments = json.loads(invocation.arguments_json)
    except json.JSONDecodeError:
        return invocation.arguments_json
    return arguments.get("final_answer", "")
