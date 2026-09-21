import json
from typing import Any

from core.agent import RunRecorder
from core.completion import ToolInvocation
from core.model_client import ModelClient
from tool.registry import ToolRegistry


def seed_messages(system_prompt: str | None, history: list[Any], user_text: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for message in history:
        messages.append({"role": message.role, "content": message.content})
    messages.append({"role": "user", "content": user_text})
    return messages


def build_reply_message(text: str | None, requested_tools: list[ToolInvocation]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": text,
        "tool_calls": [
            {
                "id": invocation.call_id,
                "type": "function",
                "function": {"name": invocation.tool_name, "arguments": invocation.arguments_json},
            }
            for invocation in requested_tools
        ],
    }


async def resolve_tool_call(
    tool_registry: ToolRegistry, invocation: ToolInvocation, recorder: RunRecorder | None = None, step: int | None = None
) -> dict[str, str]:
    if recorder:
        recorder.log_event("tool_call", {"tool_name": invocation.tool_name, "arguments": invocation.arguments_json}, step=step)

    try:
        arguments = json.loads(invocation.arguments_json)
    except json.JSONDecodeError as error:
        message = {"role": "tool", "tool_call_id": invocation.call_id, "content": f"Invalid arguments: {error}"}
        if recorder:
            recorder.log_event("tool_result", {"tool_name": invocation.tool_name, "result": message["content"]}, step=step)
        return message

    outcome = await tool_registry.acall(invocation.tool_name, arguments)
    message = {"role": "tool", "tool_call_id": invocation.call_id, "content": outcome.output}
    if recorder:
        recorder.log_event("tool_result", {"tool_name": invocation.tool_name, "result": outcome.output}, step=step)
    return message


async def run_tool_turn(
    model_client: ModelClient,
    messages: list[dict[str, Any]],
    tool_registry: ToolRegistry | None,
    max_iterations: int,
    recorder: RunRecorder | None = None,
    **kwargs: Any,
) -> str:
    """调用 LLM -> 按需执行工具 -> 把结果喂回去，直到模型不再请求工具或用光 max_iterations。

    messages 会被原地追加 assistant/tool 消息，调用方可以在返回后继续复用它。recorder 不为空
    时，每次模型调用和每次工具调用/结果都会记一条 trace 事件。
    """
    if tool_registry is None:
        completion = await model_client.acomplete(messages, **kwargs)
        if recorder:
            recorder.log_event("model_output", {"content": completion.text, "usage": completion.token_usage})
        return completion.text

    tools = tool_registry.function_schemas()
    for step in range(1, max_iterations + 1):
        completion = await model_client.acomplete_with_tools(messages, tools, **kwargs)
        if recorder:
            recorder.log_event(
                "model_output",
                {
                    "content": completion.text,
                    "tool_calls": len(completion.requested_tools),
                    "usage": completion.token_usage,
                },
                step=step,
            )
        if not completion.requested_tools:
            return completion.text or ""

        messages.append(build_reply_message(completion.text, completion.requested_tools))
        for invocation in completion.requested_tools:
            messages.append(await resolve_tool_call(tool_registry, invocation, recorder, step))

    fallback = await model_client.acomplete(messages, **kwargs)
    if recorder:
        recorder.log_event("model_output", {"content": fallback.text, "note": "fallback after max_iterations"})
    return fallback.text
