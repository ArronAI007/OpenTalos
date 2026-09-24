import json
from collections.abc import Awaitable, Callable
from typing import Any

from core.agent import Agent, AssemblyConfig, OutputTrimmer, RuntimeSettings
from core.agent_loop import execute_model_step, resolve_tool_call, seed_messages
from core.cancellation import CancellationToken
from core.protocol import ChatMessage, ToolInvocation
from core.model import ModelClient
from tool.registry import ToolRegistry

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
        trace_dir: str | None = None,
        compaction_token_limit: int | None = None,
        output_trimmer: OutputTrimmer | None = None,
    ) -> None:
        super().__init__(
            name,
            model_client,
            system_prompt or DEFAULT_SYSTEM_PROMPT,
            settings,
            context_config,
            min_retain_turns,
            trace_dir,
            compaction_token_limit,
            output_trimmer,
        )
        self.tool_registry = tool_registry
        self.max_steps = max_steps

    def _tool_schemas(self) -> list[dict[str, Any]]:
        extra = self.tool_registry.function_schemas() if self.tool_registry else []
        return [FINISH_TOOL_SCHEMA, *extra]

    async def arespond(self, input_text: str, **kwargs: object) -> str:
        cancellation: CancellationToken | None = kwargs.pop("cancellation", None)
        on_text_delta: Callable[[str], Awaitable[None]] | None = kwargs.pop("on_text_delta", None)
        messages = seed_messages(self.system_prompt, self.history_snapshot(), input_text)
        tools = self._tool_schemas()
        answer: str | None = None

        for step in range(1, self.max_steps + 1):

            async def handle_invocation(invocation: ToolInvocation, step: int = step) -> dict[str, str]:
                return await self._handle(invocation, step)

            completion = await execute_model_step(
                self.model_client,
                messages,
                tools,
                recorder=self.recorder,
                step=step,
                on_text_delta=on_text_delta,
                cancellation=cancellation,
                handle_invocation=handle_invocation,
                **kwargs,
            )
            if not completion.requested_tools:
                answer = completion.text or ""
                break

            finish_calls = [inv for inv in completion.requested_tools if inv.tool_name == FINISH_TOOL_NAME]
            if finish_calls:
                answer = _read_final_answer(finish_calls[-1])
                if self.recorder:
                    self.recorder.log_event("finish", {"final_answer": answer}, step=step)
                break

        if answer is None:
            answer = STEP_LIMIT_MESSAGE

        self.record_message(ChatMessage(content=input_text, role="user"))
        self.record_message(ChatMessage(content=answer, role="assistant"))
        await self.maybe_compress_history()
        return answer

    async def _handle(self, invocation: ToolInvocation, step: int) -> dict[str, str]:
        if invocation.tool_name == FINISH_TOOL_NAME:
            return {"role": "tool", "tool_call_id": invocation.call_id, "content": "acknowledged"}
        return await self._resolve(invocation, step)

    async def _resolve(self, invocation: ToolInvocation, step: int) -> dict[str, str]:
        if self.tool_registry is None:
            return {"role": "tool", "tool_call_id": invocation.call_id, "content": "No tools are available."}
        return await resolve_tool_call(
            self.tool_registry, invocation, self.recorder, step, self.output_trimmer,
            on_tool_result=self.record_tool_result,
        )


def _read_final_answer(invocation: ToolInvocation) -> str:
    try:
        arguments = json.loads(invocation.arguments_json)
    except json.JSONDecodeError:
        return invocation.arguments_json
    return arguments.get("final_answer", "")
