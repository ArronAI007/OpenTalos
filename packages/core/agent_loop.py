"""核心 Agent 运行时的执行原语：调模型 -> 解析文本/工具调用 -> 执行工具 -> 回填结果 ->
再次调用模型，直到最终输出/取消/预算耗尽。这是四种 agents/*.py 具体策略共用的引擎部分——
它们各自的差别只在"怎么拼下一轮 prompt"和"什么时候算结束"，不在这一层。
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from context import OutputTrimmer
from observability import RunRecorder
from tool.registry import ToolRegistry

from .cancellation import CancellationToken
from .protocol import ToolCompletion, ToolInvocation
from .model import ModelClient

ToolInvocationHandler = Callable[[ToolInvocation], Awaitable[dict[str, str]]]


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


def _trim_output(trimmer: OutputTrimmer | None, tool_name: str, output: str) -> str:
    """工具输出过长时只把预览回填给模型，并告诉它完整输出落在哪个文件里。"""
    if trimmer is None:
        return output

    result = trimmer.trim(tool_name, output)
    if not result.trimmed:
        return result.preview
    return (
        f"{result.preview}\n\n"
        f"[output truncated: {result.stats['original_lines']} lines / {result.stats['original_bytes']} bytes "
        f"-> kept {result.stats['kept_lines']} lines. Full output saved to {result.full_output_path}]"
    )


async def resolve_tool_call(
    tool_registry: ToolRegistry,
    invocation: ToolInvocation,
    recorder: RunRecorder | None = None,
    step: int | None = None,
    trimmer: OutputTrimmer | None = None,
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
    content = _trim_output(trimmer, invocation.tool_name, outcome.output)
    message = {"role": "tool", "tool_call_id": invocation.call_id, "content": content}
    if recorder:
        recorder.log_event("tool_result", {"tool_name": invocation.tool_name, "result": content}, step=step)
    return message


def _record_usage(cancellation: CancellationToken | None, usage: dict[str, int]) -> None:
    if cancellation is not None:
        cancellation.record_tokens(usage.get("total_tokens", 0))


async def _complete_text(
    model_client: ModelClient,
    messages: list[dict[str, Any]],
    on_text_delta: Callable[[str], Awaitable[None]] | None,
    **kwargs: Any,
) -> tuple[str, dict[str, int]]:
    """纯文本补全（不带工具schema）。on_text_delta 为空时走原来的 acomplete；给了回调就换成
    astream 逐块转发，再拼回完整文本——两条路径对调用方都返回同样的 (text, token_usage)。"""
    if on_text_delta is None:
        completion = await model_client.acomplete(messages, **kwargs)
        return completion.text, completion.token_usage

    parts: list[str] = []
    async for chunk in model_client.astream(messages, **kwargs):
        parts.append(chunk)
        await on_text_delta(chunk)
    usage = model_client.last_stream_summary.token_usage if model_client.last_stream_summary else {}
    return "".join(parts), usage


async def execute_model_step(
    model_client: ModelClient,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    recorder: RunRecorder | None = None,
    step: int | None = None,
    on_text_delta: Callable[[str], Awaitable[None]] | None = None,
    on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
    cancellation: CancellationToken | None = None,
    handle_invocation: ToolInvocationHandler,
    **kwargs: Any,
) -> ToolCompletion:
    """带工具 schema 的单步：调一次模型 -> 有工具请求就并行执行并把结果追加回 messages。

    是 run_tool_turn 和 ReActAgent 共用的最小单元——两者的循环终止条件不同（前者是"没有
    工具调用了"，后者还多一个"模型调了 finish"），但每一步"调模型 -> 记录 -> 并行跑工具 ->
    回填消息"的动作完全一样，抽成这一个函数避免两边各写一遍。handle_invocation 由调用方给，
    run_tool_turn 传 resolve_tool_call，ReActAgent 传自己的版本以拦截 finish 调用。

    每次拿到模型响应都会把它的 token_usage 喂给 cancellation.record_tokens——如果 token 传的
    是带 timeout_seconds/token_budget 的 CancellationToken，下一次检查点就会因为超时/超预算
    而自然终止整个循环，不需要调用方另外传参数。
    """
    if cancellation is not None:
        cancellation.raise_if_cancelled()

    if on_text_delta is not None or on_reasoning_delta is not None:
        completion = await model_client.astream_with_tools(
            messages, tools, on_text_delta=on_text_delta, on_reasoning_delta=on_reasoning_delta, **kwargs
        )
    else:
        completion = await model_client.acomplete_with_tools(messages, tools, **kwargs)
    _record_usage(cancellation, completion.token_usage)
    if recorder:
        recorder.log_event(
            "model_output",
            {"content": completion.text, "tool_calls": len(completion.requested_tools), "usage": completion.token_usage},
            step=step,
        )
    if not completion.requested_tools:
        return completion

    messages.append(build_reply_message(completion.text, completion.requested_tools))
    if cancellation is not None:
        cancellation.raise_if_cancelled()
    results = await asyncio.gather(*(handle_invocation(invocation) for invocation in completion.requested_tools))
    messages.extend(results)
    return completion


async def run_tool_turn(
    model_client: ModelClient,
    messages: list[dict[str, Any]],
    tool_registry: ToolRegistry | None,
    max_iterations: int,
    recorder: RunRecorder | None = None,
    on_text_delta: Callable[[str], Awaitable[None]] | None = None,
    on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
    cancellation: CancellationToken | None = None,
    trimmer: OutputTrimmer | None = None,
    **kwargs: Any,
) -> str:
    """调用 LLM -> 按需执行工具 -> 把结果喂回去，直到模型不再请求工具或用光 max_iterations。

    messages 会被原地追加 assistant/tool 消息，调用方可以在返回后继续复用它。recorder 不为空
    时，每次模型调用和每次工具调用/结果都会记一条 trace 事件。on_text_delta 不为空时用流式
    调用逐块转发文本增量。cancellation 不为空时，每次发起下一次模型调用/工具批次之前检查一次
    ——已经在执行的工具调用不会被腰斩，只影响"是否发起下一步"。trimmer 不为空时，超限的工具
    输出只把预览回填给模型，完整内容落盘。
    """
    if tool_registry is None:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        text, usage = await _complete_text(model_client, messages, on_text_delta, **kwargs)
        _record_usage(cancellation, usage)
        if recorder:
            recorder.log_event("model_output", {"content": text, "usage": usage})
        return text

    tools = tool_registry.function_schemas()

    async def handle_invocation(invocation: ToolInvocation) -> dict[str, str]:
        return await resolve_tool_call(tool_registry, invocation, recorder, step, trimmer)

    for step in range(1, max_iterations + 1):
        completion = await execute_model_step(
            model_client,
            messages,
            tools,
            recorder=recorder,
            step=step,
            on_text_delta=on_text_delta,
            on_reasoning_delta=on_reasoning_delta,
            cancellation=cancellation,
            handle_invocation=handle_invocation,
            **kwargs,
        )
        if not completion.requested_tools:
            return completion.text or ""

    fallback_text, fallback_usage = await _complete_text(model_client, messages, on_text_delta, **kwargs)
    _record_usage(cancellation, fallback_usage)
    if recorder:
        recorder.log_event("model_output", {"content": fallback_text, "note": "fallback after max_iterations"})
    return fallback_text
