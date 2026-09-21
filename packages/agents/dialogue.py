import json
from typing import Any

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


async def resolve_tool_call(tool_registry: ToolRegistry, invocation: ToolInvocation) -> dict[str, str]:
    try:
        arguments = json.loads(invocation.arguments_json)
    except json.JSONDecodeError as error:
        return {"role": "tool", "tool_call_id": invocation.call_id, "content": f"Invalid arguments: {error}"}
    outcome = await tool_registry.acall(invocation.tool_name, arguments)
    return {"role": "tool", "tool_call_id": invocation.call_id, "content": outcome.output}


async def run_tool_turn(
    model_client: ModelClient,
    messages: list[dict[str, Any]],
    tool_registry: ToolRegistry | None,
    max_iterations: int,
    **kwargs: Any,
) -> str:
    """调用 LLM -> 按需执行工具 -> 把结果喂回去，直到模型不再请求工具或用光 max_iterations。

    messages 会被原地追加 assistant/tool 消息，调用方可以在返回后继续复用它。
    """
    if tool_registry is None:
        completion = await model_client.acomplete(messages, **kwargs)
        return completion.text

    tools = tool_registry.function_schemas()
    for _ in range(max_iterations):
        completion = await model_client.acomplete_with_tools(messages, tools, **kwargs)
        if not completion.requested_tools:
            return completion.text or ""

        messages.append(build_reply_message(completion.text, completion.requested_tools))
        for invocation in completion.requested_tools:
            messages.append(await resolve_tool_call(tool_registry, invocation))

    fallback = await model_client.acomplete(messages, **kwargs)
    return fallback.text
